import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.agents.intent_embedder import retrieve_intent

test_queries = {
    "Покажи клиентов, которые приходят чаще всего": "frequent_clients",
    "Кто наши самые постоянные клиенты?": "frequent_clients",
    "Сколько клиентов обслужил каждый сотрудник в апреле?": "employee_productivity",
    "Кто из сотрудников был самым занятым?": "employee_productivity",
    "Сколько записей было пропущено в марте?": "missed_appointments",
    "Покажи все отмененные или неявки на прием": "missed_appointments",
    "Сколько денег мы заработали за февраль?": "payment_stats",
    "Как распределяется оплата по клиентам?": "payment_stats",
    "Насколько длинными были записи в прошлом месяце?": "appointment_duration",
    "Как долго длятся наши приемы в среднем?": "appointment_duration",
}

for query, expected in test_queries.items():
    intent, score = retrieve_intent(query)
    print(f"Query: {query}")
    print(f"   ➤ Predicted: {intent} (score: {score:.2f}) | Expected: {expected}")
    print("   Match" if intent == expected else "   Mismatch")
    print("---")
