import os
os.environ["ALLOW_WRITES"] = "true"

from app.services.booking import book_from_entities

ok, msg = book_from_entities(
    "запиши меня на стрижку на 15 сентября 2025 номер 77472663980",
    "create_appointment",
    {
        "date_range": {"start": "2025-09-15", "end": "2025-09-15"},
        "service_type": "Стрижка",
        "employee_name": {"first_name": "Дана", "last_name": "Айтбаева"},
    },
)
print(ok)
print(msg)

