"""Structured logging (structlog). Console renderer in dev, JSON in prod.

"Everything is logged" is a core non-negotiable — this is the base logger; the
durable audit trail (Postgres `audit_log`) is layered on top in later phases.
"""
from __future__ import annotations

import logging
import sys

import structlog

from config.settings import get_settings

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    s = get_settings()
    level = getattr(logging, s.log_level.upper(), logging.INFO)

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if s.log_json
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str | None = None):
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)
