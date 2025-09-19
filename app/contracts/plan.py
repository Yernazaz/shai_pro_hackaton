from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class TimeRange(BaseModel):
    start: Optional[str] = Field(default=None, alias="from")
    end: Optional[str] = Field(default=None, alias="to")

    class Config:
        populate_by_name = True
        extra = "allow"


class Filter(BaseModel):
    column: str
    op: str
    value: Any

    class Config:
        extra = "allow"


class Entities(BaseModel):
    tables: List[str] = Field(default_factory=list)
    columns: List[str] = Field(default_factory=list)
    time_range: Optional[TimeRange] = None
    filters: List[Filter] = Field(default_factory=list)
    group_by: List[str] = Field(default_factory=list)
    metrics: List[str] = Field(default_factory=list)

    class Config:
        populate_by_name = True
        extra = "allow"


class PlanOut(BaseModel):
    normalized_question: str = Field(..., description="Нормализованный вопрос пользователя")
    assumptions: List[str] = Field(default_factory=list)
    entities: Entities = Field(default_factory=Entities)
    dialect: str = Field(..., description="SQL диалект")
    sql: str = Field(..., description="Сгенерированный SQL")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_user_clarification: bool = Field(default=False)

    class Config:
        populate_by_name = True
        extra = "allow"


class PlanValidationError(RuntimeError):
    def __init__(self, raw_payload: str, error: Exception):
        super().__init__("Failed to validate plan output")
        self.raw_payload = raw_payload
        self.error = error


__all__ = [
    "PlanOut",
    "Entities",
    "Filter",
    "TimeRange",
    "PlanValidationError",
]
