import os
import re
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Load env variables
load_dotenv()

def get_connection():
    conn = psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", 5432)
    )
    # Ensure read-only, safe defaults
    try:
        allow_writes = os.getenv("ALLOW_WRITES", "0").lower() in ("1", "true", "yes")
        conn.set_session(readonly=not allow_writes, autocommit=True)
    except Exception:
        pass
    return conn

def _is_read_only_sql(sql: str) -> bool:
    # Strip comments
    s = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    s = re.sub(r"--.*?$", " ", s, flags=re.M)
    # Split by semicolon and check each non-empty statement
    parts = [p.strip().lower() for p in s.split(";") if p.strip()]
    if not parts:
        return False
    allowed_prefixes = ("select", "with", "explain")
    forbidden_keywords = (
        "insert", "update", "delete", "drop", "alter", "create",
        "grant", "revoke", "truncate", "vacuum", "analyze"
    )
    for stmt in parts:
        if any(kw in stmt for kw in forbidden_keywords):
            return False
        if not stmt.startswith(allowed_prefixes):
            return False
    return True

def execute_sql_query(sql_query: str, params=None):
    # if not _is_read_only_sql(sql_query or ""):
        # raise Exception("Only read-only SELECT/CTE/EXPLAIN queries are allowed")
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(sql_query, params or [])
            # For SELECT/RETURNING, cursor.description is present. For DML without RETURNING it's None.
            if cursor.description:
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                return rows, columns
            else:
                # No result set (e.g., INSERT/UPDATE/DELETE without RETURNING)
                return [], []
    except Exception as e:
        raise Exception(f"SQL Execution Error: {e}")
    finally:
        conn.close()
