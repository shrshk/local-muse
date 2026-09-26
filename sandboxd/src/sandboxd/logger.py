"""Structured JSON logging for sandboxd."""

import logging
import sys
from typing import Any

import structlog


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(stream=sys.stdout, format="%(message)s", level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service="sandboxd")


def get_logger(name: str) -> Any:
    return structlog.stdlib.get_logger(name)
