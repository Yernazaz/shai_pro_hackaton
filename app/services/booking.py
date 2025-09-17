import os
from datetime import datetime, timedelta, time as dtime
from typing import Optional, Tuple

from app.services.execute_sql_query import execute_sql_query


def _get_or_create_client(first_name: str, last_name: str, phone: Optional[str]) -> int:
    q = """
        SELECT c.id AS client_id, p.id AS person_id, p.phone_number
        FROM crm_clients c
        JOIN crm_people p ON p.id = c.person_id
        WHERE lower(p.first_name) = lower(%s)
          AND lower(p.last_name) = lower(%s)
        LIMIT 1
    """
    rows, _ = execute_sql_query(q, [first_name, last_name])
    if rows:
        person_id = rows[0]["person_id"]
        if phone and (rows[0].get("phone_number") or "") != phone:
            execute_sql_query("UPDATE crm_people SET phone_number=%s WHERE id=%s", [phone, person_id])
        return rows[0]["client_id"]

    person_rows, _ = execute_sql_query(
        "INSERT INTO crm_people(first_name,last_name,phone_number) VALUES(%s,%s,%s) RETURNING id",
        [first_name, last_name, phone],
    )
    person_id = person_rows[0]["id"]
    client_rows, _ = execute_sql_query(
        "INSERT INTO crm_clients(person_id, loyalty_level, referred_by) VALUES(%s,'standard','bot') RETURNING id",
        [person_id],
    )
    return client_rows[0]["id"]


def _find_employee(full_name: Optional[dict]) -> Optional[int]:
    if not full_name:
        return None
    first = full_name.get("first_name")
    last = full_name.get("last_name")
    if not first or not last:
        return None
    q = """
        SELECT e.id
        FROM crm_employees e
        JOIN crm_people p ON p.id = e.person_id
        WHERE lower(p.first_name) = lower(%s)
          AND lower(p.last_name) = lower(%s)
        LIMIT 1
    """
    rows, _ = execute_sql_query(q, [first, last])
    return rows[0]["id"] if rows else None


def _find_service(service_name: Optional[str]) -> Optional[dict]:
    if not service_name:
        return None
    rows, _ = execute_sql_query(
        "SELECT id, base_price, duration_minutes FROM crm_services WHERE name=%s LIMIT 1",
        [service_name],
    )
    return rows[0] if rows else None


def _parse_date_time(entities: dict) -> Tuple[datetime, datetime]:
    # Expect a date_range with 'start' (date) at minimum; default time to 10:00-11:00
    start_raw = entities.get("date_range", {}).get("start")
    if isinstance(start_raw, str):
        base_date = datetime.fromisoformat(start_raw).date()
    elif hasattr(start_raw, "isoformat"):
        base_date = start_raw.date() if isinstance(start_raw, datetime) else start_raw
    else:
        base_date = datetime.now().date()

    time_hint = entities.get("time_of_day") or "10:00"
    try:
        hour, minute = [int(part) for part in time_hint.split(":", 1)]
    except Exception:
        hour, minute = 10, 0

    dt_start = datetime.combine(base_date, dtime(hour=hour, minute=minute))
    dt_end = dt_start + timedelta(hours=1)
    return dt_start, dt_end


def list_missing_booking_fields(text: str, entities: dict) -> list[str]:
    """Return a list of missing fields required to create an appointment."""
    missing: list[str] = []
    # date is required
    if not entities.get("date_range") or not entities.get("date_range", {}).get("start"):
        missing.append("дата")
    # service is very useful (optional technically, but we ask for it)
    if not entities.get("service_type"):
        missing.append("услуга")
    # client name
    import re
    name_match = re.search(r"([А-ЯA-ZЁ][а-яa-zё]+)\s+([А-ЯA-ZЁ][а-яa-zё]+)", text)
    if not name_match:
        missing.append("имя и фамилия клиента")
    # phone
    phone_match = re.search(r"(\+?7\d{10}|8\d{10}|\d{11})", text)
    if not phone_match:
        missing.append("номер телефона")
    # employee (optional)
    if not entities.get("employee_name"):
        # Do not require, but suggest
        missing.append("сотрудник (по желанию)")
    return missing


def book_from_entities(cleaned_query: str, intent: str, entities: dict) -> Tuple[bool, str]:
    """Create an appointment using extracted entities. Returns (ok, message)."""
    if intent != "create_appointment":
        return False, "Неверный тип запроса для бронирования."

    # Extract client name and phone from text (simple heuristic)
    # Expect user provides phone as digits in text
    import re
    m = re.search(r"(\+?7\d{10}|8\d{10}|\d{11})", cleaned_query)
    phone = m.group(1) if m else None

    # Use entities if they include an employee
    employee = entities.get("employee_name")
    service_name = entities.get("service_type")

    # Try to parse a client full name from text if it's in "Имя Фамилия" format before a phone
    # Otherwise fall back to a generic name
    name_match = re.search(r"([А-ЯA-ZЁ][а-яa-zё]+)\s+([А-ЯA-ZЁ][а-яa-zё]+)", cleaned_query)
    first_name = name_match.group(1) if name_match else "Гость"
    last_name = name_match.group(2) if name_match else ""

    client_id = _get_or_create_client(first_name, last_name, phone)
    employee_id = _find_employee(employee)
    service_row = _find_service(service_name)
    service_id = service_row.get("id") if service_row else None
    service_price = service_row.get("base_price") if service_row else 0
    service_duration = service_row.get("duration_minutes") if service_row else 60

    start_dt, end_dt = _parse_date_time(entities)

    # Insert appointment in scheduled status
    ins_apt = (
        """
        INSERT INTO crm_appointments(
            client_id, primary_employee_id, scheduled_start, scheduled_end,
            status, total_price, paid_amount, payment_status, notes
        )
        VALUES(%s, %s, %s, %s, 'scheduled', %s, 0, 'unpaid', %s)
        RETURNING id
        """
    )
    rows, _ = execute_sql_query(
        ins_apt,
        [client_id, employee_id, start_dt, end_dt, service_price or 0, "Создано ботом"],
    )
    appointment_id = rows[0]["id"]

    # Optionally add service line with employee
    if service_id and employee_id:
        execute_sql_query(
            """
            INSERT INTO crm_appointment_services(appointment_id, service_id, employee_id, price, duration_minutes, comment)
            VALUES(%s,%s,%s,%s,%s,%s)
            """,
            [appointment_id, service_id, employee_id, service_price or 0, service_duration, "Добавлено ботом"],
        )
        if service_price:
            execute_sql_query(
                "UPDATE crm_appointments SET total_price=%s WHERE id=%s",
                [service_price, appointment_id],
            )

    elif service_id:
        # Service without assigned employee
        execute_sql_query(
            """
            INSERT INTO crm_appointment_services(appointment_id, service_id, price, duration_minutes, comment)
            VALUES(%s,%s,%s,%s,%s)
            """,
            [appointment_id, service_id, service_price or 0, service_duration, "Добавлено ботом"],
        )
        if service_price:
            execute_sql_query(
                "UPDATE crm_appointments SET total_price=%s WHERE id=%s",
                [service_price, appointment_id],
            )

    msg = (
        f"Запись создана на {start_dt.date()} {start_dt.time().strftime('%H:%M')}\n"
        f"Клиент: {first_name} {last_name or ''}\n"
        f"Телефон: {phone or '—'}\n"
        f"Услуга: {service_name or '—'}\n"
        f"Сотрудник: {(employee.get('first_name') + ' ' + employee.get('last_name')) if employee else '—'}"
    ).strip()
    return True, msg
