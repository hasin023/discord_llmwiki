"""
Structured JSON logging via structlog.
All bot modules use `get_logger(__name__)` for consistent, parseable log output.
"""
import logging
import sys
import structlog


def setup_logging(log_level: str = "INFO") -> None:
    """Configure structlog for JSON output with stdlib integration."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a named structlog logger."""
    return structlog.get_logger(name)
