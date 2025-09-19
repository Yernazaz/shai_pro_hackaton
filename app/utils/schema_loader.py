from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any

DEFAULT_SCHEMA_PATH = Path("data/schema_metadata.json")


@lru_cache(maxsize=1)
def load_schema(schema_path: str | Path = DEFAULT_SCHEMA_PATH) -> Dict[str, Any]:
    path = Path(schema_path)
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def build_schema_brief(max_columns: int = 12) -> str:
    schema = load_schema()
    lines: list[str] = []
    for table, meta in schema.items():
        lines.append(f"{table}:")
        columns = meta.get("columns", {})
        for idx, (column, description) in enumerate(columns.items()):
            if idx >= max_columns:
                remaining = len(columns) - max_columns
                if remaining > 0:
                    lines.append(f"  - … (+{remaining} columns)")
                break
            lines.append(f"  - {column}: {description}")
    return "\n".join(lines)


__all__ = ["load_schema", "build_schema_brief"]
