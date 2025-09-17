"""Helpers for turning pipeline results into user-facing replies."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable


_RUBLE_RE = re.compile(r"\bруб(?:\.|лей|ля|л[ья]ми|)\b", re.IGNORECASE)


def _normalize_currency(text: str) -> str:
    if not text:
        return text
    return _RUBLE_RE.sub("₸", text.replace("RUB", "₸").replace("rub", "₸"))


def _format_followups(followups: Iterable[str]) -> str:
    hints = [f"• {q}" for q in followups if q]
    return "\n".join(hints)


def render_pipeline_reply(result: Dict[str, Any]) -> str:
    """Produce a concise assistant reply for a pipeline result."""

    generated = result.get("generated_response") or {}
    human = generated.get("human_readable_text")
    if isinstance(human, str) and human.strip():
        return _normalize_currency(human.strip())

    followups = result.get("followup_questions") or []
    if followups:
        hints = _format_followups(followups)
        if hints:
            return f"Нужно уточнение:\n{hints}"

    intent = result.get("intent") or ""
    entities = result.get("entities") or {}
    if intent or entities:
        parts = []
        if intent:
            parts.append(f"Намерение: {intent}")
        if entities:
            parts.append(f"Параметры: {entities}")
        if parts:
            return "\n".join(parts)

    return "Не удалось понять запрос. Попробуйте переформулировать."
