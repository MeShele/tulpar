"""Logging configuration for Tulpar Express.

Provides structured logging with:
- JSON format for production
- Console format for development
- Sensitive data filtering
- Log rotation (30 days retention)
"""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, MutableMapping

import structlog

# Default log settings
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FORMAT = "json"  # "json" or "console"
DEFAULT_LOG_FILE = "logs/tulpar.log"
DEFAULT_LOG_RETENTION_DAYS = 30

# Sensitive keys patterns to mask
SENSITIVE_PATTERNS = [
    re.compile(r".*token.*", re.IGNORECASE),
    re.compile(r".*key.*", re.IGNORECASE),
    re.compile(r".*secret.*", re.IGNORECASE),
    re.compile(r".*password.*", re.IGNORECASE),
    re.compile(r".*credential.*", re.IGNORECASE),
    re.compile(r"authorization", re.IGNORECASE),
]

# Mask placeholder
MASK = "***REDACTED***"


def _is_sensitive_key(key: str) -> bool:
    """Check if a key contains sensitive information.

    Args:
        key: The key name to check.

    Returns:
        True if the key matches any sensitive pattern.
    """
    return any(pattern.match(key) for pattern in SENSITIVE_PATTERNS)


def _mask_sensitive_value(value: Any) -> Any:
    """Mask a sensitive value.

    Args:
        value: The value to mask.

    Returns:
        Masked value or original if not a string.
    """
    if isinstance(value, str) and len(value) > 0:
        # Show first 4 chars if long enough, otherwise just mask
        if len(value) > 8:
            return value[:4] + MASK
        return MASK
    return value


def _mask_dict_recursive(data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Recursively mask sensitive data in a dictionary.

    Args:
        data: Dictionary to process.

    Returns:
        Dictionary with sensitive values masked.
    """
    result = {}
    for key, value in data.items():
        if _is_sensitive_key(key):
            result[key] = _mask_sensitive_value(value)
        elif isinstance(value, dict):
            result[key] = _mask_dict_recursive(value)
        elif isinstance(value, list):
            result[key] = [
                _mask_dict_recursive(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


class SensitiveDataFilter:
    """structlog processor that filters sensitive data from logs."""

    def __call__(
        self,
        logger: logging.Logger,
        method_name: str,
        event_dict: MutableMapping[str, Any],
    ) -> MutableMapping[str, Any]:
        """Filter sensitive data from the event dictionary.

        Args:
            logger: The logger instance.
            method_name: The logging method name.
            event_dict: The event dictionary to process.

        Returns:
            Event dictionary with sensitive data masked.
        """
        return _mask_dict_recursive(event_dict)


def _get_log_level(level_name: str) -> int:
    """Convert log level name to logging constant.

    Args:
        level_name: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).

    Returns:
        Logging level constant.
    """
    levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return levels.get(level_name.upper(), logging.INFO)


def _create_file_handler(
    log_file: str | Path,
    retention_days: int,
) -> TimedRotatingFileHandler:
    """Create a rotating file handler.

    Args:
        log_file: Path to the log file.
        retention_days: Number of days to retain logs.

    Returns:
        Configured TimedRotatingFileHandler.
    """
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = TimedRotatingFileHandler(
        filename=str(log_path),
        when="midnight",
        interval=1,
        backupCount=retention_days,
        encoding="utf-8",
    )
    return handler


def configure_logging(
    level: str = DEFAULT_LOG_LEVEL,
    log_format: str = DEFAULT_LOG_FORMAT,
    log_file: str | None = None,
    retention_days: int = DEFAULT_LOG_RETENTION_DAYS,
    enable_console: bool = True,
) -> None:
    """Configure structured logging for the application.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_format: Output format ("json" or "console").
        log_file: Path to log file (None for console only).
        retention_days: Days to retain log files (default 30).
        enable_console: Whether to output to console.

    Example:
        >>> configure_logging(level="DEBUG", log_format="console")
        >>> configure_logging(level="INFO", log_format="json", log_file="logs/app.log")
    """
    log_level = _get_log_level(level)

    # Configure standard logging
    handlers: list[logging.Handler] = []

    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        handlers.append(console_handler)

    if log_file:
        file_handler = _create_file_handler(log_file, retention_days)
        file_handler.setLevel(log_level)
        handlers.append(file_handler)

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        handlers=handlers,
        force=True,
    )

    # Choose renderer based on format
    if log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # Configure structlog processors
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        SensitiveDataFilter(),
    ]

    # Configure structlog
    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Create formatter for stdlib handlers
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # Apply formatter to all handlers
    for handler in handlers:
        handler.setFormatter(formatter)

    structlog.get_logger().info(
        "logging_configured",
        level=level,
        format=log_format,
        log_file=log_file,
        retention_days=retention_days if log_file else None,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a configured logger instance.

    Args:
        name: Optional logger name.

    Returns:
        Configured structlog BoundLogger.
    """
    return structlog.get_logger(name)


# Convenience exports
__all__ = [
    "configure_logging",
    "get_logger",
    "SensitiveDataFilter",
    "SENSITIVE_PATTERNS",
    "MASK",
    "DEFAULT_LOG_LEVEL",
    "DEFAULT_LOG_FORMAT",
    "DEFAULT_LOG_FILE",
    "DEFAULT_LOG_RETENTION_DAYS",
]
