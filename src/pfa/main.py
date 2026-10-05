"""FastAPI app. The lifespan runs Telegram polling in the same event loop."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from pfa.bot.app import build_application
from pfa.core.config import get_settings
from pfa.core.loggers import configure_logging
from pfa.graphs.chat import build_chat_graph
from pfa.graphs.llm import build_chat_model


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
    chat_graph = build_chat_graph(build_chat_model(settings))
    application = build_application(settings, chat_graph)
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


app = FastAPI(title="pfa", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Reports that the process is up."""
    return {"status": "ok"}
