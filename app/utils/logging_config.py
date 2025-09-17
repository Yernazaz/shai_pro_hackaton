import logging
import os
from typing import Optional


def _env_level(default: str = "INFO") -> int:
    level_name = os.getenv("LOG_LEVEL", default).upper()
    return getattr(logging, level_name, logging.INFO)


def setup_logging(level: Optional[str] = None) -> None:
    """Configure root logging once. Safe to call multiple times."""
    if logging.getLogger().handlers:
        # Already configured
        return
    fmt = "% (asctime)s - %(levelname)s - %(name)s - %(message)s".replace(" ", "")
    logging.basicConfig(
        level=_env_level(level or os.getenv("LOG_LEVEL", "INFO")),
        format=fmt,
    )


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)

