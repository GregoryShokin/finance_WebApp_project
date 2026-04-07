from __future__ import annotations

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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000/api/v1")
APP_IMPORT_URL = os.environ.get("APP_IMPORT_URL", "http://localhost:3000/import")
ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv"}
LINK_CODE_RE = re.compile(r"[A-Z0-9]{6,12}")


def bot_headers() -> dict[str, str]:
    return {"X-Telegram-Bot-Token": BOT_TOKEN}


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

    await update.message.reply_text(
        "Привет! Я помогу загрузить банковские выписки в FinanceApp.\n\n"
        "Как подключиться сейчас:\n"
        "1. Открой приложение -> Настройки -> Telegram\n"
        "2. Нажми «Получить код привязки»\n"
        "3. Пришли мне этот код сообщением или командой /start КОД\n\n"
        "После привязки просто отправь мне PDF, Excel или CSV файл выписки."
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    telegram_id = update.effective_user.id
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{API_BASE_URL}/telegram/user/{telegram_id}",
                headers=bot_headers(),
            )
            if resp.status_code != 200:
                await update.message.reply_text("Не удалось проверить статус привязки.")
                return

            data = resp.json()
            if data.get("linked"):
                await update.message.reply_text(
                    f"Аккаунт привязан: {data['email']}\n"
                    "Можешь отправлять выписки."
                )
            else:
                await update.message.reply_text(
                    "Аккаунт пока не привязан.\n"
                    "Открой приложение -> Настройки -> Telegram -> Получить код привязки, "
                    "затем пришли мне этот код."
                )
        except Exception:
            await update.message.reply_text("Ошибка соединения с сервером.")


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

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{API_BASE_URL}/telegram/bot/connect",
                headers=bot_headers(),
                json=payload,
            )
            if resp.status_code == 200:
                data = resp.json()
                username = data.get("telegram_username")
                await update.message.reply_text(
                    (
                        f"Готово! Telegram привязан к аккаунту {data['email']}.\n"
                        f"Username: @{username}\n\n"
                        if username
                        else f"Готово! Telegram привязан к аккаунту {data['email']}.\n\n"
                    )
                    + "Теперь можешь отправлять мне выписки файлами."
                )
                return

            detail = resp.json().get("detail") if resp.headers.get("content-type", "").startswith("application/json") else resp.text
            await update.message.reply_text(detail or "Не удалось привязать Telegram. Попробуй ещё раз.")
        except Exception as exc:
            logger.error("Error linking telegram account: %s", exc)
            await update.message.reply_text("Не удалось привязать аккаунт. Попробуй ещё раз чуть позже.")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    code = extract_link_code(update.message.text)
    if code:
        await try_link_account(update, code)
        return

    await update.message.reply_text(
        "Если хочешь привязать Telegram, пришли код из приложения.\n"
        "Его можно получить в Настройки -> Telegram -> Получить код привязки."
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.document is None or update.effective_user is None:
        return

    document: Document = update.message.document
    filename = document.file_name or "import_file"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        await update.message.reply_text(
            f"Файл формата {ext} не поддерживается.\n"
            "Пришли PDF, Excel (.xlsx/.xls) или CSV файл выписки."
        )
        return

    telegram_id = update.effective_user.id
    await update.message.reply_text("Загружаю выписку...")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{API_BASE_URL}/telegram/user/{telegram_id}",
                headers=bot_headers(),
            )
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            if resp.status_code != 200 or not data.get("linked"):
                await update.message.reply_text(
                    "Аккаунт не привязан.\n"
                    "Открой приложение -> Настройки -> Telegram -> Получить код привязки, "
                    "затем пришли мне этот код."
                )
                return

            file = await context.bot.get_file(document.file_id)
            file_bytes = await file.download_as_bytearray()

            upload_resp = await client.post(
                f"{API_BASE_URL}/telegram/bot/upload",
                headers=bot_headers(),
                files={"file": (filename, bytes(file_bytes), "application/octet-stream")},
                data={"telegram_id": str(telegram_id)},
            )

            if upload_resp.status_code == 201:
                await update.message.reply_text(
                    "Выписка загружена.\n\n"
                    f"Файл: {filename}\n"
                    "Проверь и подтверди транзакции в приложении.\n\n"
                    f"{APP_IMPORT_URL}"
                )
            else:
                detail = upload_resp.json().get("detail") if upload_resp.headers.get("content-type", "").startswith("application/json") else upload_resp.text
                await update.message.reply_text(f"Ошибка загрузки: {detail}")

    except Exception as exc:
        logger.error("Error handling document: %s", exc)
        await update.message.reply_text(
            "Произошла ошибка. Попробуй ещё раз или напиши /status"
        )


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()