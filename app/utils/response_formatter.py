"""Helpers for turning controller envelopes into user-facing replies."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable

from app.contracts.envelope import ControllerEnvelope

_RUBLE_RE = re.compile(r"\bруб(?:\.|лей|ля|л[ья]ми|)\b", re.IGNORECASE)


def _normalize_currency(text: str) -> str:
    if not text:
        return text
    return _RUBLE_RE.sub("₸", text.replace("RUB", "₸").replace("rub", "₸"))


def _format_followups(followups: Iterable[str]) -> str:
    hints = [f"• {q}" for q in followups if q]
    return "\n".join(hints)


def render_pipeline_reply(result: ControllerEnvelope | Dict[str, Any]) -> str:
    if isinstance(result, dict):
        envelope = ControllerEnvelope(**result)
    else:
        envelope = result

    answer = _normalize_currency(envelope.analysis_text.strip()) if envelope.analysis_text else ""
    followups = [hint for hint in envelope.suggested_followup if hint]
    if followups:
        hints = _format_followups(followups)
        if answer:
            return f"{answer}\n\nРекомендации:\n{hints}"
        return f"Нужно уточнение:\n{hints}"
    if answer:
        return answer
    return "Не удалось сформировать ответ. Попробуйте переформулировать запрос."
