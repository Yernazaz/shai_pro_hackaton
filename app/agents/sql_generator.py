import os
from decimal import Decimal
from app.registry.agent_registry import registry
import json
from app.pipeline.context import PipelineContext
from app.schema.bot_response import BotResponse
from app.prompt_generator import generate_prompt
from app.services.execute_sql_query import execute_sql_query
from app.services.generate_summary import generate_summary_from_result
from app.utils.openai_config import get_openai_model
from app.utils.llm_client import chat_completion
from app.utils.logging_config import get_logger

logger = get_logger(__name__)

class SQLGeneratorAgent:
    def run(self, context: PipelineContext) -> PipelineContext:
        logger.info("[SQLGenerator] Running for intent: %s", context.intent)

        # Skip LLM for intents handled by bot with write operations
        if context.intent in ("create_employee", "delete_employee"):
            context.generated_response = {
                "type": "noop",
                "status": "skipped",
                "sql_query": None,
                "human_readable_text": "Операция выполняется ботом (создание/удаление сотрудника)."
            }
            return context

        # Fast-path intents with deterministic SQL (avoid LLM drift)
        if context.intent in ("list_employees", "list_clients", "client_count", "employee_count", "list_services"):
            try:
                date_filtered = False
                date_range_strings: tuple[str, str] | None = None
                if context.intent == "list_employees":
                    sql = (
                        "SELECT e.id AS employee_id, p.first_name, p.last_name, p.phone_number, e.position, e.hire_date "
                        "FROM crm_employees e "
                        "JOIN crm_people p ON p.id = e.person_id "
                        "WHERE e.is_active = TRUE "
                        "ORDER BY p.last_name, p.first_name"
                    )
                elif context.intent == "list_clients":
                    sql = (
                        "SELECT c.id AS client_id, p.first_name, p.last_name, p.phone_number, c.loyalty_level "
                        "FROM crm_clients c "
                        "JOIN crm_people p ON p.id = c.person_id "
                        "ORDER BY p.last_name, p.first_name"
                    )
                elif context.intent == "employee_count":
                    sql = "SELECT COUNT(*) AS count FROM crm_employees WHERE is_active = TRUE"
                else:  # client_count
                    if context.intent == "client_count":
                        entities = context.entities or {}
                        date_range = entities.get("date_range") if isinstance(entities, dict) else None
                        start = date_range.get("start") if isinstance(date_range, dict) else None
                        end = date_range.get("end") if isinstance(date_range, dict) else None
                        if start and end:
                            start_str = start.isoformat() if hasattr(start, "isoformat") else str(start)
                            end_str = end.isoformat() if hasattr(end, "isoformat") else str(end)
                            sql = (
                                "SELECT COUNT(DISTINCT a.client_id) AS count "
                                "FROM crm_appointments a "
                                "WHERE a.client_id IS NOT NULL "
                                f"AND DATE(a.scheduled_start) BETWEEN '{start_str}' AND '{end_str}' "
                                "AND (a.status IS NULL OR LOWER(a.status) <> 'cancelled')"
                            )
                            date_filtered = True
                            date_range_strings = (start_str, end_str)
                        else:
                            sql = "SELECT COUNT(*) AS count FROM crm_clients"
                    else:  # list_services
                        sql = (
                            "SELECT cat.name AS category_name, srv.name AS service_name, srv.base_price, srv.duration_minutes "
                            "FROM crm_services srv "
                            "LEFT JOIN crm_service_categories cat ON cat.id = srv.category_id "
                            "ORDER BY cat.name NULLS LAST, srv.name"
                        )

                result, columns = execute_sql_query(sql)
                context.sql = sql
                context.query_result = result
                # Deterministic human-readable text for lists/counts
                summary = ""
                if context.intent in ("list_employees", "list_clients", "list_services"):
                    lines = []
                    if context.intent == "list_services":
                        by_category: dict[str, list[str]] = {}
                        for row in result:
                            cat = row.get("category_name") or "Без категории"
                            name = row.get("service_name", "")
                            price = row.get("base_price")
                            duration = row.get("duration_minutes")
                            if isinstance(price, Decimal):
                                price = float(price)
                            if isinstance(price, (int, float)):
                                price_str = f"{int(price)} ₸"
                            else:
                                price_str = f"{price} ₸"
                            detail = f"- {name} — {price_str}, {duration} мин"
                            by_category.setdefault(cat, []).append(detail)
                        blocks = []
                        for cat, services in by_category.items():
                            blocks.append(f"{cat}:\n" + "\n".join(services))
                        summary = "Список услуг:\n" + "\n\n".join(blocks)
                    else:
                        who = "сотрудников" if context.intent == "list_employees" else "клиентов"
                        for i, row in enumerate(result, 1):
                            name = f"{row.get('first_name','').strip()} {row.get('last_name','').strip()}".strip()
                            phone = row.get('phone_number') or ""
                            extra = ""
                            if context.intent == "list_employees":
                                position = row.get("position") or ""
                                if position:
                                    extra = f" — {position}"
                            else:
                                loyalty = row.get("loyalty_level") or ""
                                if loyalty:
                                    extra = f" — статус {loyalty}"
                            line = f"{i}. {name}" + (f", {phone}" if phone else "") + extra
                            lines.append(line)
                        summary = f"Список {who}:\n" + "\n".join(lines)
                else:
                    # counts
                    key = "count" if result and "count" in result[0] else list(result[0].keys())[0] if result else "count"
                    val = result[0][key] if result else 0
                    if context.intent == "client_count" and date_filtered and date_range_strings:
                        start_str, end_str = date_range_strings
                        summary = (
                            f"За период с {start_str} по {end_str} обслужено {val} уникальных клиентов."
                        )
                    else:
                        summary = str(val)
                context.generated_response = {
                    "type": context.intent,
                    "status": "success",
                    "sql_query": sql,
                    "appointments": [],
                    "human_readable_text": (summary or "").strip(),
                }
                return context
            except Exception as e:
                context.query_result = {"error": str(e)}
                logger.exception("[SQLGenerator] Fast-path error: %s", e)
                return context

        if context.intent == "most_expensive_service":
            try:
                sql = (
                    "WITH max_price AS (\n"
                    "    SELECT MAX(price) AS price FROM crm_appointment_services\n"
                    "), ranked AS (\n"
                    "    SELECT\n"
                    "        aps.price,\n"
                    "        aps.appointment_id,\n"
                    "        srv.name AS service_name,\n"
                    "        p_emp.first_name AS employee_first_name,\n"
                    "        p_emp.last_name AS employee_last_name,\n"
                    "        a.scheduled_start\n"
                    "    FROM crm_appointment_services aps\n"
                    "    JOIN crm_services srv ON srv.id = aps.service_id\n"
                    "    JOIN max_price mp ON mp.price = aps.price\n"
                    "    LEFT JOIN crm_employees emp ON emp.id = aps.employee_id\n"
                    "    LEFT JOIN crm_people p_emp ON p_emp.id = emp.person_id\n"
                    "    LEFT JOIN crm_appointments a ON a.id = aps.appointment_id\n"
                    ")\n"
                    "SELECT\n"
                    "    service_name,\n"
                    "    price,\n"
                    "    appointment_id,\n"
                    "    employee_first_name,\n"
                    "    employee_last_name,\n"
                    "    scheduled_start\n"
                    "FROM ranked\n"
                    "ORDER BY service_name, appointment_id"
                )

                result, columns = execute_sql_query(sql)
                context.sql = sql
                context.query_result = result

                def _format_currency(value):
                    if isinstance(value, Decimal):
                        value = float(value)
                    if isinstance(value, (int, float)):
                        if abs(value - int(value)) < 1e-6:
                            formatted = f"{int(value):,}".replace(",", " ")
                        else:
                            formatted = f"{value:,.2f}".replace(",", " ")
                        return f"{formatted} ₸"
                    return str(value)

                lines = []
                for row in result:
                    service = (row.get("service_name") or "Неизвестная услуга").strip()
                    price = _format_currency(row.get("price"))
                    employee = " ".join(filter(None, [row.get("employee_first_name"), row.get("employee_last_name")])).strip()
                    appointment = row.get("appointment_id")
                    chunk = f"{service} — {price}"
                    if employee:
                        chunk += f" (исполнитель: {employee})"
                    if appointment:
                        chunk += f", запись №{appointment}"
                    lines.append(chunk)

                summary = "Самая дорогая услуга не найдена." if not lines else (
                    "Самая дорогая услуга: " + "; ".join(lines) + "."
                )

                context.generated_response = {
                    "type": "most_expensive_service",
                    "status": "success",
                    "sql_query": sql,
                    "appointments": [],
                    "human_readable_text": summary,
                }
                return context
            except Exception as e:
                context.query_result = {"error": str(e)}
                logger.exception("[SQLGenerator] Fast-path error (most_expensive_service): %s", e)
                return context

        # Allow offline/dev mode without OpenAI
        if os.getenv("DISABLE_OPENAI", "0").lower() in ("1", "true", "yes"):
            context.generated_response = {
                "type": "appointment_list",
                "status": "skipped",
                "sql_query": None,
                "human_readable_text": "Генерация SQL отключена (dev-режим). Доступны intent, entities, tables, columns."
            }
            context.sql = ""
            return context

        # Prepare messages for GPT
        system_msg = {
            "role": "system",
            "content": generate_prompt()  
        }

        # Optional conversation context to help resolve pronouns/scopes
        chat_ctx_str = ""
        if getattr(context, "chat_context", None):
            # Limit and format last few turns
            turns = context.chat_context[-6:]
            lines = []
            for t in turns:
                role = t.get("role", "user")
                content = str(t.get("content", ""))[:300]
                lines.append(f"- {role}: {content}")
            chat_ctx_str = "\nRecent conversation context (latest last):\n" + "\n".join(lines) + "\n"

        user_msg = {
            "role": "user",
            "content": f"""
        The user asked: {context.cleaned_query}
        {chat_ctx_str}
        Your task is to generate an SQL query that fulfills the user's request.
        Intent: {context.intent}
        Entities: {context.entities}
        Tables: {context.tables}
        Columns: {context.columns}

        ONLY return aggregated values (like SUM or COUNT) if the user is asking for statistics.
        Everthing is in Kazakhstani Tenge (₸).
        Respond using the function below:
        """
        }

        # Function schema for structured output (Pydantic v2 JSON schema)
        functions = [{
            "name": "execute_sql_query",
            "description": "Generate SQL and structure the response",
            "parameters": BotResponse.model_json_schema()
        }]

        try:
            try:
                logger.info(
                    "[SQLGenerator] LLM prompt system=%s | user=%s",
                    system_msg["content"],
                    user_msg["content"],
                )
            except Exception:
                logger.exception("[SQLGenerator] Failed to log prompt")

            response = chat_completion(
                model=get_openai_model(),
                messages=[system_msg, user_msg],
                functions=functions,
                function_call={"name": "execute_sql_query"},
                temperature=0.1,
            )

            message = response["choices"][0]["message"] if isinstance(response, dict) else response.choices[0].message
            # Support legacy function_call and modern tool_calls
            structured_json = None
            if isinstance(message, dict):
                if "function_call" in message and message["function_call"]:
                    structured_json = message["function_call"].get("arguments")
                elif "tool_calls" in message and message["tool_calls"]:
                    # take the first tool call with our function name
                    for tc in message["tool_calls"]:
                        fn = (tc.get("function") or {})
                        if fn.get("name") == "execute_sql_query":
                            structured_json = fn.get("arguments")
                            break
            if not structured_json:
                raise ValueError("No function/tool call arguments returned by model")
            parsed = json.loads(structured_json)
            sql_string = parsed.get("sql_query")

            context.generated_response = parsed
            context.sql = sql_string
            if sql_string:
                try:
                    logger.info("[SQLGenerator] Executing SQL: %s", sql_string)
                    result, columns = execute_sql_query(sql_string)
                    try:
                        logger.info(
                            "[SQLGenerator] SQL result: %s",
                            json.dumps(result[:50], ensure_ascii=False, default=str),
                        )
                    except Exception:
                        logger.exception("[SQLGenerator] Failed to log SQL result")
                    context.query_result = result

                    try:
                        summary = generate_summary_from_result(
                            context.intent,
                            result,
                            getattr(context, "original_query", None),
                        )
                        context.generated_response["human_readable_text"] = summary
                        logger.info("[SQLGenerator] Query and summary generated successfully.")
                    except Exception as e:
                        # Summary generation is optional; keep query result
                        logger.exception("[SQLGenerator] Error generating summary: %s", str(e))

                    logger.info("[SQLGenerator] Query executed successfully.")
                except Exception as sql_error:
                    context.query_result = {"error": str(sql_error)}
                    logger.exception("[SQLGenerator] SQL execution failed: %s", str(sql_error))
            else:
                context.query_result = {"error": "No SQL query returned from GPT"}
                logger.warning("[SQLGenerator] Missing SQL in GPT output.")

            return context
        except Exception as e:
            context.query_result = {"error": str(e)}
            logger.exception("[SQLGenerator] Error during GPT call: %s", str(e))
            return context

registry.register("sql", SQLGeneratorAgent())
