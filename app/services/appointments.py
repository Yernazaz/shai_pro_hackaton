import re
from typing import Optional, Tuple, List

from app.services.execute_sql_query import execute_sql_query


def _name_variants(token: str) -> List[str]:
    t = (token or "").strip().lower()
    if not t:
        return []
    vars = {t}
    if len(t) > 4 and t[-1] in "аяуыюыеоиь":
        vars.add(t[:-1])
    if len(t) > 5 and t[-2:] in ("ой", "ей", "ий", "ый", "ая", "яя", "ою", "ею", "ою", "ою", "ом", "ем"):
        vars.add(t[:-2])
    return list(vars)


def _split_capitalized(text: str) -> Tuple[Optional[str], Optional[str]]:
    if not text:
        return None, None
    m = re.search(r"([А-ЯA-ZЁ][а-яa-zё\-]+)\s+([А-ЯA-ZЁ][а-яa-zё\-]+)", text)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _find_user_by_name(first: Optional[str], last: Optional[str], role: str) -> Optional[int]:
    if not (first and last):
        return None
    fvars = _name_variants(first)
    lvars = _name_variants(last)
    table = "crm_employees" if role == "employee" else "crm_clients"
    id_field = "employee_id" if role == "employee" else "client_id"
    rows, _ = execute_sql_query(
        f"""
        SELECT t.id AS {id_field}
        FROM {table} t
        JOIN crm_people p ON p.id = t.person_id
        WHERE lower(p.first_name) = lower(%s)
          AND lower(p.last_name) = lower(%s)
        LIMIT 1
        """,
        [first.title(), last.title()],
    )
    if rows:
        return rows[0][id_field]

    # Fuzzy via LIKE variants
    for fv in fvars:
        for lv in lvars:
            rows, _ = execute_sql_query(
                f"""
                SELECT t.id AS {id_field}
                FROM {table} t
                JOIN crm_people p ON p.id = t.person_id
                WHERE lower(p.first_name) LIKE %s
                  AND lower(p.last_name) LIKE %s
                LIMIT 1
                """,
                [f"%{fv}%", f"%{lv}%"],
            )
            if rows:
                return rows[0][id_field]
    return None


def delete_appointments(
    appointment_ids: Optional[List[int]] = None,
    employee_first_last: Optional[Tuple[str, str]] = None,
    client_first_last: Optional[Tuple[str, str]] = None,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
) -> int:
    """Delete appointments matching filters (hard delete). Returns count removed."""
    clauses = ["1=1"]
    params: List = []

    if appointment_ids:
        ids_list = ",".join(str(int(i)) for i in appointment_ids if isinstance(i, int))
        clauses.append(f"id IN ({ids_list})")

    if date_start and date_end:
        clauses.append("scheduled_start::date BETWEEN %s AND %s")
        params.extend([date_start, date_end])

    if employee_first_last:
        emp_id = _find_user_by_name(employee_first_last[0], employee_first_last[1], role="employee")
        if emp_id:
            clauses.append(
                "(primary_employee_id = %s OR id IN (SELECT appointment_id FROM crm_appointment_services WHERE employee_id=%s))"
            )
            params.extend([emp_id, emp_id])

    if client_first_last:
        cl_id = _find_user_by_name(client_first_last[0], client_first_last[1], role="client")
        if cl_id:
            clauses.append("client_id = %s")
            params.append(cl_id)

    if len(clauses) == 1:
        # No filters provided
        return 0

    where = " AND ".join(clauses)
    sql = f"DELETE FROM crm_appointments WHERE {where} RETURNING id"
    rows, _ = execute_sql_query(sql, params)
    return len(rows or [])
