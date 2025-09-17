import json
import logging
import os
import pathlib

import psycopg2
from fastapi import FastAPI
from pydantic import BaseModel

from app.agents import column_agent, entity_agent, input_preprocessing, intent_agent, sql_generator, table_agent
from app.pipeline.context import PipelineContext
from app.pipeline.orchestrator import Orchestrator
from app.registry.agent_registry import registry
from app.utils.logging_config import get_logger, setup_logging
from app.utils.response_formatter import render_pipeline_reply

app = FastAPI()
logger = get_logger(__name__)


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
    chat_context: list | None = None  # list of {role, content}

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
    # Define your pipeline steps.
    steps = ["input_preprocessing", "intent", "entity", "table", "column", "sql"]
    orchestrator = Orchestrator(steps)

    # Run the pipeline to get the final context dictionary.
    incoming_context = _serialize_context(request.chat_context)
    try:
        logger.info(
            "[API] Incoming query: %s | context=%s",
            request.query,
            json.dumps(incoming_context, ensure_ascii=False, default=str),
        )
    except Exception:
        logger.exception("[API] Failed to log incoming context")

    result = orchestrator.run(request.query, chat_context=request.chat_context)
    logger.info("Cleaned query: %s", result.get("cleaned_query"))

    assistant_reply = render_pipeline_reply(result)
    chat_context = list(request.chat_context or [])
    chat_context.append({"role": "user", "content": request.query})
    chat_context.append({"role": "assistant", "content": assistant_reply})
    trimmed_context = chat_context[-12:]
    result["assistant_message"] = assistant_reply
    result["chat_context"] = trimmed_context

    try:
        summary = {
            "intent": result.get("intent"),
            "entities": result.get("entities"),
            "tables": result.get("tables"),
            "columns": result.get("columns"),
            "sql": result.get("sql"),
            "followups": result.get("followup_questions"),
            "assistant_message": assistant_reply,
        }
        logger.info("[API] Pipeline result: %s", json.dumps(summary, ensure_ascii=False, default=str))
        logger.info(
            "[API] Updated context: %s",
            json.dumps(_serialize_context(trimmed_context), ensure_ascii=False, default=str),
        )
    except Exception:
        logger.exception("[API] Failed to log pipeline summary")

    # Check for missing pieces and generate follow-up questions.
    missing = []
    if not result.get("intent"):
        missing.append("intent")
    if not result.get("entities") or len(result.get("entities", {})) == 0:
        missing.append("entities")
    if not result.get("tables") or len(result.get("tables", [])) == 0:
        missing.append("tables")
    if not result.get("columns") or len(result.get("columns", {})) == 0:
        missing.append("columns")
    if not result.get("sql"):
        missing.append("sql")

    followups = []
    if "intent" in missing:
        followups.append("Что именно вы хотите узнать? Например: продуктивность сотрудников или платежи клиентов.")
    if "entities" in missing:
        followups.append("Можете уточнить временной период или имя сотрудника?")
    if "tables" in missing:
        followups.append("Пожалуйста, переформулируйте ваш запрос, чтобы я понял, какие таблицы использовать.")
    if "columns" in missing:
        followups.append("Какие данные вам важны? Например: дата, услуги или оплата.")
    if "sql" in missing:
        followups.append("Не удалось сгенерировать корректный SQL запрос. Можете ли вы переформулировать запрос?")

    # Attach fallback questions to the result.
    result["followup_questions"] = followups

    return result

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
