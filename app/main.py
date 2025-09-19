import json
import logging
import os
import pathlib

import psycopg2
from fastapi import FastAPI
from pydantic import BaseModel

from app.config.settings import get_settings
from app.pipeline.controller import IterativeController
from app.utils.logging_config import get_logger, setup_logging
from app.utils.memory import initialise_memory, update_memory
from app.utils.response_formatter import render_pipeline_reply
from app.utils.query_rewrite import rewrite_query_with_context
from app.utils.schema_loader import build_schema_brief

app = FastAPI()
logger = get_logger(__name__)
controller = IterativeController()
settings = get_settings()
SCHEMA_BRIEF = build_schema_brief()


def _serialize_context(context_list: list | None):
    if not context_list:
        return []
    serialized = []
    for item in context_list[-12:]:
        role = item.get("role") if isinstance(item, dict) else None
        content = item.get("content") if isinstance(item, dict) else None
        serialized.append({"role": role, "content": content})
    return serialized

class QueryRequest(BaseModel):
    query: str
    original_query: str | None = None
    session_id: str | None = None
    chat_context: list | None = None  # deprecated
    memory: dict | None = None
    pending_state: dict | None = None
    org_id: int | None = None

@app.on_event("startup")
def _startup_warmup():
    # Initialize logging early
    setup_logging()
    # Preload frequently used caches (best-effort)
    try:
        from scripts.employee_names import load_employee_names
        load_employee_names()
    except Exception:
        # DB may be unavailable at startup in some environments
        pass

@app.post("/query")
def handle_query(request: QueryRequest):
    incoming_context = []
    incoming_memory = initialise_memory(request.memory)
    display_query = request.original_query or request.query
    try:
        logger.info("[API] Incoming query: %s", display_query)
    except Exception:
        logger.exception("[API] Failed to log incoming context")

    rewritten_query = request.query

    pending_state = request.pending_state or {}
    pending_notes = pending_state.get("assumptions")
    contextual_notes = ""
    if pending_notes:
        contextual_notes = "\n".join(str(note) for note in pending_notes if note)

    runtime_context = {
        "org_id": request.org_id,
        "schema_brief": SCHEMA_BRIEF,
        "contextual_notes": contextual_notes,
        "allowed_tables": settings.allowed_tables,
        "dialect": settings.db_dialect,
        "pending_state": pending_state,
    }

    envelope = controller.run(rewritten_query, runtime_context)

    assistant_reply = render_pipeline_reply(envelope)

    updated_memory = update_memory(incoming_memory, envelope)
    updated_memory["last_query"] = request.query
    updated_memory["last_cleaned_query"] = rewritten_query

    result_payload = {
        "original_query": display_query,
        "normalized_question": envelope.normalized_question,
        "rephrased_query": rewritten_query,
        "sql": envelope.sql,
        "rows": envelope.rows,
        "analysis_text": envelope.analysis_text,
        "suggested_followup": envelope.suggested_followup,
        "iterations_used": envelope.iterations_used,
        "confidence": envelope.confidence,
        "telemetry": envelope.telemetry,
        "assistant_message": assistant_reply,
        "memory": updated_memory,
        "pending_state": envelope.pending_state,
    }

    try:
        preview_rows = envelope.rows[:3] if isinstance(envelope.rows, list) else []
        formatted_preview = [
            ", ".join(f"{k}: {v}" for k, v in row.items()) if isinstance(row, dict) else str(row)
            for row in preview_rows
        ]
        logger.info("-----------")
        logger.info("[API] SQL: %s", envelope.sql or "<empty>")
        logger.info("[API] Rows(%d): %s", len(envelope.rows), formatted_preview)
        logger.info("[API] Analysis: %s", envelope.analysis_text)
        logger.info("-----------")
    except Exception:
        logger.exception("[API] Failed to log controller envelope")

    return result_payload

@app.get("/healthz")
def healthz():
    checks = {"db": False, "faiss": False}
    # Check DB connectivity
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT", 5432)
        )
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            _ = cur.fetchone()
        conn.close()
        checks["db"] = True
    except Exception:
        checks["db"] = False

    # Check FAISS index files exist
    root = pathlib.Path(__file__).resolve().parents[1]
    faiss_dir = root / "faiss_index"
    needed = [faiss_dir / "tables.index", faiss_dir / "columns.index", faiss_dir / "table_ids.pkl", faiss_dir / "column_ids.pkl"]
    checks["faiss"] = all(p.exists() for p in needed)

    status = 200 if all(checks.values()) else 503
    return {"status": status, **checks}
