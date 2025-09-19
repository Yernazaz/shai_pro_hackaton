import asyncio
import html
import io
import json
import logging
import os
from typing import Any, Dict

import httpx
from dotenv import load_dotenv
from app.utils.logging_config import get_logger
from app.utils.context_store import context_store

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

from app.utils.response_formatter import render_pipeline_reply


async def process_text_query(text: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The core logic for processing a text query, shared by text and voice handlers."""
    logger = get_logger(__name__)
    chat_id = update.effective_chat.id

    session_id = str(update.effective_user.id if update.effective_user else chat_id)
    pending_state, expired = context_store.load(session_id)
    if expired:
        await update.message.reply_text("Предыдущее уточнение просрочено, контекст очищен.")
    combined_query = text
    if pending_state and pending_state.get("next_query_hint"):
        base = pending_state["next_query_hint"].strip()
        if text:
            combined_query = f"{base}\n\nДополнительная информация пользователя: {text}"
        else:
            combined_query = base

    # show typing indicator while processing
    context.chat_data["last_query"] = text
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        logger.info(
            "[TG→Pipeline] query=%s | rewritten=%s | context=%s",
            text,
            combined_query,
            "[]",
        )
        request_payload = QueryRequest(
            query=combined_query,
            original_query=text,
            session_id=session_id,
            memory=context.chat_data.get("memory"),
            pending_state=pending_state,
        )
        result = await _run_pipeline(request_payload)
        memory_state = result.get("memory") or {}
        context.chat_data["memory"] = memory_state
        logger.info("-----------")
        try:
            summary = {
                "sql": result.get("sql"),
                "rows": len(result.get("rows", [])),
                "iterations": result.get("iterations_used"),
            }
            logger.info(
                "[TG←Pipeline] result=%s",
                json.dumps(summary, ensure_ascii=False, default=str),
            )
        except Exception:
            logger.exception("[TG] Failed to log pipeline summary")
        reply = render_pipeline_reply(result)

        # Ensure we don't exceed Telegram message limit
        if len(reply) > 4000:
            reply = reply[:3996] + " …"

        await update.message.reply_text(reply, disable_web_page_preview=True)
        logger.info("[TG→User] %s", reply)
        logger.info("-----------")
        pending_result = result.get("pending_state")
        if pending_result and pending_result.get("next_query_hint"):
            context_store.save(session_id, pending_result)
        else:
            context_store.clear(session_id)
        context.chat_data["last_sql"] = result.get("sql")
        context.chat_data["last_normalized_question"] = result.get("normalized_question")


    except Exception as e:
        logger.exception("Telegram handler error")
        await update.message.reply_text(f"Произошла ошибка: {e}")


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


async def _run_pipeline(request: QueryRequest) -> Dict[str, Any]:
    """Execute the same flow as the REST endpoint without blocking the event loop."""
    loop = asyncio.get_event_loop()
    # Offload sync work to default executor to avoid blocking
    return await loop.run_in_executor(None, lambda: handle_query(request))


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

    memory = chat_data.get("memory") or {}
    last_scope = chat_data.get("last_scope") or memory.get("last_scope")
    last_intent = chat_data.get("last_intent") or memory.get("last_intent")
    history = chat_data.get("history") or []
    last_query = chat_data.get("last_query") or memory.get("last_query")

    rewritten = rewrite_query_with_context(
        base_text,
        history,
        last_scope=last_scope,
        last_query=last_query,
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

    text = update.message.text.strip()
    logger = get_logger(__name__)
    logger.info("[TG] %s (%s): %s", update.effective_user.id if update.effective_user else "-", update.effective_user.username if update.effective_user else "-", text)

    await process_text_query(text, update, context)


async def handle_sql_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Try to fetch SQL for the last user message by re-running (stateless fallback)
    # In the future we could cache per chat, but this keeps it simple.
    try:
        last_text = context.chat_data.get("last_query") or update.message.text
        request_payload = QueryRequest(
            query=last_text,
            original_query=last_text,
            session_id=str(update.effective_user.id if update.effective_user else chat_id),
            memory=context.chat_data.get("memory"),
        )
        result = await _run_pipeline(request_payload)
        memory_state = result.get("memory") or {}
        if memory_state:
            context.chat_data["memory"] = memory_state
        sql = result.get("sql")
        if not sql:
            await update.message.reply_text("SQL не был сгенерирован для этого запроса.")
            return
        display_sql = sql
        if len(display_sql) > 3800:
            display_sql = display_sql[:3796] + " …"
        escaped_sql = html.escape(display_sql)
        await update.message.reply_text(f"<pre>{escaped_sql}</pre>", parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception("SQL keyword error")
        await update.message.reply_text(f"Ошибка при получении SQL: {e}")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.voice:
        return

    logger = get_logger(__name__)
    logger.info("[TG] Received voice message from %s", update.effective_user.id if update.effective_user else "-")

    n8n_webhook_url = os.getenv("N8N_VOICE_WEBHOOK_URL")
    if not n8n_webhook_url:
        logger.warning("N8N_VOICE_WEBHOOK_URL is not set, skipping voice message forwarding.")
        # Optionally, inform the user that voice messages are not configured
        # await update.message.reply_text("Обработка голосовых сообщений не настроена.")
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        
        voice = update.message.voice
        voice_file = await voice.get_file()
        voice_data = await voice_file.download_as_bytearray()

        # Wrap bytearray in BytesIO to make it a file-like object for httpx
        voice_stream = io.BytesIO(voice_data)

        # Prepare metadata to send alongside the file
        payload = {
            "file_id": voice.file_id,
            "file_unique_id": voice.file_unique_id,
            "duration": voice.duration,
            "mime_type": voice.mime_type or "audio/ogg",
            "chat_id": update.effective_chat.id,
            "user_id": update.effective_user.id if update.effective_user else "unknown",
            "message_id": update.message.message_id,
        }

        # The file name can be inferred from the path, but we can also set a default
        file_name = f"voice_{update.message.message_id}.oga"

        files = {"file": (file_name, voice_stream, "audio/ogg")}
        
        async with httpx.AsyncClient() as client:
            # Set a timeout for the request, e.g., 60 seconds
            response = await client.post(n8n_webhook_url, data=payload, timeout=60.0)
            response.raise_for_status()  # Raise an exception for bad status codes

        logger.info("Voice message forwarded to n8n successfully. Status code: %d", response.status_code)
        
        # Process n8n response to get transcription
        try:
            response_data = response.json()
            transcribed_text = response_data.get("transcription")

            if transcribed_text and transcribed_text.strip():
                logger.info("[TG] Transcription received from n8n: '%s'", transcribed_text)
                await update.message.reply_text(f"Распознано: «{transcribed_text}»")
                # Now process the transcribed text as a regular query
                await process_text_query(transcribed_text, update, context)
            else:
                logger.warning("N8n response did not contain a valid 'transcription' field. Response: %s", response_data)
                await update.message.reply_text("Не удалось распознать речь. Попробуйте еще раз.")

        except (json.JSONDecodeError, AttributeError) as json_err:
            logger.error("Failed to decode JSON from n8n response: %s", response.text)
            await update.message.reply_text("Ошибка обработки ответа от сервиса распознавания.")

    except httpx.HTTPStatusError as http_err:
        logger.exception("HTTP error forwarding voice message to n8n: %s", http_err.response.text)
        await update.message.reply_text("Ошибка при отправке голосового сообщения на обработку.")
    except Exception as e:
        logger.exception("Error forwarding voice message to n8n")
        await update.message.reply_text(f"Ошибка при обработке голосового сообщения: {e}")


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

    # Voice message handler
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    logging.info("Telegram bot is starting (polling mode)…")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
