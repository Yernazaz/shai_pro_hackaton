"""Heuristics to rewrite follow-up queries using conversational context."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, Iterable, List, Optional

SCOPE_KEYWORDS = {
    "clients": ("клиент", "клиентов", "клиентам", "client"),
    "employees": ("сотрудник", "сотрудников", "мастер", "employee"),
    "services": ("услуг", "услуга", "service"),
    "appointments": ("запис", "визит", "appointment"),
}


def _infer_scope_from_messages(messages: Iterable[Dict[str, str]]) -> Optional[str]:
    for msg in reversed(list(messages) if messages else []):
        text = (msg.get("content") or "").lower()
        for scope, keywords in SCOPE_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                return scope
    return None


BOOKING_PATTERN = re.compile(
    r"Запись создана на (?P<datetime>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}).*?"\
    r"Клиент: (?P<client>.+?)\s+Телефон: (?P<phone>[+\d]+).*?"\
    r"Услуга: (?P<service>.+?)(?:\s|$)",
    re.S
)


def _last_user_query(chat_context: Optional[List[Dict[str, str]]]) -> Optional[str]:
    if not chat_context:
        return None
    for message in reversed(chat_context):
        if message.get("role") == "user":
            return message.get("content")
    return None


def _needs_booking_completion(chat_context: Optional[List[Dict[str, str]]]) -> bool:
    if not chat_context:
        return False
    for message in reversed(chat_context):
        if message.get("role") != "assistant":
            continue
        text = (message.get("content") or "").lower()
        if "чтобы создать запись" in text:
            return True
        break
    return False


def _rewrite_pronouns(query: str, scope: Optional[str]) -> Optional[str]:
    low = query.lower()
    if scope and re.search(r"\bих\b", low):
        if "телефон" in low or "номер" in low:
            if scope == "clients":
                return "перечисли номера телефонов клиентов"
            if scope == "employees":
                return "перечисли номера телефонов сотрудников"
        if "имена" in low or "имя" in low:
            if scope == "clients":
                return "перечисли имена всех клиентов"
            if scope == "employees":
                return "перечисли имена всех сотрудников"
        if scope == "clients":
            return "перечисли всех клиентов"
        if scope == "employees":
            return "перечисли всех сотрудников"
        if scope == "services":
            return "перечисли все услуги"
    return None


def _rewrite_like_previous(query: str, last_query: Optional[str]) -> Optional[str]:
    low = query.lower()
    if "точно так же" not in low and "так же" not in low:
        return None
    match = re.search(r"с\s+(.+)", query, flags=re.IGNORECASE)
    if not match:
        return None
    service = match.group(1).strip().strip('.!?')
    if not service:
        return None
    base = "перечисли клиентов, которые записывались на услугу {service}, с датами визитов, суммой и телефонами"
    return base.format(service=service)


def _extract_last_booking(chat_context: Optional[List[Dict[str, str]]]) -> Optional[Dict[str, str]]:
    if not chat_context:
        return None
    for message in reversed(chat_context):
        if message.get("role") != "assistant":
            continue
        text = message.get("content") or ""
        match = BOOKING_PATTERN.search(text)
        if match:
            info = match.groupdict()
            try:
                dt = datetime.strptime(info["datetime"], "%Y-%m-%d %H:%M")
            except Exception:
                dt = None
            return {
                "datetime": info.get("datetime"),
                "client": info.get("client", "").strip(),
                "phone": info.get("phone", "").strip(),
                "service": info.get("service", "").strip(),
                "date": dt.date().isoformat() if dt else info.get("datetime", "").split()[0],
            }
    return None


def _extract_time_from_query(query: str) -> Optional[str]:
    low = query.lower()
    match = re.search(
        r"(?:на|в)\s*(\d{1,2})(?:[:.](\d{2}))?\s*(?:час(?:а|ов)?|)?\s*(утра|вечера|дня|ночи)?",
        low
    )
    if not match:
        return None
    hour = int(match.group(1))
    minute = (match.group(2) or "00").ljust(2, "0")
    period = match.group(3) or ""
    period = period.strip()
    if period in ("вечера", "дня") and hour < 12:
        hour += 12
    elif period == "ночи" and hour < 6:
        hour += 24 if hour < 4 else 0
    if hour >= 24:
        hour %= 24
    return f"{hour:02d}:{minute}"


def _extract_last_client_list(chat_context: Optional[List[Dict[str, str]]]) -> list[str]:
    if not chat_context:
        return []
    for message in reversed(chat_context):
        if message.get("role") != "assistant":
            continue
        text = message.get("content") or ""
        if "список клиентов" not in text.lower():
            continue
        names = []
        for line in text.splitlines():
            m = re.search(r"\d+\.\s+([^,]+)", line)
            if m:
                names.append(m.group(1).strip())
        if names:
            return names
    return []


def _rewrite_clients_subset(query: str, chat_context: Optional[List[Dict[str, str]]]) -> Optional[str]:
    low = query.lower()
    if "клиент" not in low:
        return None
    if "перв" not in low:
        return None
    names = _extract_last_client_list(chat_context)
    if len(names) < 1:
        return None
    count_match = re.search(r"первые?\s*(\d+)", low)
    if count_match:
        try:
            subset = int(count_match.group(1))
        except Exception:
            subset = 5
    else:
        subset = min(5, len(names))
    subset = max(1, min(subset, len(names)))
    selected = names[:subset]
    joined = ", ".join(selected)
    return f"какими услугами пользовались клиенты {joined}?"


def _rewrite_reschedule(
    query: str,
    chat_context: Optional[List[Dict[str, str]]],
) -> Optional[str]:
    low = query.lower()
    if not any(word in low for word in ("измен", "перенес", "перестав", "перезапиши")):
        return None
    new_time = _extract_time_from_query(query)
    if not new_time:
        return None
    booking = _extract_last_booking(chat_context)
    if not booking:
        return None
    client = booking.get("client")
    phone = booking.get("phone")
    service = booking.get("service")
    date = booking.get("date")
    if not all([client, service, date]):
        return None
    phone_part = f" телефон {phone}" if phone else ""
    return (
        f"запиши клиента {client} на услугу {service} {date} в {new_time}{phone_part}"
    )


def rewrite_query_with_context(
    original_query: str,
    chat_context: Optional[List[Dict[str, str]]] = None,
    *,
    last_scope: Optional[str] = None,
    last_query: Optional[str] = None,
) -> str:
    """Rewrite pronoun-heavy follow-ups into explicit queries."""

    scope = last_scope or _infer_scope_from_messages(chat_context or [])

    base_query = last_query or _last_user_query(chat_context)
    combined_query = original_query
    if _needs_booking_completion(chat_context) and base_query:
        combined_query = f"{base_query} {original_query}".strip()
        base_query = combined_query

    subset_rewrite = _rewrite_clients_subset(combined_query, chat_context)
    if subset_rewrite:
        return subset_rewrite

    pronoun_rewrite = _rewrite_pronouns(combined_query, scope)
    if pronoun_rewrite:
        return pronoun_rewrite

    same_as_before = _rewrite_like_previous(combined_query, base_query)
    if same_as_before:
        return same_as_before

    reschedule = _rewrite_reschedule(combined_query, chat_context)
    if reschedule:
        return reschedule

    return combined_query
