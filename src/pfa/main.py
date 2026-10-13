"""FastAPI app. The lifespan runs Telegram polling in the same event loop."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from loguru import logger

from pfa.api import analytics, auth, banks, budgets, summaries, transactions
from pfa.api.deps import require_session
from pfa.api.errors import validation_error_handler
from pfa.bot.app import build_application
from pfa.bot.nudges import build_nudge_sender
from pfa.bot.summaries import build_summary_senders
from pfa.bot.uploads import UploadCoordinator
from pfa.core.config import get_settings
from pfa.core.database import create_engine, create_session_factory
from pfa.core.loggers import configure_logging
from pfa.core.tracing import configure_tracing
from pfa.graphs.chat import InsightsConfig, build_chat_graph
from pfa.graphs.extraction import build_extraction_graph
from pfa.graphs.extractors import (
    GeminiCorrectionParser,
    GeminiExtractor,
    GeminiStatementExtractor,
)
from pfa.graphs.insights import GeminiRouter, GeminiWriter, Route
from pfa.graphs.llm import build_chat_model, build_extract_model
from pfa.graphs.recommendations import build_summary_graph
from pfa.schemas.analytics import Period
from pfa.schemas.insights import InsightFacts
from pfa.services.analytics import shift_anchor, today_in
from pfa.services.auth import issue_login_link, revoke_all_sessions
from pfa.services.categories import load_category_names, seed_categories
from pfa.services.files import FileStash
from pfa.services.insights import gather_facts
from pfa.services.nudges import NudgeService
from pfa.services.scheduler import NudgeScheduler
from pfa.services.summaries import SummaryService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Starts Telegram polling on startup and stops it on shutdown."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_use_basic_format)
    if settings.langsmith_tracing and not settings.langsmith_api_key:
        logger.warning("LANGSMITH_TRACING is on but LANGSMITH_API_KEY is empty")
    if settings.tracing_enabled:
        configure_tracing()  # before any graph runs, so every trace is redacted
    logger.info(
        "LangSmith tracing {} (project: {}; receipt images are never uploaded)",
        "enabled" if settings.tracing_enabled else "disabled",
        settings.langsmith_project,
    )
    async with AsyncPostgresSaver.from_conn_string(
        settings.checkpoint_conn_string
    ) as checkpointer:
        await checkpointer.setup()
        engine = create_engine(settings)
        session_factory = create_session_factory(engine)
        app.state.session_factory = session_factory
        await seed_categories(
            session_factory, load_category_names(settings.categories_file)
        )

        chat_model = build_chat_model(settings)
        category_names = load_category_names(settings.categories_file)

        async def chat_facts(route: Route) -> InsightFacts:
            today = today_in(settings.timezone)
            period = Period(route.period)
            async with session_factory() as session:
                return await gather_facts(
                    session,
                    period,
                    shift_anchor(period, today, route.offset),
                    today,
                    category=route.category,
                    partial=route.offset == 0,  # the current period is still running
                )

        chat_graph = build_chat_graph(
            chat_model,
            checkpointer,
            InsightsConfig(
                router=GeminiRouter(chat_model, lambda: category_names),
                facts=chat_facts,
                writer=GeminiWriter(chat_model),
            ),
        )
        files = FileStash()  # receipts live in memory only
        extraction_graph = build_extraction_graph(
            session_factory=session_factory,
            extractor=GeminiExtractor(build_extract_model(settings)),
            statement_extractor=GeminiStatementExtractor(build_extract_model(settings)),
            file_source=files.get,
            parse_correction=GeminiCorrectionParser(chat_model),
            checkpointer=checkpointer,
        )
        application = build_application(settings, chat_graph)

        async def issue_link() -> str:
            return await issue_login_link(session_factory, settings)

        async def revoke_sessions() -> None:
            await revoke_all_sessions(session_factory)

        application.bot_data["issue_link"] = issue_link
        application.bot_data["revoke_sessions"] = revoke_sessions
        send_nudge = build_nudge_sender(application.bot, settings.telegram_chat_id)
        application.bot_data["send_nudge"] = send_nudge
        summary_service = SummaryService(
            session_factory,
            build_summary_graph(session_factory, GeminiWriter(chat_model)),
            settings.timezone,
        )
        send_monday_summary, send_demo_summary = build_summary_senders(
            bot=application.bot,
            chat_id=settings.telegram_chat_id,
            service=summary_service,
            issue_link=issue_link,
            ttl_minutes=settings.auth_link_ttl_minutes,
        )
        application.bot_data["send_demo_summary"] = send_demo_summary
        nudges = NudgeScheduler(
            service=NudgeService(session_factory, settings.timezone),
            send_nudge=send_nudge,
            timezone=settings.timezone,
            send_summary=send_monday_summary,
            summary_hour=settings.summary_hour,
        )
        application.bot_data["link_ttl_minutes"] = settings.auth_link_ttl_minutes
        application.bot_data["coordinator"] = UploadCoordinator(
            bot=application.bot,
            graph=extraction_graph,
            session_factory=session_factory,
            settings=settings,
            issue_link=issue_link,
            files=files,
        )
        app.state.telegram = application

        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram polling started")
        await nudges.start()
        try:
            yield
        finally:
            nudges.shutdown()
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
            logger.info("Telegram polling stopped")
            await engine.dispose()


app = FastAPI(title="pfa", lifespan=lifespan)
app.add_exception_handler(RequestValidationError, validation_error_handler)
protected = [Depends(require_session)]
app.include_router(auth.router)
app.include_router(analytics.router, dependencies=protected)
app.include_router(banks.router, dependencies=protected)
app.include_router(budgets.router, dependencies=protected)
app.include_router(summaries.router, dependencies=protected)
app.include_router(transactions.router, dependencies=protected)


@app.get("/health")
async def health() -> dict[str, str]:
    """Reports that the process is up."""
    return {"status": "ok"}
