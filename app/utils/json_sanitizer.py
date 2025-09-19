from __future__ import annotations

import json
from typing import Any, Tuple


def ensure_string_sql(payload: dict[str, Any]) -> Tuple[dict[str, Any], bool]:
    value = payload.get("sql")
    if isinstance(value, str):
        return payload, True
    if isinstance(value, list) and value:
        candidate = value[0]
        if isinstance(candidate, dict):
            if "query" in candidate:
                inner = candidate["query"]
                if isinstance(inner, str):
                    payload["sql"] = inner
                    return payload, True
                # Unable to extract string query
                return payload, False
            if "cte" in candidate and "main" in candidate:
                return payload, False
        return payload, False
    if isinstance(value, dict):
        if "query" in value and isinstance(value["query"], str):
            payload["sql"] = value["query"]
            return payload, True
        return payload, False
    if value is None:
        payload["sql"] = ""
        return payload, False
    payload["sql"] = str(value)
    return payload, True


__all__ = ["ensure_string_sql"]
