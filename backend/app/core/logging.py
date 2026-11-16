"""Structured logging configuration for backend, streaming, and ML services.

Supports both human-readable text logs and single-line JSON logs without leaking
raw secrets or credentials.
"""

from datetime import datetime, timezone
import functools
import json
import logging
import os
import sys
import time
from typing import Any, Callable


class JsonLogFormatter(logging.Formatter):
    """Emit structured JSON logs for machine observability."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def get_logger(name: str) -> logging.Logger:
    """Obtain or configure a standard logger."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        log_format = os.getenv("LOG_FORMAT", "text").strip().lower()
        if log_format == "json":
            formatter: logging.Formatter = JsonLogFormatter()
        else:
            formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
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
