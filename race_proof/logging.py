"""Structured Logging Facility for RaceProof.

Provides formatted rich console logging for interactive CLI/TUI sessions
and structured JSON logging for automated enterprise CI/CD / SIEM ingestion.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

from rich.console import Console
from rich.logging import RichHandler

from race_proof.config import config

_LOGGER_INITIALIZED = False


def setup_logging(
    level: str | None = None,
    json_format: bool = False,
    stream: Any = sys.stderr,
) -> logging.Logger:
    """Initialize structured logging for RaceProof."""
    global _LOGGER_INITIALIZED
    log_level = (level or config.log_level).upper()

    logger = logging.getLogger("race_proof")
    logger.setLevel(getattr(logging, log_level, logging.INFO))

    # Remove existing handlers to avoid duplicate lines
    logger.handlers.clear()

    if json_format:
        formatter = logging.Formatter(
            '{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}'
        )
        handler = logging.StreamHandler(stream)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    else:
        console = Console(file=stream, highlight=False)
        handler = RichHandler(
            console=console,
            show_time=False,
            show_path=False,
            markup=True,
            rich_tracebacks=True,
        )
        logger.addHandler(handler)

    logger.propagate = False
    _LOGGER_INITIALIZED = True
    return logger


def get_logger(name: str = "race_proof") -> logging.Logger:
    """Retrieve or initialize a named logger."""
    global _LOGGER_INITIALIZED
    if not _LOGGER_INITIALIZED:
        return setup_logging()
    return logging.getLogger(name)

