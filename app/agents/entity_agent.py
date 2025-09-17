import json
import os
import re
from app.registry.agent_registry import registry
from dateparser.search import search_dates
from app.services.service_matcher import load_services_from_db, match_service
from datetime import datetime, timedelta
from rapidfuzz import process
from scripts.limit_extraction import extract_limit
from scripts.employee_names import load_employee_names, reload_employee_names
import calendar
from app.utils.logging_config import get_logger
from app.utils.llm_client import chat_completion
from app.utils.openai_config import get_openai_model

logger = get_logger(__name__)

USE_LLM_FALLBACK = os.getenv("ENTITY_AGENT_USE_LLM", "1").lower() in ("1", "true", "yes")
DISABLE_OPENAI = os.getenv("DISABLE_OPENAI", "0").lower() in ("1", "true", "yes")

ENTITY_EXTRACTION_FUNCTION = {
    "name": "extract_entities",
    "description": (
        "Структурируй сущности из пользовательского запроса. "
        "Возвращай только поля, которые уверенно определены."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "date_range": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": "Дата начала в формате YYYY-MM-DD"},
                    "end": {"type": "string", "description": "Дата окончания в формате YYYY-MM-DD"},
                },
                "required": ["start", "end"],
                "additionalProperties": False,
            },
            "employee_name": {
                "type": "object",
                "properties": {
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                },
                "required": ["first_name", "last_name"],
                "additionalProperties": False,
            },
            "service_type": {"type": "string"},
            "client_name": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1},
            "time_of_day": {"type": "string", "description": "Время HH:MM"},
            "status": {"type": "string"},
            "metric": {"type": "string"},
        },
        "additionalProperties": False,
    },
}

RU_MONTHS = {
    "январь": 1, "январе": 1,
    "февраль": 2, "феврале": 2,
    "март": 3, "марте": 3,
    "апрель": 4, "апреле": 4,
    "май": 5, "мае": 5,
    "июнь": 6, "июне": 6,
    "июль": 7, "июле": 7,
    "август": 8, "августе": 8,
    "сентябрь": 9, "сентябре": 9,
    "октябрь": 10, "октябре": 10,
    "ноябрь": 11, "ноябре": 11,
    "декабрь": 12, "декабре": 12
}
RELATIVE_TIME_PATTERNS = {
    r"в прошлом месяце": lambda: EntityExtractionAgent._month_delta(-1),
    r"в этом месяце": lambda: EntityExtractionAgent._month_delta(0),
    r"на этой неделе": lambda: EntityExtractionAgent._week_delta(0),
    r"на прошлой неделе": lambda: EntityExtractionAgent._week_delta(-1),
    r"за\s+(\d+)\s+месяц": lambda match: EntityExtractionAgent._month_delta_range(int(match.group(1))),
    r"за\s+(\d+)\s+неделю": lambda match: EntityExtractionAgent._week_delta_range(int(match.group(1))),
    r"за\s+(\d+)\s+день": lambda match: {
        "start": (datetime.now() - timedelta(days=int(match.group(1)))).date(),
        "end": datetime.now().date()
    },
    r"с начала года": lambda: {
        "start": datetime(datetime.now().year, 1, 1).date(),
        "end": datetime.now().date()
    }
}

class EntityExtractionAgent:
    def run(self, context):
        text = context.cleaned_query
        context.entities = {}
        logger.info("[EntityExtraction] Query: %s", text)

        normalized_text = re.sub(r"\s+", " ", text.strip()).title()
        logger.info("[EntityExtraction] Normalized: %s", normalized_text)

        month_match = re.search(
            r"за\s+(январь|февраль|март|апрель|май|июнь|июль|август|сентябрь|октябрь|ноябрь|декабрь)\s+(\d{4})",
            text.lower()
        )
        if month_match:
            month_rus = month_match.group(1)
            year = int(month_match.group(2))
            month_num = RU_MONTHS.get(month_rus)
            if month_num:
                start = datetime(year, month_num, 1).date()
                end = datetime(year, month_num, calendar.monthrange(year, month_num)[1]).date()
                context.entities["date_range"] = {"start": start, "end": end}
                logger.info("[EntityExtraction] Detected from month-year regex: %s", context.entities["date_range"])

        if "date_range" not in context.entities:
            for pattern, resolver in RELATIVE_TIME_PATTERNS.items():
                for match in re.finditer(pattern, text):
                    try:
                        context.entities["date_range"] = resolver(match)
                    except TypeError:
                        context.entities["date_range"] = resolver()
                    logger.info("[EntityExtraction] Detected relative date: %s", context.entities["date_range"])
                    break
                if "date_range" in context.entities:
                    break

        if "date_range" not in context.entities:
            for month_rus, month_num in RU_MONTHS.items():
                if (
                    f"в {month_rus}" in text
                    or f"за {month_rus}" in text
                    or f"на {month_rus}" in text
                    or (re.search(rf"\b{re.escape(month_rus)}\b", text) is not None)
                ):
                    year = datetime.now().year
                    start = datetime(year, month_num, 1).date()
                    end = datetime(year, month_num, calendar.monthrange(year, month_num)[1]).date()
                    context.entities["date_range"] = {"start": start, "end": end}
                    logger.info("[EntityExtraction] Detected with fallback month map: %s", context.entities["date_range"])
                    break

        if "date_range" not in context.entities:
            date_entities = search_dates(text, languages=["ru"])
            if date_entities:
                parsed = [dt for (_, dt) in date_entities]
                context.entities["date_range"] = self._simplify_date_range(parsed)
                logger.info("[EntityExtraction] Detected with dateparser: %s", context.entities["date_range"])

        services_keywords = load_services_from_db()
        service_type = match_service(text, services_keywords)
        if service_type:
            context.entities["service_type"] = service_type
            logger.info("[EntityExtraction] Detected service_type: %s", service_type)

        time_match = re.search(
            r"(?:на|в)\s*(\d{1,2})(?:[:.](\d{2}))?\s*(?:час(?:а|ов)?|)?\s*(утра|вечера|дня|ночи)?",
            text.lower()
        )
        if time_match:
            hour = int(time_match.group(1))
            minute = time_match.group(2) or "00"
            period = (time_match.group(3) or "").strip()
            if period in ("вечера", "дня") and hour < 12:
                hour += 12
            elif period == "ночи" and hour == 12:
                hour = 0
            context.entities["time_of_day"] = f"{hour:02d}:{minute}"
            logger.info("[EntityExtraction] Detected time_of_day: %s", context.entities["time_of_day"])

        limit = extract_limit(text)
        if limit:
            context.entities["limit"] = limit
            logger.info("[EntityExtraction] Detected limit: %s", limit)

        clean_for_match = re.sub(r"[^\w\s]", "", text.lower())
        match = extract_employee_name_by_match(clean_for_match)
        if match:
            context.entities["employee_name"] = match
            logger.info("[EntityExtraction] Detected employee_name from fuzzy match: %s", match)

        existing_snapshot = dict(context.entities)

        if USE_LLM_FALLBACK and not DISABLE_OPENAI:
            try:
                enriched = self._llm_enrich_entities(context, existing_snapshot)
                if enriched:
                    for key, value in enriched.items():
                        if key not in context.entities and value is not None:
                            context.entities[key] = value
            except Exception:
                logger.exception("[EntityExtraction] LLM fallback failed")

        return context

    def _simplify_date_range(self, dates):
        if not dates:
            return None
        if len(dates) == 1:
            return {"start": dates[0].date(), "end": dates[0].date()}
        dates = sorted(dates)
        return {"start": dates[0].date(), "end": dates[-1].date()}

    @staticmethod
    def _month_delta(offset):
        today = datetime.now()
        year = today.year
        month = today.month + offset
        if month < 1:
            month += 12
            year -= 1
        elif month > 12:
            month -= 12
            year += 1
        start = datetime(year, month, 1).date()
        end = datetime(year, month, calendar.monthrange(year, month)[1]).date()
        return {"start": start, "end": end}
    
    @staticmethod
    def _week_delta(offset):
        today = datetime.now()
        start = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
        end = start + timedelta(days=6)
        return {"start": start.date(), "end": end.date()}
    
    @staticmethod
    def _month_delta_range(months_back: int):
        today = datetime.now()
        start_month = today.month - months_back + 1
        start_year = today.year
        while start_month <= 0:
            start_month += 12
            start_year -= 1
        start = datetime(start_year, start_month, 1).date()
        end = today.date()
        return {"start": start, "end": end}
    
    @staticmethod
    def _week_delta_range(weeks_back: int):
        today = datetime.now()
        start = today - timedelta(weeks=weeks_back)
        end = today
        return {"start": start.date(), "end": end.date()}

    def _llm_enrich_entities(self, context, existing: dict):
        query = context.original_query or context.cleaned_query
        if not query:
            return {}

        serialized_existing = json.dumps(existing, ensure_ascii=False, default=str)
        messages = [
            {
                "role": "system",
                "content": (
                    "Ты извлекаешь структурированные сущности из запроса на русском языке. "
                    "Возвращай значения только если уверен. Если сущность отсутствует — не добавляй поле."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Запрос пользователя: {query}\n"
                    f"Нормализованный текст: {context.cleaned_query}\n"
                    f"Уже найденные сущности: {serialized_existing}"
                ),
            },
        ]

        response = chat_completion(
            model=os.getenv("ENTITY_LLM_MODEL") or get_openai_model(),
            messages=messages,
            functions=[ENTITY_EXTRACTION_FUNCTION],
            function_call={"name": ENTITY_EXTRACTION_FUNCTION["name"]},
            temperature=0,
        )

        message = response["choices"][0]["message"] if isinstance(response, dict) else response.choices[0].message
        arguments = None
        if isinstance(message, dict):
            call = message.get("function_call") or {}
            arguments = call.get("arguments")
        else:
            if message.function_call:
                arguments = message.function_call.arguments

        if not arguments:
            return {}

        try:
            parsed = json.loads(arguments)
        except Exception:
            logger.exception("[EntityExtraction] Failed to parse LLM entities")
            return {}

        return self._postprocess_llm_entities(parsed)

    def _postprocess_llm_entities(self, payload: dict):
        result = {}

        def _parse_date(value: str | None):
            if not value:
                return None
            try:
                return datetime.fromisoformat(value).date()
            except Exception:
                return None

        date_range = payload.get("date_range")
        if isinstance(date_range, dict):
            start = _parse_date(date_range.get("start"))
            end = _parse_date(date_range.get("end"))
            if start and end:
                result["date_range"] = {"start": start, "end": end}

        employee = payload.get("employee_name")
        if isinstance(employee, dict):
            first = (employee.get("first_name") or "").strip()
            last = (employee.get("last_name") or "").strip()
            if first and last:
                result["employee_name"] = {"first_name": first, "last_name": last}

        service = payload.get("service_type")
        if isinstance(service, str) and service.strip():
            result["service_type"] = service.strip()

        client_name = payload.get("client_name")
        if isinstance(client_name, str) and client_name.strip():
            result["client_name"] = client_name.strip()

        limit = payload.get("limit")
        if isinstance(limit, int) and limit > 0:
            result["limit"] = limit

        time_of_day = payload.get("time_of_day")
        if isinstance(time_of_day, str) and time_of_day.strip():
            result["time_of_day"] = time_of_day.strip()

        status = payload.get("status")
        if isinstance(status, str) and status.strip():
            result["status"] = status.strip()

        metric = payload.get("metric")
        if isinstance(metric, str) and metric.strip():
            result["metric"] = metric.strip()

        return result
    
def extract_employee_name_by_match(query: str, threshold: int = 85):
    full_names = load_employee_names()
    full_names_lower = [name.lower() for name in full_names]

    match, score, index = process.extractOne(query.lower(), full_names_lower)
    if score >= threshold:
        matched_name = full_names[index]  # Use original casing
        if " " in matched_name:
            first, last = matched_name.split(" ", 1)
            return {"first_name": first, "last_name": last}
    # If miss, try to refresh employees (newly added) and match again
    full_names = reload_employee_names()
    if full_names:
        full_names_lower = [name.lower() for name in full_names]
        match, score, index = process.extractOne(query.lower(), full_names_lower)
        if score >= threshold and " " in full_names[index]:
            first, last = full_names[index].split(" ", 1)
            return {"first_name": first, "last_name": last}
    return None

registry.register("entity", EntityExtractionAgent())
