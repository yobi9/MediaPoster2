"""Logging with rotation, secret redaction and a bridge for the Qt console."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import LOG_PATH

SUCCESS_LEVEL = 25
logging.addLevelName(SUCCESS_LEVEL, "SUCCESS")

_SECRET_PATTERNS = (
    re.compile(r"(api_key=)[^&\s\"']+", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE),
    re.compile(r"([?&]token=)[^&\s\"']+", re.IGNORECASE),
)


class RedactionFilter(logging.Filter):
    """Make sure keys never reach app_log.txt or the GUI console."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        for pattern in _SECRET_PATTERNS:
            message = pattern.sub(r"\1***", message)
        record.msg = message
        record.args = ()
        if record.exc_info:
            # Keep the traceback but scrub its rendered text as well.
            record.exc_text = None
        return True


_configured = False


def setup_logging(
    log_path: Path | None = None,
    *,
    console: bool = True,
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure the ``mediaart`` logger once and return it."""
    global _configured
    logger = logging.getLogger("mediaart")
    if _configured:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    target = log_path or LOG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        target,
        maxBytes=3_000_000,
        backupCount=3,
        encoding="utf-8",
        delay=True,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
            "%Y-%m-%d %H:%M:%S",
        )
    )
    file_handler.addFilter(RedactionFilter())
    logger.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        console_handler.addFilter(RedactionFilter())
        logger.addHandler(console_handler)

    _configured = True
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    base = "mediaart"
    return logging.getLogger(f"{base}.{name}" if name else base)


def log_success(logger: logging.Logger, message: str, *args: object) -> None:
    logger.log(SUCCESS_LEVEL, message, *args)
