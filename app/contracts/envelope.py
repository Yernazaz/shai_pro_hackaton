from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field


class ControllerEnvelope(BaseModel):
    normalized_question: str
    assumptions: List[str] = Field(default_factory=list)
    sql: str
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    analysis_text: str
    suggested_followup: List[str] = Field(default_factory=list)
    iterations_used: int = 1
    confidence: float = 0.0
    telemetry: Dict[str, Any] = Field(default_factory=dict)
    pending_state: Dict[str, Any] | None = None

    class Config:
        extra = "allow"


__all__ = ["ControllerEnvelope"]
