from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, Iterable, List, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor

from app.config.settings import get_settings
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

_FORBIDDEN_KEYWORDS = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "grant",
    "revoke",
    "truncate",
    "vacuum",
    "analyze",
    "attach",
)
_MASK_FIELDS = ("phone", "email", "passport", "account")


class ExecMeta(Dict[str, Any]):
    """Dictionary with execution metadata."""


def _get_connection():
    conn = psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", 5432),
    )
    conn.set_session(readonly=True, autocommit=True)
    return conn


def _ensure_single_statement(sql: str) -> None:
    parts = [p.strip() for p in sql.split(";") if p.strip()]
    if len(parts) > 1:
        raise ValueError("Only single-statement queries are allowed")


def _validate_keywords(sql: str) -> None:
    lowered = sql.lower()
    if not (lowered.strip().startswith("select") or lowered.strip().startswith("with")):
        raise ValueError("Only SELECT/CTE statements are allowed")
    for keyword in _FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", lowered, flags=re.IGNORECASE):
            raise ValueError("Query contains forbidden keyword")


def _validate_tables(sql: str, allowed: Iterable[str]) -> None:
    allowed_set = {tbl.lower() for tbl in allowed if tbl}
    if not allowed_set:
        return
    pattern = re.compile(r"\b(from|join)\s+([a-zA-Z0-9_\.\"`]+)", re.IGNORECASE)
    tables = set()
    for _, table in pattern.findall(sql):
        cleaned = table.strip('`"')
        if "." in cleaned:
            cleaned = cleaned.split(".")[-1]
        tables.add(cleaned.lower())
    disallowed = tables - allowed_set
    if disallowed:
        raise ValueError(f"Query references disallowed tables: {', '.join(sorted(disallowed))}")


def _ensure_limit(sql: str, limit: int) -> Tuple[str, bool]:
    trimmed = sql.strip().rstrip(";")
    if re.search(r"\blimit\s+\d+", trimmed, re.IGNORECASE):
        return trimmed, False
    return f"SELECT * FROM ( {trimmed} ) AS limited_query LIMIT {limit}", True


def _mask_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    masked: List[Dict[str, Any]] = []
    for row in rows:
        masked_row: Dict[str, Any] = {}
        for key, value in row.items():
            lower_key = key.lower()
            if value is None:
                masked_row[key] = value
                continue
            if any(token in lower_key for token in _MASK_FIELDS):
                if "email" in lower_key and isinstance(value, str):
                    parts = value.split("@")
                    masked_row[key] = (parts[0][:2] + "***@" + parts[1]) if len(parts) == 2 else "***"
                elif isinstance(value, str):
                    masked_row[key] = value[:2] + "***" + value[-2:]
                else:
                    masked_row[key] = "***"
            else:
                masked_row[key] = value
        masked.append(masked_row)
    return masked


def execute_sql_query(sql: str, org_id: int | None = None) -> Tuple[List[Dict[str, Any]], ExecMeta]:
    settings = get_settings()

    _ensure_single_statement(sql)
    _validate_keywords(sql)
    _validate_tables(sql, settings.allowed_tables)

    sql_with_limit, limit_applied = _ensure_limit(sql, settings.max_rows)

    logger.info("-----------")
    logger.info("[SQL] Incoming query:\n%s", sql.strip())
    if limit_applied:
        logger.info("[SQL] Applied safety limit: %s rows", settings.max_rows)

    conn = _get_connection()
    start_time = time.monotonic()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SET statement_timeout TO %s", (settings.query_timeout_ms,))
            cursor.execute(sql_with_limit)
            rows = cursor.fetchall()
    finally:
        conn.close()
    duration_ms = int((time.monotonic() - start_time) * 1000)
    masked_rows = rows if not settings.pii_masking_enabled else _mask_rows(rows)
    truncated = limit_applied and len(masked_rows) >= settings.max_rows

    meta: ExecMeta = ExecMeta(
        duration_ms=duration_ms,
        row_count=len(masked_rows),
        truncated=truncated,
        limit_applied=settings.max_rows if limit_applied else None,
    )
    preview = masked_rows[:3]
    try:
        preview_text = json.dumps(preview, ensure_ascii=False, default=str)
    except Exception:
        preview_text = str(preview)
    logger.info(
        "[SQL] Completed in %sms with %s rows%s",
        duration_ms,
        len(masked_rows),
        " (truncated)" if truncated else "",
    )
    logger.info("[SQL] Preview: %s", preview_text)
    logger.info("-----------")
    return masked_rows, meta


__all__ = ["execute_sql_query", "ExecMeta"]
