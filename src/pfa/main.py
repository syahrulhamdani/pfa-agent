"""FastAPI app. The lifespan runs Telegram polling in the same event loop."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from loguru import logger

from pfa.api import auth, banks, transactions
from pfa.api.deps import require_session
from pfa.bot.app import build_application
from pfa.bot.uploads import UploadCoordinator
from pfa.core.config import get_settings
from pfa.core.database import create_engine, create_session_factory
from pfa.core.loggers import configure_logging
from pfa.graphs.chat import build_chat_graph
from pfa.graphs.extraction import build_extraction_graph
from pfa.graphs.extractors import GeminiCorrectionParser, GeminiExtractor
from pfa.graphs.llm import build_chat_model, build_extract_model
from pfa.services.auth import issue_login_link, revoke_all_sessions
from pfa.services.categories import load_category_names, seed_categories
from pfa.services.images import ImageStash


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Starts Telegram polling on startup and stops it on shutdown."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_use_basic_format)
    if settings.langsmith_tracing and not settings.langsmith_api_key:
        logger.warning("LANGSMITH_TRACING is on but LANGSMITH_API_KEY is empty")
    logger.info(
        "LangSmith tracing {} (project: {})",
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
        chat_graph = build_chat_graph(chat_model, checkpointer)
        images = ImageStash()  # receipts live in memory only
        extraction_graph = build_extraction_graph(
            session_factory=session_factory,
            extractor=GeminiExtractor(build_extract_model(settings)),
            image_source=images.get,
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
        application.bot_data["link_ttl_minutes"] = settings.auth_link_ttl_minutes
        application.bot_data["coordinator"] = UploadCoordinator(
            bot=application.bot,
            graph=extraction_graph,
            session_factory=session_factory,
            settings=settings,
            issue_link=issue_link,
            images=images,
        )
        app.state.telegram = application

        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram polling started")
        try:
            yield
        finally:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
            logger.info("Telegram polling stopped")
            await engine.dispose()


app = FastAPI(title="pfa", lifespan=lifespan)
protected = [Depends(require_session)]
app.include_router(auth.router)
app.include_router(banks.router, dependencies=protected)
app.include_router(transactions.router, dependencies=protected)


@app.get("/health")
async def health() -> dict[str, str]:
    """Reports that the process is up."""
    return {"status": "ok"}
