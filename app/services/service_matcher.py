import re
from app.services.execute_sql_query import execute_sql_query

_cached_services = {}

def load_services_from_db():
    global _cached_services
    if _cached_services:
        return _cached_services

    query = "SELECT id, name FROM crm_services;"
    result, _ = execute_sql_query(query)

    service_map = {}
    for row in result:
        name = row["name"].strip()
        keywords = generate_keywords(name)
        service_map[name] = keywords

    _cached_services = service_map
    return service_map

def generate_keywords(service_name: str):
    """
    Basic keyword variants for a given service name, with naive Russian stemming
    to handle common case endings (e.g., "стрижка" → matches "стрижку").
    """
    base = service_name.lower()
    base = re.sub(r"[^\w\s]", "", base)
    variants = {base}
    # naive stem: drop a trailing vowel/soft sign (covers а/я/у/ю/ы/и/е/о/ь)
    if base and base[-1] in "аяуыюыеоиь":
        variants.add(base[:-1])
    return list(variants)

def match_service(text: str, service_dict: dict):
    query_text = text.lower()
    for service_name, keywords in service_dict.items():
        for keyword in keywords:
            if keyword in query_text:
                return service_name
    return None
