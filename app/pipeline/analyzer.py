from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from pydantic import ValidationError

from app.config.settings import get_settings
from app.contracts.analysis import AnalysisOut, AnalysisValidationError
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


def _extract_json_block(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Response does not contain JSON object")
    return text[start : end + 1]


def _normalize_text(value: Any) -> str:
    return str(value).strip("\n \'\"")


def analyze_results(
    normalized_question: str,
    sql: str,
    rows: list[dict[str, Any]],
    context: Dict[str, Any],
) -> AnalysisOut:
    settings = get_settings()
    prompt = _load_prompt("analysis_v1.txt")
    rows_preview = json.dumps(rows, ensure_ascii=False, default=str)
    contextual_notes = context.get("contextual_notes", "")

    system_prompt = prompt
    user_payload = (
        "Вопрос: "
        f"{normalized_question}\n\n"
        f"SQL: {sql}\n\n"
        f"Результаты: {rows_preview}\n\n"
        f"Контекст: {contextual_notes or '-'}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                "Верни JSON по схеме AnalysisOut без какого-либо текста до или после.\n" + user_payload
            ),
        },
    ]

    last_error: Exception | None = None

    for attempt in range(3):
        logger.info("[Analyzer] Calling LLM for analysis (attempt %s)", attempt + 1)
        response = chat_completion(
            model=settings.llm_analysis_model,
            messages=messages,
            temperature=settings.llm_temperature,
        )

        if isinstance(response, dict):
            message = response["choices"][0]["message"]
            content = message.get("content", "")
        else:
            message = response.choices[0].message
            content = getattr(message, "content", "")

        try:
            json_payload = _extract_json_block(content or "")
            payload = json.loads(json_payload)

            if not payload.get("final_answer"):
                for key in ("answer_ru", "answer", "result", "summary"):
                    value = payload.get(key)
                    if value:
                        payload["final_answer"] = value
                        break
                else:
                    payload["final_answer"] = ""

            final_answer = payload.get("final_answer")
            if isinstance(final_answer, list):
                lines: list[str] = []
                for idx, entry in enumerate(final_answer, start=1):
                    if isinstance(entry, dict):
                        parts = [
                            f"{_normalize_text(k)}: {_normalize_text(v)}"
                            for k, v in entry.items()
                        ]
                        lines.append(f"{idx}. " + ", ".join(parts))
                    else:
                        lines.append(f"{idx}. {_normalize_text(entry)}")
                payload["final_answer"] = "\n".join(lines)
            elif isinstance(final_answer, dict):
                parts = [
                    f"{_normalize_text(k)}: {_normalize_text(v)}"
                    for k, v in final_answer.items()
                ]
                payload["final_answer"] = "\n".join(parts)
            else:
                payload["final_answer"] = _normalize_text(final_answer)

            if "explanations" not in payload:
                for key in ("details", "explanation", "notes"):
                    if key in payload and isinstance(payload[key], list):
                        payload["explanations"] = payload[key]
                        break
            explanations = payload.get("explanations")
            if isinstance(explanations, str):
                payload["explanations"] = [_normalize_text(explanations)]
            elif isinstance(explanations, dict):
                payload["explanations"] = [
                    f"{_normalize_text(k)}: {_normalize_text(v)}"
                    for k, v in explanations.items()
                ]

            if "suggested_followup" not in payload:
                hint = payload.get("next_questions") or payload.get("followups")
                if hint:
                    payload["suggested_followup"] = hint
            followups = payload.get("suggested_followup")
            if isinstance(followups, str):
                payload["suggested_followup"] = [_normalize_text(followups)]
            elif isinstance(followups, list):
                payload["suggested_followup"] = [
                    _normalize_text(item) for item in followups
                ]

            analysis = AnalysisOut.model_validate(payload)
            logger.info(
                "[Analyzer] Analysis prepared (needs_iteration=%s)",
                analysis.needs_iteration,
            )
            return analysis
        except (ValueError, ValidationError) as exc:
            logger.warning("[Analyzer] Failed to parse analysis output: %s", exc)
            last_error = AnalysisValidationError(content or "", exc)
            messages.append(
                {
                    "role": "user",
                    "content": "Ответ должен быть чистым JSON. Повтори попытку в точном формате.",
                }
            )

    assert last_error is not None
    raise last_error


__all__ = ["analyze_results"]
