"""Structured logging helpers."""

import logging


def configure_logging(log_level: str) -> None:
    """Configure process-wide logging."""

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

