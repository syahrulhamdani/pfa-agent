"""Loguru setup driven by LOG_LEVEL and LOG_USE_BASIC_FORMAT."""

import logging
import sys

from loguru import logger

_BASIC_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)


class InterceptHandler(logging.Handler):
    """Routes standard-library logging, as used by Telegram and httpx, to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        """Forwards one record to loguru, keeping its level and exception."""
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def configure_logging(level: str, use_basic_format: bool) -> None:
    """Configures loguru.

    Args:
        level: Minimum log level, such as "INFO".
        use_basic_format: True for a readable local format; False for
            structured JSON suitable for production.
    """
    # The Google SDK warns about automatic function calling on every first call;
    # we use no tools, so keep only its errors.
    logging.getLogger("google_genai.models").setLevel(logging.ERROR)
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    # httpx logs every Telegram poll at INFO, which drowns everything else.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logger.remove()
    if use_basic_format:
        logger.add(sys.stderr, level=level, format=_BASIC_FORMAT, diagnose=False)
    else:
        logger.add(sys.stderr, level=level, serialize=True, diagnose=False)
