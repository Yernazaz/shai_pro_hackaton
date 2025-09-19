from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from app.utils.logging_config import get_logger

logger = get_logger(__name__)

_RULES_FILE = Path(__file__).resolve().parents[2] / "data" / "telegram_rules.yaml"

_DEFAULT_RULES: Dict[str, Any] = {
    "stat_followups": {
        "top_employees_by_revenue": {
            "максим": "какой сотрудник принёс максимальный доход и какая это сумма?",
            "миним": "какой сотрудник показал минимальный доход и сколько это?",
        },
        "services_by_employee": {
            "максим": "у какого сотрудника самое большое количество оказанных услуг?",
            "миним": "у какого сотрудника самое маленькое количество оказанных услуг?",
        },
        "client_total_spending": {
            "максим": "какой клиент потратил больше всего и сколько именно?",
            "миним": "какой клиент потратил меньше всего и сколько именно?",
        },
    }
}

_rules_cache: Dict[str, Any] | None = None


def _load_rules(force_reload: bool = False) -> Dict[str, Any]:
    global _rules_cache

    if not force_reload and _rules_cache is not None:
        return _rules_cache

    if not _RULES_FILE.exists():
        logger.info("[TelegramRules] Config file not found at %s; using defaults", _RULES_FILE)
        _rules_cache = dict(_DEFAULT_RULES)
        return _rules_cache

    try:
        with _RULES_FILE.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            logger.warning("[TelegramRules] Invalid format in %s; using defaults", _RULES_FILE)
            _rules_cache = dict(_DEFAULT_RULES)
        else:
            merged = dict(_DEFAULT_RULES)
            if isinstance(data.get("stat_followups"), dict):
                merged["stat_followups"] = data["stat_followups"]
            _rules_cache = merged
            logger.info("[TelegramRules] Loaded config from %s", _RULES_FILE)
    except Exception:
        logger.exception("[TelegramRules] Failed to load %s; using defaults", _RULES_FILE)
        _rules_cache = dict(_DEFAULT_RULES)

    return _rules_cache


def get_stat_followups(force_reload: bool = False) -> Dict[str, Dict[str, str]]:
    rules = _load_rules(force_reload=force_reload)
    return rules.get("stat_followups", {})


__all__ = [
    "get_stat_followups",
]
