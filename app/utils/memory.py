"""Shared helpers for conversational memory between turns."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Dict, List

MAX_RESULT_ROWS = 20

SCOPE_BY_INTENT = {
    "list_employees": "employees",
    "create_employee": "employees",
    "delete_employee": "employees",
    "list_clients": "clients",
    "client_count": "clients",
    "client_total_spending": "clients",
    "client_last_visit": "clients",
    "frequent_clients": "clients",
    "list_services": "services",
    "list_appointments": "appointments",
    "appointment_stats": "appointments",
    "upcoming_appointments": "appointments",
}


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
    trimmed = []
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


def update_memory(memory: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    updated = deepcopy(memory) if memory else {}

    intent = result.get("intent")
    if intent:
        updated["last_intent"] = intent
        scope = SCOPE_BY_INTENT.get(intent)
        if scope:
            updated["last_scope"] = scope

    entities = result.get("entities") or {}
    if entities:
        updated["last_entities"] = entities

    sql = result.get("sql")
    if not sql:
        generated = result.get("generated_response") or {}
        sql = generated.get("sql_query")
    if sql:
        updated["last_sql"] = sql

    rows = result.get("query_result")
    trimmed_rows = _trim_rows(rows if isinstance(rows, list) else [])
    if trimmed_rows:
        updated["last_result"] = trimmed_rows

    # Specialised slots
    if trimmed_rows:
        client_names = _extract_client_list(trimmed_rows)
        if client_names:
            updated["client_list"] = client_names

        if intent == "client_count":
            first = trimmed_rows[0]
            for key in ("count", "total", "value"):
                if key in first:
                    updated["client_count"] = first[key]
                    break

    # Persist the last human-readable message for reference/debugging
    assistant_message = result.get("assistant_message") or ""
    if assistant_message:
        updated["last_message"] = assistant_message

    return updated


def format_memory_for_log(memory: Dict[str, Any]) -> str:
    try:
        return json.dumps(memory, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(memory)
