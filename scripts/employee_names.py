import os
import sys

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.services.execute_sql_query import execute_sql_query

_cached_employees = []

def load_employee_names():
    global _cached_employees
    if _cached_employees:
        return _cached_employees  # Already loaded

    query = """
        SELECT p.first_name, p.last_name
        FROM crm_employees e
        JOIN crm_people p ON p.id = e.person_id
        WHERE e.is_active = TRUE;
    """
    result, _ = execute_sql_query(query)
    _cached_employees = [f"{r['first_name']} {r['last_name']}".strip() for r in result]
    return _cached_employees

def reload_employee_names():
    """Force refresh of cached employee names from DB."""
    global _cached_employees
    _cached_employees = []
    return load_employee_names()

if __name__ == "__main__":
    print("Running employee names loader...")
    employees = load_employee_names()
    if employees:
        print(f"Loaded employee names: {employees}")
    else:
        print("No employee names found.")
