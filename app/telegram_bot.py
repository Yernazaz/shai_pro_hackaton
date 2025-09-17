import asyncio
import json
import logging
import os
import time
from typing import Any, Dict

from dotenv import load_dotenv
from app.utils.logging_config import get_logger
from scripts.employee_names import reload_employee_names

# Reuse the same pipeline as the API by calling handle_query directly
from app.main import handle_query, QueryRequest

# Telegram bot (async, PTB v21+)
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.utils.query_rewrite import rewrite_query_with_context
from app.utils.response_formatter import render_pipeline_reply

def _serialize_history(history: list[Dict[str, Any]] | None) -> list[Dict[str, Any]]:
    if not history:
        return []
    cleaned = []
    for turn in history[-12:]:
        cleaned.append({
            "role": turn.get("role"),
            "content": turn.get("content"),
        })
    return cleaned


async def _run_pipeline(text: str, chat_context: list[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    """Execute the same flow as the REST endpoint without blocking the event loop."""
    loop = asyncio.get_event_loop()
    # Offload sync work to default executor to avoid blocking
    return await loop.run_in_executor(None, lambda: handle_query(QueryRequest(query=text, chat_context=chat_context)))


def _maybe_rewrite_query(text: str, chat_data: Dict[str, Any], allow_context: bool) -> str:
    """Rewrite short follow-ups like 'дай номера' using last scope.
    Scope is 'employees' or 'clients'.
    """
    t = (text or "").strip()
    if len(t) > 64 and not chat_data.get("pending_booking"):
        return text
    if not allow_context:
        return text

    pending = chat_data.get("pending_booking")
    base_text = text
    if pending:
        combined = f"{pending.get('base_query', '')} {text}".strip()
        pending["base_query"] = combined
        base_text = combined

    last_scope = chat_data.get("last_scope")
    last_intent = chat_data.get("last_intent")
    history = chat_data.get("history") or []

    rewritten = rewrite_query_with_context(
        base_text,
        history,
        last_scope=last_scope,
        last_query=chat_data.get("last_query"),
    )
    if rewritten != base_text:
        return rewritten

    want_phones = any(kw in t.lower() for kw in ["номер", "номера", "телефон", "телефоны"])
    if want_phones and last_scope in ("employees", "clients"):
        if last_scope == "employees" or last_intent == "list_employees":
            return "перечисли номера телефонов сотрудников"
        if last_scope == "clients" or last_intent == "list_clients":
            return "перечисли номера телефонов клиентов"

    lowered = t.lower()
    if "максим" in lowered or "миним" in lowered:
        stat_followups = {
            "top_employees_by_revenue": {
                "максим": "какой сотрудник принёс максимальный доход и какая это сумма?",
                "миним": "какой сотрудник показал минимальный доход и сколько это?",
            },
            "services_by_employee": {
                "максим": "у какого сотрудника самое большое количество оказанных услуг?",
                "миним": "у какого сотрудника самое маленькое количество оказанных услуг?",
            },
            "client_total_spending": {
                "максим": "какой клиент потратил больше всего и сколько именно?",
                "миним": "какой клиент потратил меньше всего и сколько именно?",
            },
        }

        intents_map = stat_followups.get(last_intent or "")
        if intents_map:
            for marker, rewrite in intents_map.items():
                if marker in lowered:
                    return rewrite
    return text


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "Привет! Я бот NQL CRM. Отправьте мне текстовый запрос, "
            "например: 'выручка за прошлый месяц' или 'продуктивность сотрудников'."
        ),
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Clear conversational context for this chat
    context.chat_data.clear()
    await update.message.reply_text("Контекст очищен.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    logger = get_logger(__name__)
    logger.info("[TG] %s (%s): %s", update.effective_user.id if update.effective_user else "-", update.effective_user.username if update.effective_user else "-", text)

    # Direct command fast-paths (reliable regardless of intent)
    if os.getenv("ALLOW_WRITES", "0").lower() in ("1", "true", "yes"):
        low = text.lower()
        try:
            # 1) Delete appointments by last result ("удали эти записи")
            if low.startswith("удали") and "запис" in low and ("эти" in low or "их" in low):
                last_ids = context.chat_data.get("last_appointment_ids") or []
                if last_ids:
                    from app.services.appointments import delete_appointments
                    count = delete_appointments(appointment_ids=last_ids)
                    msg = f"Удалено записей: {count}."
                    await update.message.reply_text(msg)
                    logger.info("[TG→User] %s", msg)
                    return
                # No cached ids
                await update.message.reply_text("Нет идентификаторов записей. Сначала запросите список, затем скажите: 'удали эти записи'.")
                return

            # 2) Delete employee (only if not 'удали записи ...')
            if low.startswith("удали") or " удалить " in f" {low} ":
                from app.services.employees import delete_employee
                ok, msg = delete_employee(None, text)
                reload_employee_names()
                await update.message.reply_text(msg)
                logger.info("[TG→User] %s", msg)
                return
            if low.startswith("добав") or low.startswith("создай"):
                from app.services.employees import add_employee, extract_phone
                ok, msg = add_employee(None, extract_phone(text), text)
                reload_employee_names()
                await update.message.reply_text(msg)
                logger.info("[TG→User] %s", msg)
                return
        except Exception as e:
            logging.exception("Direct employee command error")
            await update.message.reply_text(f"Ошибка: {e}")
            return

    # Recency gate: ignore context if older than 1 hour
    now_ts = time.time()
    last_ts = context.chat_data.get("last_ts")
    allow_context = bool(last_ts) and (now_ts - float(last_ts) <= 3600)

    # Heuristic rewrite for short follow-ups (e.g., 'дай номера')
    text_for_pipeline = _maybe_rewrite_query(text, context.chat_data, allow_context)
    # Build recent chat context (store simple role/content turns)
    history: list[Dict[str, Any]] = context.chat_data.get("history") or []
    chat_ctx = history[-8:] if (history and allow_context) else None
    # Store last query in chat_data and show typing indicator while processing
    context.chat_data["last_query"] = text
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        logger.info(
            "[TG→Pipeline] query=%s | rewritten=%s | context=%s",
            text,
            text_for_pipeline,
            json.dumps(_serialize_history(chat_ctx or []), ensure_ascii=False, default=str),
        )
        result = await _run_pipeline(text_for_pipeline, chat_ctx)
        try:
            summary = {
                "intent": result.get("intent"),
                "entities": result.get("entities"),
                "tables": result.get("tables"),
                "sql": result.get("sql"),
                "followups": result.get("followup_questions"),
            }
            logger.info(
                "[TG←Pipeline] result=%s",
                json.dumps(summary, ensure_ascii=False, default=str),
            )
        except Exception:
            logger.exception("[TG] Failed to log pipeline summary")
        # Optional: booking flow guarded by env flag
        if (result.get("intent") == "create_appointment"):
            if os.getenv("ALLOW_WRITES", "0").lower() in ("1", "true", "yes"):
                from app.services.booking import book_from_entities, list_missing_booking_fields
                # Use original (non-lowercased) text to preserve name casing
                original = result.get("original_query") or text
                missing = list_missing_booking_fields(original, result.get("entities") or {})
                # If we only miss optional employee, proceed
                required_missing = [m for m in missing if m != "сотрудник (по желанию)"]
                if required_missing:
                    bullets = "\n".join(f"• {m}" for m in required_missing)
                    await update.message.reply_text(
                        f"Чтобы создать запись, уточните:\n{bullets}"
                    )
                    context.chat_data["pending_booking"] = {
                        "base_query": original,
                        "missing": required_missing,
                    }
                    return
                ok, msg = book_from_entities(original, result.get("intent"), result.get("entities") or {})
                await update.message.reply_text(msg)
                logger.info("[TG→User] %s", msg)
                context.chat_data.pop("pending_booking", None)
                return
            else:
                await update.message.reply_text(
                    "Я понял, вы хотите записаться. Чтобы включить создание записей (INSERT), задайте переменную окружения ALLOW_WRITES=true. Сейчас операции записи отключены."
                )
                logger.info("[TG→User] writes_disabled_booking")
                return
        # Create/Delete employee flows
        if result.get("intent") in ("create_employee", "delete_employee"):
            if os.getenv("ALLOW_WRITES", "0").lower() not in ("1", "true", "yes"):
                await update.message.reply_text("Операции записи отключены (ALLOW_WRITES=false).")
                return
            # Parse name and optional phone from original text
            original = result.get("original_query") or text
            from app.services.employees import extract_phone
            full_name = None  # allow employees.add to parse from original text
            phone = extract_phone(original)
            if result.get("intent") == "create_employee":
                from app.services.employees import add_employee
                ok, msg = add_employee(full_name, phone, original)
                # Refresh employee cache for name matching
                reload_employee_names()
                await update.message.reply_text(msg)
                logger.info("[TG→User] %s", msg)
                return
            else:
                from app.services.employees import delete_employee
                ok, msg = delete_employee(full_name, original)
                reload_employee_names()
                await update.message.reply_text(msg)
                logger.info("[TG→User] %s", msg)
                return
        reply = render_pipeline_reply(result)

        # Ensure we don't exceed Telegram message limit
        if len(reply) > 4000:
            reply = reply[:3996] + " …"

        await update.message.reply_text(reply, disable_web_page_preview=True)
        logger.info("[TG→User] %s", reply)
        # Update conversational scope for follow-ups
        intent = result.get("intent")
        if intent in (
            "list_employees",
            "create_employee",
            "delete_employee",
            "services_by_employee",
            "top_employees_by_revenue",
            "employee_productivity",
        ):
            context.chat_data["last_scope"] = "employees"
        elif intent in (
            "list_clients",
            "client_count",
            "client_total_spending",
            "client_last_visit",
            "frequent_clients",
        ):
            context.chat_data["last_scope"] = "clients"
        elif intent in ("list_appointments", "upcoming_appointments"):
            context.chat_data["last_scope"] = "appointments"

        # Cache last appointment IDs for follow-up deletion
        last_ids = []
        try:
            qr = result.get("query_result") or []
            for row in qr:
                if isinstance(row, dict):
                    if "id" in row and isinstance(row["id"], int):
                        last_ids.append(row["id"])
                    elif "appointment_id" in row and isinstance(row["appointment_id"], int):
                        last_ids.append(row["appointment_id"])
        except Exception:
            pass
        if last_ids:
            context.chat_data["last_appointment_ids"] = last_ids[-50:]
        # Save history turn
        history.append({"role": "user", "content": text, "ts": now_ts})
        history.append({"role": "assistant", "content": reply, "ts": now_ts})
        context.chat_data["history"] = history[-20:]
        context.chat_data["last_intent"] = intent
        context.chat_data["last_ts"] = now_ts

        # Optional: if SQL was generated and user might want it, hint with a footer
        if (result.get("sql") or (result.get("generated_response") or {}).get("sql_query")) and not (result.get("followup_questions")):
            await context.bot.send_message(
                chat_id=chat_id,
                text="Если нужен SQL — напишите: sql",
            )
    except Exception as e:
        logging.exception("Telegram handler error")
        await update.message.reply_text(f"Произошла ошибка: {e}")


async def handle_sql_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Try to fetch SQL for the last user message by re-running (stateless fallback)
    # In the future we could cache per chat, but this keeps it simple.
    try:
        last_text = context.chat_data.get("last_query") or update.message.text
        result = await _run_pipeline(last_text)
        sql = result.get("sql") or (result.get("generated_response") or {}).get("sql_query")
        if not sql:
            await update.message.reply_text("SQL не был сгенерирован для этого запроса.")
            return
        if len(sql) > 3800:
            sql = sql[:3796] + " …"
        await update.message.reply_text(f"<pre>{sql}</pre>", parse_mode=ParseMode.HTML)
    except Exception as e:
        logging.exception("SQL keyword error")
        await update.message.reply_text(f"Ошибка при получении SQL: {e}")


def main() -> None:
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in environment")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    app = ApplicationBuilder().token(token).build()

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))

    # Simple 'sql' keyword to show the last query's SQL again
    app.add_handler(MessageHandler(filters.Regex(r"^\s*sql\s*$") & ~filters.COMMAND, handle_sql_keyword))

    # Main text handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logging.info("Telegram bot is starting (polling mode)…")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
