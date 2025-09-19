from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError


class AnalysisOut(BaseModel):
    final_answer: str = Field(..., description="Человекочитаемый вывод")
    explanations: List[str] = Field(default_factory=list)
    suggested_followup: List[str] = Field(default_factory=list)
    needs_iteration: bool = Field(default=False)
    iteration_reason: Optional[str] = Field(default=None)
    next_query_hint: Optional[str] = Field(default=None)

    class Config:
        extra = "allow"


class AnalysisValidationError(RuntimeError):
    def __init__(self, raw_payload: str, validation_error: ValidationError):
        super().__init__("Failed to validate analysis output")
        self.raw_payload = raw_payload
        self.validation_error = validation_error


__all__ = [
    "AnalysisOut",
    "AnalysisValidationError",
]
