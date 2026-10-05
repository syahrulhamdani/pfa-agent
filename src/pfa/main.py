"""FastAPI app. The lifespan runs Telegram polling in the same event loop."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from loguru import logger

from pfa.api import banks
from pfa.bot.app import build_application
from pfa.bot.uploads import UploadCoordinator
from pfa.core.config import get_settings
from pfa.core.database import create_engine, create_session_factory
from pfa.core.loggers import configure_logging
from pfa.graphs.chat import build_chat_graph
from pfa.graphs.extraction import build_extraction_graph
from pfa.graphs.extractors import GeminiCorrectionParser, GeminiExtractor
from pfa.graphs.llm import build_chat_model, build_extract_model
from pfa.services.categories import load_category_names, seed_categories


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
        extraction_graph = build_extraction_graph(
            session_factory=session_factory,
            extractor=GeminiExtractor(build_extract_model(settings)),
            parse_correction=GeminiCorrectionParser(chat_model),
            checkpointer=checkpointer,
        )
        application = build_application(settings, chat_graph)
        application.bot_data["coordinator"] = UploadCoordinator(
            bot=application.bot,
            graph=extraction_graph,
            session_factory=session_factory,
            settings=settings,
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
app.include_router(banks.router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Reports that the process is up."""
    return {"status": "ok"}
