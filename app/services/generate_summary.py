import json
import os
from typing import Any, List

from app.utils.gemini_config import get_gemini_model
from app.utils.llm_client import chat_completion


def _serialize_rows(rows: List[Any]) -> str:
    try:
        return json.dumps(rows, ensure_ascii=False, default=str)
    except Exception:
        return str(rows)


def generate_summary_from_result(intent: str, result: list, original_query: str | None = None) -> str:
    if not result:
        return "По вашему запросу нет данных."

    trimmed_result = result[:10]
    serialized_rows = _serialize_rows(trimmed_result)

    intent_context_map = {
        "average_spending": "Покажи, сколько клиенты тратят в среднем. Упомяни сумму, округли до целого числа.",
        "most_expensive_service": "Определи, какая услуга у клиента была самой дорогой. Назови услугу и сумму.",
        "most_frequent_service": "Назови самую популярную услугу. Укажи количество раз, которое её заказывали.",
        "client_service_preference": "Покажи, какие услуги чаще всего выбирает каждый клиент. Назови клиента и услугу.",
        "most_frequent_period": "Покажи, в какие дни месяца чаще всего приходят клиенты. Назови дни и количество визитов.",
        "frequent_clients": "Определи самых частых клиентов. Назови имена и количество визитов.",
        "list_employees": "Перечисли сотрудников и, если есть, их номера телефонов.",
        "list_clients": "Перечисли клиентов и, если есть, их номера телефонов.",
        "appointment_stats": "Опиши статистику записей. Упомяни дату, количество и сумму.",
        "client_count": "Сколько клиентов всего (уникальных). Если результат одно число — просто назови его.",
        "employee_productivity": "Сравни продуктивность сотрудников. Укажи имя и количество приемов.",
        "missed_appointments": "Опиши пропущенные записи. Укажи количество и даты.",
        "payment_stats": "Покажи информацию о выручке. Упомяни суммы и даты.",
        "appointment_duration": "Покажи среднюю длительность записей. Укажи время и услуги."
    }

    context_instruction = intent_context_map.get(
        intent,
        "Сформулируй краткое описание результата для пользователя. Упомяни ключевые числа, даты или имена."
    )

    messages = [
        {
            "role": "system",
            "content": (
                "Ты помощник, который пишет краткие ответы на русском языке "
                "на основе результатов SQL-запросов. Используй имена, даты и количество записей. "
                "Не объясняй SQL. Не упоминай таблицы. Не придумывай данные, которых нет в таблице."
            )
        },
        {
            "role": "user",
            "content": (
                (f"Исходный вопрос: {original_query}\n" if original_query else "")
                + f"Вот результат SQL-запроса для намерения '{intent}':\n"
                + f"{serialized_rows}\n\n"
                + f"{context_instruction}\n"
                + "Если в результатах нет отменённых записей — не пиши про них."
            )
        }
    ]

    try:
        response = chat_completion(
            model=get_gemini_model(),
            messages=messages,
            temperature=0.4,
        )
        msg = response["choices"][0]["message"] if isinstance(response, dict) else response.choices[0].message
        content = msg.get("content") if isinstance(msg, dict) else msg.content
        return (content or "").strip()
    except Exception as e:
        return f"Не удалось сгенерировать объяснение: {str(e)}"
