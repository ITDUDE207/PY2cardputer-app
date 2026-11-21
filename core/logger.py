"""Logging with secret redaction.

The API key must never reach a log file, the GUI terminal, or an exception
message. Every secret registered here is replaced with ``***REDACTED***`` in
both log records and ad-hoc strings.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

REDACTED = "***REDACTED***"
MIN_SECRET_LENGTH = 6

_SECRETS: set[str] = set()
_LOCK = threading.Lock()

# Catches bearer tokens and common key formats even if a secret was never
# registered (for example a token echoed by a third-party tool).
_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s\"']+"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)(https?://)[^/\s@]+@"),
)


def register_secret(value: str | None) -> None:
    """Register a value that must be redacted from all output."""
    if not value or len(value) < MIN_SECRET_LENGTH:
        return
    with _LOCK:
        _SECRETS.add(value)


def clear_secrets() -> None:
    """Forget registered secrets (used by tests)."""
    with _LOCK:
        _SECRETS.clear()


def redact(text: object) -> str:
    """Return ``text`` with registered secrets and token patterns masked."""
    result = "" if text is None else str(text)
    with _LOCK:
        secrets = sorted(_SECRETS, key=len, reverse=True)
    for secret in secrets:
        if secret in result:
            result = result.replace(secret, REDACTED)
    for pattern in _PATTERNS:
        result = pattern.sub(lambda m: f"{m.group(1)}{REDACTED}" if m.groups() else REDACTED, result)
    return result


class RedactingFilter(logging.Filter):
    """Scrub secrets from messages, arguments and tracebacks."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            message = str(record.msg)
        record.msg = redact(message)
        record.args = ()
        if record.exc_info and record.exc_info[0] is not None:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


def build_logger(
    name: str = "py2cardputer",
    *,
    log_dir: Path | str | None = None,
    log_file: str = "py2cardputer.log",
    level: int = logging.INFO,
    console: bool = True,
    max_bytes: int = 2_000_000,
    backup_count: int = 5,
) -> logging.Logger:
    """Create (or reuse) a logger with redacting console and file handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    redactor = RedactingFilter()

    if console:
        stream = logging.StreamHandler(stream=sys.stderr)
        stream.setFormatter(formatter)
        stream.addFilter(redactor)
        logger.addHandler(stream)

    if log_dir is not None:
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            directory / log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redactor)
        logger.addHandler(file_handler)

    return logger


def add_job_log_file(logger: logging.Logger, log_path: Path | str) -> logging.Handler:
    """Attach a dedicated per-job log file and return the handler."""
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    return handler
