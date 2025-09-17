import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.agents.table_agent import TableSelectionAgent
from app.pipeline.context import PipelineContext

agent = TableSelectionAgent()

test_cases = {
    "frequent_clients": ["crm_clients", "crm_appointments"],
    "employee_productivity": ["crm_employees", "crm_appointments", "crm_appointment_services"],
    "missed_appointments": ["crm_appointments"],
    "payment_stats": ["crm_appointments", "crm_payments"],
    "appointment_duration": ["crm_appointment_services", "crm_appointments"],
    "unknown_intent": []  # should fallback or print warning
}

for intent, expected_tables in test_cases.items():
    print(f"\n🔎 Testing intent: {intent}")
    context = PipelineContext("dummy query")  # original query doesn't matter here
    context.intent = intent

    context = agent.run(context)

    if context.tables == expected_tables:
        print(f"✅ Correct tables: {context.tables}")
    else:
        print(f"❌ Wrong tables: {context.tables}, expected: {expected_tables}")
