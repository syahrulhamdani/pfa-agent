"""Boundary: configure_logging sets up loguru and quiets the Google SDK."""

import logging

from pfa.core.loggers import configure_logging


def test_configure_logging_quiets_google_sdk():
    configure_logging("INFO", use_basic_format=True)
    assert logging.getLogger("google_genai.models").level == logging.ERROR


def test_configure_logging_supports_json_format():
    configure_logging("INFO", use_basic_format=False)  # must not raise


def test_stdlib_logging_reaches_loguru():
    from loguru import logger

    configure_logging("INFO", use_basic_format=True)
    captured: list[str] = []
    sink = logger.add(lambda m: captured.append(m.record["message"]), level="INFO")
    try:
        logging.getLogger("telegram.ext.Application").error("handler blew up")
    finally:
        logger.remove(sink)
    assert "handler blew up" in captured
