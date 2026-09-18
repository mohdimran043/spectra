"""Structured logging with request / investigation / tool-call correlation IDs."""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
investigation_id_var: ContextVar[str | None] = ContextVar("investigation_id", default=None)
tool_call_id_var: ContextVar[str | None] = ContextVar("tool_call_id", default=None)

_CONFIGURED = False


def _inject_context(_logger: Any, _name: str, event_dict: dict) -> dict:
    for key, var in (
        ("request_id", request_id_var),
        ("investigation_id", investigation_id_var),
        ("tool_call_id", tool_call_id_var),
    ):
        value = var.get()
        if value:
            event_dict[key] = value
    return event_dict


def configure_logging(level: str = "INFO", fmt: str = "console") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    for noisy in ("httpx", "httpcore", "urllib3", "sentence_transformers", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    renderer = (
        structlog.processors.JSONRenderer()
        if fmt == "json"
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _inject_context,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str) -> structlog.BoundLogger:
    if not _CONFIGURED:
        configure_logging()
    return structlog.get_logger(name)
