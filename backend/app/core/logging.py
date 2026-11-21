"""Structured logging configuration for backend, streaming, and ML services.

Supports both human-readable text logs and single-line JSON logs with safe `extra`
metadata serialization and uvicorn/app logger alignment without leaking secrets.
"""

from datetime import datetime, timezone
import functools
import json
import logging
import os
import sys
import time
from typing import Any, Callable, Optional

from backend.app.core.config import settings

_STANDARD_RECORD_ATTRS = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName", "processName",
    "process", "message", "asctime", "taskName",
})
_SENSITIVE_KEY_TOKENS = ("token", "secret", "password", "passwd", "api_key", "authorization", "credential")


def _sanitize_extra_value(key: str, value: Any) -> Any:
    lower_key = key.lower()
    if any(tok in lower_key for tok in _SENSITIVE_KEY_TOKENS):
        return "[REDACTED]"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_sanitize_extra_value(key, v) for v in value[:20]]
    if isinstance(value, dict):
        return {str(k): _sanitize_extra_value(str(k), v) for k, v in list(value.items())[:20]}
    return str(value)


def _resolve_log_level(explicit_level: Optional[str] = None) -> int:
    obs_cfg = getattr(settings, "observability", None)
    raw = (
        explicit_level
        or os.getenv("LOG_LEVEL")
        or (getattr(obs_cfg, "log_level", None) if obs_cfg is not None else None)
        or ("DEBUG" if settings.debug else "INFO")
    )
    level_name = str(raw).strip().upper()
    return getattr(logging, level_name, logging.INFO)


def _resolve_log_format(explicit_format: Optional[str] = None) -> str:
    obs_cfg = getattr(settings, "observability", None)
    raw = (
        explicit_format
        or os.getenv("LOG_FORMAT")
        or (getattr(obs_cfg, "log_format", None) if obs_cfg is not None else None)
        or settings.log_format
        or "text"
    )
    return str(raw).strip().lower()


class JsonLogFormatter(logging.Formatter):
    """Emit structured JSON logs with sanitized extra fields for machine observability."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra_fields = {
            k: _sanitize_extra_value(k, v)
            for k, v in record.__dict__.items()
            if k not in _STANDARD_RECORD_ATTRS and not k.startswith("_")
        }
        if extra_fields:
            payload["extra"] = extra_fields
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, default=str)


def _build_formatter(log_format: str) -> logging.Formatter:
    if log_format == "json":
        return JsonLogFormatter()
    return logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def configure_logging(level: Optional[str] = None, log_format: Optional[str] = None) -> None:
    """Align root, application, and uvicorn logger levels and formatters."""
    resolved_level = _resolve_log_level(level)
    resolved_fmt = _resolve_log_format(log_format)
    formatter = _build_formatter(resolved_fmt)

    for target_name in ("", "uvicorn", "uvicorn.error", "uvicorn.access"):
        target = logging.getLogger(target_name)
        target.setLevel(resolved_level)
        if target_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            for h in target.handlers:
                h.setFormatter(formatter)
        elif not target.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(formatter)
            target.addHandler(handler)
        else:
            for h in target.handlers:
                h.setFormatter(formatter)


def get_logger(name: str) -> logging.Logger:
    """Obtain or configure a standard logger aligned with runtime settings."""
    resolved_level = _resolve_log_level()
    resolved_fmt = _resolve_log_format()
    logger = logging.getLogger(name)
    logger.setLevel(resolved_level)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_build_formatter(resolved_fmt))
        logger.addHandler(handler)
        logger.propagate = False
    else:
        fmt = _build_formatter(resolved_fmt)
        for h in logger.handlers:
            h.setFormatter(fmt)
    return logger


class OperationLogger:
    """Logs system lifecycle and operational events."""

    def __init__(self, name: str):
        self._logger = get_logger(name)

    def info(self, msg: str, *args: Any):
        self._logger.info(msg, *args)

    def warning(self, msg: str, *args: Any):
        self._logger.warning(msg, *args)

    def debug(self, msg: str, *args: Any):
        self._logger.debug(msg, *args)

    def error(self, msg: str, *args: Any):
        self._logger.error(msg, *args)


class PerformanceLogger:
    """Decorator to measure and log function execution latency."""

    def __init__(self, name: str):
        self._logger = get_logger(name)

    def track(self, func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            self._logger.debug(f"START: {func.__name__}")
            try:
                res = func(*args, **kwargs)
                elapsed = time.perf_counter() - start
                self._logger.info(f"DONE: {func.__name__} in {elapsed:.4f}s")
                return res
            except Exception as e:
                elapsed = time.perf_counter() - start
                self._logger.error(f"FAILED: {func.__name__} after {elapsed:.4f}s | error: {e}")
                raise e
        return wrapper
