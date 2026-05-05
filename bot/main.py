from __future__ import annotations

import asyncio
import logging
import os
import re

import httpx
from telegram import Document, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000/api/v1")
APP_IMPORT_URL = os.environ.get("APP_IMPORT_URL", "http://localhost:3000/import")
ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv"}
LINK_CODE_RE = re.compile(r"[A-Z0-9]{6,12}")

API_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
UPLOAD_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def bot_headers() -> dict[str, str]:
    return {"X-Telegram-Bot-Token": BOT_TOKEN}


async def safe_reply(update: Update, text: str) -> None:
    """Reply but never raise — Telegram timeouts shouldn't crash handlers."""
    if update.message is None:
        return
    try:
        await update.message.reply_text(text)
    except Exception as exc:
        logger.warning("reply_text failed: %s", exc)


def extract_link_code(text: str | None) -> str | None:
    if not text:
        return None
    normalized = text.upper().strip()
    if normalized.startswith("/START"):
        parts = normalized.split(maxsplit=1)
        normalized = parts[1].strip() if len(parts) > 1 else ""
    match = LINK_CODE_RE.search(normalized)
    return match.group(0) if match else None


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    code = extract_link_code(update.message.text)
    if code:
        await try_link_account(update, code)
        return

    await safe_reply(
        update,
        "Привет! Я помогу загрузить банковские выписки в FinanceApp.\n\n"
        "Как подключиться сейчас:\n"
        "1. Открой приложение -> Настройки -> Telegram\n"
        "2. Нажми «Получить код привязки»\n"
        "3. Пришли мне этот код сообщением или командой /start КОД\n\n"
        "После привязки просто отправь мне PDF, Excel или CSV файл выписки.",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    telegram_id = update.effective_user.id
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        try:
            resp = await client.get(
                f"{API_BASE_URL}/telegram/user/{telegram_id}",
                headers=bot_headers(),
            )
            if resp.status_code != 200:
                await safe_reply(update, "Не удалось проверить статус привязки.")
                return

            data = resp.json()
            if data.get("linked"):
                await safe_reply(
                    update,
                    f"Аккаунт привязан: {data['email']}\nМожешь отправлять выписки.",
                )
            else:
                await safe_reply(
                    update,
                    "Аккаунт пока не привязан.\n"
                    "Открой приложение -> Настройки -> Telegram -> Получить код привязки, "
                    "затем пришли мне этот код.",
                )
        except Exception as exc:
            logger.warning("cmd_status failed: %s", exc)
            await safe_reply(update, "Ошибка соединения с сервером.")


async def try_link_account(update: Update, code: str) -> None:
    if update.message is None or update.effective_user is None:
        return

    payload = {
        "code": code,
        "telegram_id": update.effective_user.id,
        "telegram_username": update.effective_user.username,
        "first_name": update.effective_user.first_name,
        "last_name": update.effective_user.last_name,
    }

    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        try:
            resp = await client.post(
                f"{API_BASE_URL}/telegram/bot/connect",
                headers=bot_headers(),
                json=payload,
            )
            if resp.status_code == 200:
                data = resp.json()
                username = data.get("telegram_username")
                await safe_reply(
                    update,
                    (
                        f"Готово! Telegram привязан к аккаунту {data['email']}.\n"
                        f"Username: @{username}\n\n"
                        if username
                        else f"Готово! Telegram привязан к аккаунту {data['email']}.\n\n"
                    )
                    + "Теперь можешь отправлять мне выписки файлами.",
                )
                return

            detail = resp.json().get("detail") if resp.headers.get("content-type", "").startswith("application/json") else resp.text
            await safe_reply(update, detail or "Не удалось привязать Telegram. Попробуй ещё раз.")
        except Exception as exc:
            logger.error("Error linking telegram account: %s", exc)
            await safe_reply(update, "Не удалось привязать аккаунт. Попробуй ещё раз чуть позже.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    code = extract_link_code(update.message.text)
    if code:
        await try_link_account(update, code)
        return

    await safe_reply(
        update,
        "Если хочешь привязать Telegram, пришли код из приложения.\n"
        "Его можно получить в Настройки -> Telegram -> Получить код привязки.",
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.document is None or update.effective_user is None:
        return

    document: Document = update.message.document
    filename = document.file_name or "import_file"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        await safe_reply(
            update,
            f"Файл формата {ext} не поддерживается.\n"
            "Пришли PDF, Excel (.xlsx/.xls) или CSV файл выписки.",
        )
        return

    telegram_id = update.effective_user.id
    await safe_reply(update, "Загружаю выписку...")

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as status_client:
            resp = await status_client.get(
                f"{API_BASE_URL}/telegram/user/{telegram_id}",
                headers=bot_headers(),
            )
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            if resp.status_code != 200 or not data.get("linked"):
                await safe_reply(
                    update,
                    "Аккаунт не привязан.\n"
                    "Открой приложение -> Настройки -> Telegram -> Получить код привязки, "
                    "затем пришли мне этот код.",
                )
                return

        file = await context.bot.get_file(document.file_id, read_timeout=60)
        file_bytes = await file.download_as_bytearray(read_timeout=120)

        async with httpx.AsyncClient(timeout=UPLOAD_TIMEOUT) as upload_client:
            upload_resp = await upload_client.post(
                f"{API_BASE_URL}/telegram/bot/upload",
                headers=bot_headers(),
                files={"file": (filename, bytes(file_bytes), "application/octet-stream")},
                data={"telegram_id": str(telegram_id)},
            )

        if upload_resp.status_code == 201:
            payload = upload_resp.json()
            # Этап 0.5 — duplicate-detection text reply. Backend formats the
            # Russian message (one source of truth for date format / wording);
            # bot just forwards it. Falls back to the standard "загружено"
            # reply when no duplicate was detected.
            bot_message = payload.get("bot_message")
            if bot_message:
                await safe_reply(update, bot_message)
            else:
                await safe_reply(
                    update,
                    "Выписка загружена.\n\n"
                    f"Файл: {filename}\n"
                    "Проверь и подтверди транзакции в приложении.\n\n"
                    f"{APP_IMPORT_URL}",
                )
        else:
            detail = (
                upload_resp.json().get("detail")
                if upload_resp.headers.get("content-type", "").startswith("application/json")
                else upload_resp.text
            )
            await safe_reply(update, f"Ошибка загрузки: {detail}")

    except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
        logger.error("Timeout handling document %s: %s", filename, exc)
        await safe_reply(
            update,
            "Не удалось обработать выписку — превышено время ожидания. "
            "Попробуй ещё раз через минуту или загрузи файл через приложение.",
        )
    except Exception as exc:
        logger.exception("Error handling document: %s", exc)
        await safe_reply(
            update,
            "Произошла ошибка. Попробуй ещё раз или напиши /status",
        )


def main() -> None:
    request = HTTPXRequest(
        connect_timeout=15.0,
        read_timeout=60.0,
        write_timeout=60.0,
        pool_timeout=10.0,
    )
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
