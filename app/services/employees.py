from typing import Optional, Tuple
import re

from app.services.execute_sql_query import execute_sql_query


def _split_name(full_name: str) -> Tuple[Optional[str], Optional[str]]:
    parts = re.split(r"\s+", full_name.strip())
    # Drop helper words
    parts = [p for p in parts if p.lower() not in ("имя", "фамилия", "номер", "телефон", "сотрудник", "мастер")]
    if len(parts) >= 2:
        return parts[0].strip().title(), " ".join(parts[1:]).strip().title()
    return None, None


def extract_name_from_text(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Try to robustly extract first and last name from free text.
    Supports patterns like:
    - "Имя Алишер Фамилия Нурки"
    - "добавь сотрудника Алишер Нурки номер +7..."
    - generic two capitalized tokens
    """
    if not text:
        return None, None
    # 1) Explicit labels
    m1 = re.search(r"имя\s*[:\-]?\s+([A-Za-zА-Яа-яЁё\-]+)", text, re.I)
    m2 = re.search(r"фамили[яю]\s*[:\-]?\s+([A-Za-zА-Яа-яЁё\-]+)", text, re.I)
    if m1 and m2:
        return m1.group(1).title(), m2.group(1).title()

    # 2) After the word 'сотрудника' / 'сотрудник'
    m3 = re.search(r"сотрудник[а]?\s+([A-Za-zА-Яа-яЁё\-]+)\s+([A-Za-zА-Яа-яЁё\-]+)", text, re.I)
    if m3:
        return m3.group(1).title(), m3.group(2).title()

    # 3) First two capitalized tokens
    m4 = re.search(r"([А-ЯA-ZЁ][а-яa-zё\-]+)\s+([А-ЯA-ZЁ][а-яa-zё\-]+)", text)
    if m4:
        # ignore if first token is a label word
        first = m4.group(1)
        last = m4.group(2)
        if first.lower() in ("имя", "фамилия", "номер", "телефон"):
            # try to find next pair
            rest = text[m4.end():]
            m5 = re.search(r"([А-ЯA-ZЁ][а-яa-zё\-]+)\s+([А-ЯA-ZЁ][а-яa-zё\-]+)", rest)
            if m5:
                return m5.group(1).title(), m5.group(2).title()
        return first.title(), last.title()
    return None, None


def extract_phone(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"(\+?7\s*\d[\s\d]{9,}|8\s*\d[\s\d]{9,}|\+?7\d{10}|8\d{10}|\+\d{9,})", text)
    if not m:
        return None
    return re.sub(r"\s+", "", m.group(0))


def add_employee(full_name: Optional[str], phone: Optional[str], original_text: Optional[str] = None) -> Tuple[bool, str]:
    # Allow passing only original text
    first = last = None
    if full_name:
        first, last = _split_name(full_name)
    if not (first and last) and original_text:
        first, last = extract_name_from_text(original_text)
    if not first or not last:
        return False, "Укажите имя и фамилию сотрудника."

    # If exists, just update phone if provided
    rows, _ = execute_sql_query(
        """
        SELECT e.id AS employee_id, p.id AS person_id, p.phone_number
        FROM crm_employees e
        JOIN crm_people p ON p.id = e.person_id
        WHERE lower(p.first_name) = lower(%s)
          AND lower(p.last_name) = lower(%s)
        LIMIT 1
        """,
        [first, last],
    )
    if rows:
        emp = rows[0]
        if phone and (emp.get("phone_number") or "") != phone:
            execute_sql_query(
                "UPDATE crm_people SET phone_number=%s WHERE id=%s",
                [phone, emp["person_id"]],
            )
        # ensure employee marked active
        execute_sql_query("UPDATE crm_employees SET is_active=TRUE WHERE id=%s", [emp["employee_id"]])
        return True, f"Сотрудник {first} {last} уже существует. Данные обновлены."

    # Insert new person entry
    person_rows, _ = execute_sql_query(
        "INSERT INTO crm_people(first_name,last_name,phone_number) VALUES(%s,%s,%s) RETURNING id",
        [first, last, phone],
    )
    person_id = person_rows[0]["id"]

    # Create employee profile with default position
    execute_sql_query(
        """
        INSERT INTO crm_employees(person_id, position, hire_date, is_active)
        VALUES(%s,'Сотрудник салона', CURRENT_DATE, TRUE)
        """,
        [person_id],
    )
    return True, f"Сотрудник {first} {last} добавлен"


def delete_employee(full_name: Optional[str], original_text: Optional[str] = None) -> Tuple[bool, str]:
    first = last = None
    if full_name:
        first, last = _split_name(full_name)
    if not (first and last) and original_text:
        first, last = extract_name_from_text(original_text)
    if not first or not last:
        return False, "Укажите имя и фамилию сотрудника для удаления."

    rows, _ = execute_sql_query(
        """
        SELECT e.id AS employee_id, p.id AS person_id
        FROM crm_employees e
        JOIN crm_people p ON p.id = e.person_id
        WHERE lower(p.first_name) = lower(%s)
          AND lower(p.last_name) = lower(%s)
        LIMIT 1
        """,
        [first, last],
    )
    if not rows:
        return False, f"Сотрудник {first} {last} не найден"

    person_id = rows[0]["person_id"]
    # Deactivate employee first (for history), then remove person profile (cascade removes employee)
    execute_sql_query("UPDATE crm_employees SET is_active=FALSE WHERE person_id=%s", [person_id])
    execute_sql_query("DELETE FROM crm_people WHERE id=%s", [person_id])
    return True, f"Сотрудник {first} {last} удален"
