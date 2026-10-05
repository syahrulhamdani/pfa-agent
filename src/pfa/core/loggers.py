"""Loguru setup driven by LOG_LEVEL and LOG_USE_BASIC_FORMAT."""

import logging
import sys

from loguru import logger

_BASIC_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)


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
    logger.remove()
    if use_basic_format:
        logger.add(sys.stderr, level=level, format=_BASIC_FORMAT)
    else:
        logger.add(sys.stderr, level=level, serialize=True)
