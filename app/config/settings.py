from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, List

from app.utils.gemini_config import get_gemini_model


def _split_csv(value: str | None) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings:
    """Centralised runtime configuration for the NL→SQL pipeline."""

    def __init__(self) -> None:
        self.db_dialect: str = os.getenv("DB_DIALECT", "postgres").lower()
        self.allowed_tables: List[str] = _split_csv(os.getenv("ALLOWED_TABLES"))
        self.default_time_window: str = os.getenv("DEFAULT_TIME_WINDOW", "").strip()
        self.timezone: str = os.getenv("APP_TIMEZONE", "UTC")
        self.max_rows: int = int(os.getenv("QUERY_MAX_ROWS", "500"))
        self.query_timeout_ms: int = int(float(os.getenv("QUERY_TIMEOUT_SECONDS", "30")) * 1000)
        self.enable_iterations: bool = os.getenv("ENABLE_ITERATIONS", "1").lower() in {"1", "true", "yes"}
        default_model = get_gemini_model()
        self.llm_plan_model: str = os.getenv("LLM_PLAN_MODEL") or default_model
        self.llm_analysis_model: str = os.getenv("LLM_ANALYSIS_MODEL") or default_model
        self.llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0"))
        self.redis_host: str = os.getenv("REDIS_HOST", "localhost")
        self.redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
        self.redis_db: int = int(os.getenv("REDIS_DB", "0"))
        self.context_ttl_seconds: int = int(os.getenv("CONTEXT_TTL_SECONDS", "60"))
        self.enable_context_memory: bool = os.getenv("ENABLE_CONTEXT_MEMORY", "1").lower() in {"1", "true", "yes"}
        self.pii_masking_enabled: bool = os.getenv("PII_MASKING_ENABLED", "0").lower() in {"1", "true", "yes"}

    def as_prompt_context(self) -> Dict[str, str]:
        return {
            "dialect": self.db_dialect,
            "allowed_tables": ", ".join(self.allowed_tables) if self.allowed_tables else "*",
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


__all__ = ["Settings", "get_settings"]
