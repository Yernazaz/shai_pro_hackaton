"""Helpers for conversational memory between turns."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from app.contracts.envelope import ControllerEnvelope

MAX_RESULT_ROWS = 20


def initialise_memory(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    if isinstance(raw, dict):
        try:
            return deepcopy(raw)
        except Exception:
            return dict(raw)
    return {}


def _trim_rows(rows: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    trimmed: List[Dict[str, Any]] = []
    for row in rows[:MAX_RESULT_ROWS]:
        if isinstance(row, dict):
            trimmed.append(row)
    return trimmed


def _extract_client_list(rows: List[Dict[str, Any]]) -> List[str]:
    names = []
    for row in rows:
        first = (row.get("first_name") or "").strip()
        last = (row.get("last_name") or "").strip()
        full = " ".join(part for part in (first, last) if part)
        if full:
            names.append(full)
    return names


def update_memory(memory: Dict[str, Any], envelope: ControllerEnvelope) -> Dict[str, Any]:
    updated = deepcopy(memory) if memory else {}

    trimmed_rows = _trim_rows(envelope.rows)
    if trimmed_rows:
        updated["last_result"] = trimmed_rows
        client_list = _extract_client_list(trimmed_rows)
        if client_list:
            updated["client_list"] = client_list
    if envelope.sql:
        updated["last_sql"] = envelope.sql
    if envelope.analysis_text:
        updated["last_message"] = envelope.analysis_text
    if envelope.normalized_question:
        updated["last_normalized_question"] = envelope.normalized_question
    updated["rows_count"] = len(envelope.rows)
    updated["iterations_used"] = envelope.iterations_used
    updated["confidence"] = envelope.confidence
    return updated


__all__ = ["initialise_memory", "update_memory"]
