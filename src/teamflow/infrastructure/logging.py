import logging

import structlog

from teamflow.core.config import settings


def configure_logging() -> None:
    logging.basicConfig(format="%(message)s", level=settings.log_level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def bind_task_id(task_id: str) -> None:
    structlog.contextvars.bind_contextvars(task_id=task_id)


def clear_task_context() -> None:
    structlog.contextvars.clear_contextvars()
