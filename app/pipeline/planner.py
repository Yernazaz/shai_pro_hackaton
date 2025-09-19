from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from pydantic import ValidationError

from app.config.settings import get_settings
from app.contracts.plan import PlanOut, PlanValidationError
from app.utils.json_sanitizer import ensure_string_sql
from app.utils.llm_client import chat_completion
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

_PROMPT_CACHE: Dict[str, str] = {}


def _load_prompt(name: str) -> str:
    if name in _PROMPT_CACHE:
        return _PROMPT_CACHE[name]
    path = Path(__file__).resolve().parent / "prompts" / name
    content = path.read_text(encoding="utf-8")
    _PROMPT_CACHE[name] = content
    return content


def _render_prompt(template: str, replacements: Dict[str, Any]) -> str:
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered


def _extract_json_block(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Response does not contain JSON object")
    return text[start : end + 1]


def _normalize_entities(entities: Any) -> Dict[str, Any]:
    """Coerce various LLM outputs for entities into the Entities dict shape.

    Accepts:
    - dict: returned as-is
    - list[str]: split to tables/columns heuristically
    - list[dict]: extract tables/columns/filters when obvious
    - str: treated as a single table name
    - otherwise: empty dict
    """
    def _is_filter(obj: Dict[str, Any]) -> bool:
        return all(k in obj for k in ("column", "op", "value"))

    if entities is None:
        return {}
    if isinstance(entities, dict):
        return entities
    if isinstance(entities, str):
        name = entities.strip()
        if not name:
            return {}
        return {"tables": [name]}
    if isinstance(entities, list):
        tables: List[str] = []
        columns: List[str] = []
        filters: List[Dict[str, Any]] = []
        group_by: List[str] = []
        metrics: List[str] = []
        time_range: Dict[str, Any] | None = None

        for item in entities:
            if isinstance(item, str):
                s = item.strip()
                if not s:
                    continue
                if "." in s:
                    columns.append(s)
                else:
                    tables.append(s)
                continue

            if isinstance(item, dict):
                # Filters like {column, op, value}
                if _is_filter(item):
                    filters.append(item)
                    continue

                # time range variants
                if ("from" in item or "to" in item) and time_range is None:
                    time_range = {k: v for k, v in item.items() if k in ("from", "to", "start", "end")}
                    continue

                # Extract table name from common keys
                for key in ("table", "entity", "name", "entity_name"):
                    if key in item and isinstance(item[key], str):
                        t = item[key].strip()
                        if t:
                            tables.append(t)
                        break

                # Extract column name
                if "column" in item and isinstance(item["column"], str):
                    c = item["column"].strip()
                    if c:
                        columns.append(c)

                # group_by / metrics hints
                if "group_by" in item and isinstance(item["group_by"], list):
                    group_by.extend([str(x) for x in item["group_by"]])
                if "metrics" in item and isinstance(item["metrics"], list):
                    metrics.extend([str(x) for x in item["metrics"]])
                continue

        result: Dict[str, Any] = {}
        if tables:
            result["tables"] = sorted(set(tables))
        if columns:
            result["columns"] = sorted(set(columns))
        if filters:
            result["filters"] = filters
        if group_by:
            result["group_by"] = sorted(set(group_by))
        if metrics:
            result["metrics"] = sorted(set(metrics))
        if time_range is not None:
            result["time_range"] = time_range
        return result

    # Fallback
    return {}


def plan_query(raw_question: str, context: Dict[str, Any]) -> PlanOut:
    settings = get_settings()

    allowed_tables = context.get("allowed_tables") or settings.allowed_tables
    schema_brief = context.get("schema_brief", "(schema summary unavailable)")
    contextual_notes = context.get("contextual_notes", "")
    lowered_question = raw_question.lower()
    if any(token in lowered_question for token in ("последн", "last")):
        extra_note = (
            "Если в вопросе упоминается 'последний раз' или аналогичное,"
            " не ограничивай период по умолчанию и просто найди максимальную дату/время."
        )
        contextual_notes = f"{contextual_notes}\n{extra_note}" if contextual_notes else extra_note
    if (
        any(token in lowered_question for token in ("самый", "лучший", "top", "больше всего", "чаще всех"))
        and not any(period in lowered_question for period in ("день", "недел", "месяц", "год", "30", "7", "24"))
    ):
        extra_note = (
            "Если пользователь спрашивает про 'самый'/ 'больше всего' без указания периода,"
            " анализируй весь доступный диапазон данных и не применяй окно по умолчанию."
        )
        contextual_notes = f"{contextual_notes}\n{extra_note}" if contextual_notes else extra_note
    replacements = {
        "dialect": context.get("dialect", settings.db_dialect),
        "allowed_tables": ", ".join(allowed_tables) if allowed_tables else "*",
        "user_question": raw_question,
        "schema_brief": schema_brief,
        "contextual_notes": contextual_notes or "-",
    }

    system_prompt = _render_prompt(_load_prompt("plan_v1.txt"), replacements)
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": "Верни строго валидный JSON по схеме PlanOut без какого-либо текста снаружи.",
        },
    ]

    last_error: Exception | None = None
    for attempt in range(3):
        logger.info("[Planner] Calling LLM for plan (attempt %s)", attempt + 1)
        try:
            response = chat_completion(
                model=settings.llm_plan_model,
                messages=messages,
                temperature=settings.llm_temperature,
            )
        except Exception as exc:
            logger.error("[Planner] LLM call failed: %s", exc)
            last_error = exc
            break

        if isinstance(response, dict):
            message = response["choices"][0]["message"]
            content = message.get("content", "")
        else:
            message = response.choices[0].message
            content = getattr(message, "content", "")

        try:
            json_payload = _extract_json_block(content or "")
            payload_dict = json.loads(json_payload)
            if "normalized_question" not in payload_dict or not payload_dict.get("normalized_question"):
                payload_dict["normalized_question"] = raw_question
            if "dialect" not in payload_dict or not payload_dict.get("dialect"):
                payload_dict["dialect"] = replacements["dialect"]
            # Normalize entities to expected dict shape
            if "entities" not in payload_dict or payload_dict["entities"] is None:
                payload_dict["entities"] = {}
            else:
                payload_dict["entities"] = _normalize_entities(payload_dict["entities"])
            confidence = payload_dict.get("confidence")
            if isinstance(confidence, str):
                mapping = {
                    "low": 0.2,
                    "medium": 0.5,
                    "high": 0.8,
                    "very high": 0.95,
                }
                lower_conf = confidence.lower()
                payload_dict["confidence"] = mapping.get(lower_conf, mapping.get(lower_conf.split()[0], 0.5))
            elif confidence is None:
                payload_dict["confidence"] = 0.0
            payload_dict, sql_ok = ensure_string_sql(payload_dict)
            if not sql_ok:
                payload_dict["sql"] = ""
                payload_dict["needs_user_clarification"] = False
                assumptions = payload_dict.get("assumptions") or []
                assumptions.append("Не удалось автоматически сформировать SQL по исходному запросу.")
                payload_dict["assumptions"] = assumptions
            sql_text = payload_dict.get("sql")
            if not isinstance(sql_text, str) or not sql_text.strip():
                raise ValueError("SQL_EMPTY")
            plan = PlanOut.model_validate(payload_dict)

            sql_text = plan.sql or ""
            lowered_sql = sql_text.lower()
            lowered_question = raw_question.lower()
            if "выруч" in lowered_question and "crm_payments" not in lowered_sql:
                raise ValueError("SQL_CANONICAL_REVENUE")
            logger.info(
                "[Planner] Plan received with confidence %.3f (needs clarification=%s)",
                plan.confidence,
                plan.needs_user_clarification,
            )
            return plan
        except (ValueError, ValidationError) as exc:
            logger.warning("[Planner] Failed to parse plan output: %s", exc)
            last_error = PlanValidationError(content or "", exc)
            reminder = (
                "Ответ должен быть чистым JSON без текста до или после. Повтори попытку,"
                " соблюдая структуру."
            )
            if isinstance(exc, ValueError):
                if str(exc) == "SQL_EMPTY":
                    reminder = (
                        "SQL не может быть пустым. Сформируй исполнимый SELECT/CTE, даже если уверенность низкая."
                    )
                elif str(exc) == "SQL_CANONICAL_REVENUE":
                    reminder = (
                        "Для расчёта выручки используй таблицу crm_payments (поле amount) и формируй итоговый SELECT."
                    )
            messages.append({"role": "user", "content": reminder})

    if last_error is None:
        raise RuntimeError("Planner failed without error details")
    if isinstance(last_error, PlanValidationError):
        raise last_error
    raise RuntimeError(f"Planner call failed: {last_error}")


__all__ = ["plan_query"]
