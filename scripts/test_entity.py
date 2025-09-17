import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.agents.entity_agent import EntityExtractionAgent
from app.pipeline.context import PipelineContext

agent = EntityExtractionAgent()

test_cases = {
    "Кто был самым активным сотрудником в марте?": ["date_range"],
    "Покажи топ 3 клиентов за февраль": ["limit", "date_range"],
    "Сколько клиентов пришло на стрижку в этом месяце?": ["service_type", "date_range"],
    "Какие услуги были самыми длинными на прошлой неделе?": ["date_range"],
    "Покажи продуктивность сотрудника Иванов в январе": ["employee_name", "date_range"],
    "Кто записывался на окрашивание на этой неделе?": ["service_type", "date_range"],
    "Сколько клиентов записались на массаж в прошлом месяце?": ["service_type", "date_range"]
}

for query, expected_keys in test_cases.items():
    print("Query:", query)
    context = PipelineContext(query)
    context.cleaned_query = query.lower()  # simulate preprocessing agent
    context = agent.run(context)

    for key in expected_keys:
        value = context.entities.get(key)
        if value:
            print(f"Found {key}: {value}")
        else:
            print(f"Missing {key}")
    print("Extracted entities:", context.entities)
    print("---")
