import hashlib
import hmac
import secrets
import string
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.v1._upload_helpers import validate_and_read_upload
from app.core.config import settings
from app.core.keys import ip_key
from app.core.rate_limit import limiter
from app.models.user import User
from app.services.import_service import (
    BankUnsupportedError,
    ImportService,
    ImportValidationError,
)
from app.services.upload_validator import UnsupportedUploadTypeError, UploadTooLargeError

router = APIRouter(prefix="/telegram", tags=["Telegram"])

_LINK_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_LINK_CODE_TTL_MINUTES = 15


class TelegramAuthData(BaseModel):
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class TelegramConnectResponse(BaseModel):
    ok: bool
    telegram_username: str | None


class TelegramLinkCodeResponse(BaseModel):
    ok: bool
    code: str
    expires_at: datetime
    bot_username: str


class TelegramBotConnectRequest(BaseModel):
    code: str
    telegram_id: int
    telegram_username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


class TelegramBotConnectResponse(BaseModel):
    ok: bool
    email: str
    telegram_username: str | None


class TelegramBotUserResponse(BaseModel):
    linked: bool
    email: str | None = None
    telegram_username: str | None = None


class TelegramStatusResponse(BaseModel):
    connected: bool
    telegram_id: int | None
    telegram_username: str | None
    pending_code: str | None
    pending_code_expires_at: datetime | None


class TelegramDisconnectResponse(BaseModel):
    ok: bool


class TelegramBotUploadResponse(BaseModel):
    ok: bool
    session_id: int
    filename: str
    status: str
    # Этап 0.5 — duplicate-detection signal forwarded from ImportService.
    # `None` on a fresh upload, `"choose"` if an active duplicate already
    # exists, `"warn"` if only committed duplicates exist. The bot reads this
    # to render a text reply instead of just "загружено" (the user has no
    # modal in Telegram, so we explain what happened in plain Russian).
    action_required: str | None = None
    bot_message: str | None = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_link_code(raw_code: str | None) -> str:
    return "".join(ch for ch in str(raw_code or "").upper() if ch.isalnum())


def _active_link_code(user: User) -> tuple[str | None, datetime | None]:
    if not user.telegram_link_code or not user.telegram_link_code_expires_at:
        return None, None
    if user.telegram_link_code_expires_at <= _now_utc():
        return None, None
    return user.telegram_link_code, user.telegram_link_code_expires_at


def _generate_unique_link_code(db: Session) -> str:
    while True:
        code = "".join(secrets.choice(_LINK_CODE_ALPHABET) for _ in range(8))
        exists = (
            db.query(User)
            .filter(
                User.telegram_link_code == code,
                User.telegram_link_code_expires_at.is_not(None),
                User.telegram_link_code_expires_at > _now_utc(),
            )
            .first()
        )
        if exists is None:
            return code


def verify_telegram_auth(data: TelegramAuthData) -> bool:
    """Верифицирует подпись данных от Telegram Login Widget."""
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        return False

    if time.time() - data.auth_date > 86400:
        return False

    fields = {
        "auth_date": str(data.auth_date),
        "first_name": data.first_name,
        "id": str(data.id),
        "last_name": data.last_name,
        "photo_url": data.photo_url,
        "username": data.username,
    }
    check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(fields.items()) if value is not None
    )

    secret = hashlib.sha256(token.encode()).digest()
    expected_hash = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()

    return hmac.compare_digest(expected_hash, data.hash)


def require_bot_token(x_telegram_bot_token: str | None = Header(default=None)) -> None:
    expected = settings.TELEGRAM_BOT_TOKEN
    if not expected or x_telegram_bot_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bot token")


@router.post("/connect", response_model=TelegramConnectResponse)
def connect_telegram(
    auth_data: TelegramAuthData,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Привязать Telegram аккаунт к текущему пользователю через Telegram Login Widget."""
    if not verify_telegram_auth(auth_data):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверная подпись Telegram. Попробуй ещё раз.",
        )

    existing = (
        db.query(User)
        .filter(
            User.telegram_id == auth_data.id,
            User.id != current_user.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Этот Telegram аккаунт уже привязан к другому пользователю.",
        )

    current_user.telegram_id = auth_data.id
    current_user.telegram_username = auth_data.username
    current_user.telegram_link_code = None
    current_user.telegram_link_code_expires_at = None
    db.commit()
    db.refresh(current_user)

    return TelegramConnectResponse(
        ok=True,
        telegram_username=auth_data.username,
    )


@router.get("/status", response_model=TelegramStatusResponse)
def telegram_status(
    current_user: User = Depends(get_current_user),
):
    """Статус привязки Telegram и активный код, если он есть."""
    pending_code, pending_code_expires_at = _active_link_code(current_user)
    return TelegramStatusResponse(
        connected=current_user.telegram_id is not None,
        telegram_id=current_user.telegram_id,
        telegram_username=current_user.telegram_username,
        pending_code=pending_code,
        pending_code_expires_at=pending_code_expires_at,
    )


@router.post("/link-code", response_model=TelegramLinkCodeResponse)
def generate_telegram_link_code(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Сгенерировать одноразовый код привязки Telegram."""
    if current_user.telegram_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telegram уже подключён. Сначала отвяжи его, если хочешь перепривязать аккаунт.",
        )

    code = _generate_unique_link_code(db)
    expires_at = _now_utc() + timedelta(minutes=_LINK_CODE_TTL_MINUTES)

    current_user.telegram_link_code = code
    current_user.telegram_link_code_expires_at = expires_at
    db.commit()
    db.refresh(current_user)

    return TelegramLinkCodeResponse(
        ok=True,
        code=code,
        expires_at=expires_at,
        bot_username=settings.TELEGRAM_BOT_NAME,
    )


@router.delete("/disconnect", response_model=TelegramDisconnectResponse)
def disconnect_telegram(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отвязать Telegram аккаунт."""
    current_user.telegram_id = None
    current_user.telegram_username = None
    current_user.telegram_link_code = None
    current_user.telegram_link_code_expires_at = None
    db.commit()
    return TelegramDisconnectResponse(ok=True)


@router.get("/user/{telegram_id}", response_model=TelegramBotUserResponse)
def get_user_by_telegram_id(
    telegram_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_bot_token),
):
    """Внутренний endpoint для бота — проверить, привязан ли Telegram аккаунт."""
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        return TelegramBotUserResponse(linked=False)

    return TelegramBotUserResponse(
        linked=True,
        email=user.email,
        telegram_username=user.telegram_username,
    )


@router.post("/bot/connect", response_model=TelegramBotConnectResponse)
def connect_telegram_via_code(
    payload: TelegramBotConnectRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_bot_token),
):
    """Внутренний endpoint для бота — привязать Telegram аккаунт по одноразовому коду."""
    code = _normalize_link_code(payload.code)
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Код привязки пуст.")

    user = db.query(User).filter(User.telegram_link_code == code).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Код не найден.")

    _, expires_at = _active_link_code(user)
    if expires_at is None:
        user.telegram_link_code = None
        user.telegram_link_code_expires_at = None
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Код истёк. Сгенерируй новый в настройках.")

    existing = (
        db.query(User)
        .filter(
            User.telegram_id == payload.telegram_id,
            User.id != user.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Этот Telegram аккаунт уже привязан к другому пользователю.",
        )

    user.telegram_id = payload.telegram_id
    user.telegram_username = payload.telegram_username
    user.telegram_link_code = None
    user.telegram_link_code_expires_at = None
    db.commit()
    db.refresh(user)

    return TelegramBotConnectResponse(
        ok=True,
        email=user.email,
        telegram_username=user.telegram_username,
    )


@router.post("/bot/upload", status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_BOT_UPLOAD, key_func=ip_key)
async def upload_import_from_telegram(
    request: Request,
    telegram_id: int = Form(...),
    file: UploadFile = File(...),
    delimiter: str = Form(","),
    db: Session = Depends(get_db),
    _: None = Depends(require_bot_token),
):
    """Внутренний endpoint для бота — загрузить выписку сразу в импорт-сессию пользователя.

    `response_model` опущен — ветки с 413/415 возвращают `JSONResponse`
    напрямую, success-ответ имеет ту же форму, что и `TelegramBotUploadResponse`.
    """
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Telegram аккаунт не привязан.")

    try:
        raw_bytes, _detected = await validate_and_read_upload(file)
    except UploadTooLargeError as exc:
        return JSONResponse(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, content=exc.to_payload())
    except UnsupportedUploadTypeError as exc:
        return JSONResponse(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, content=exc.to_payload())

    service = ImportService(db)
    try:
        result = service.upload_source(
            user_id=user.id,
            filename=file.filename or "import_file",
            raw_bytes=raw_bytes,
            delimiter=delimiter,
        )
    except BankUnsupportedError as exc:
        # Bot has no modal UI, so we render a plain Russian message that the
        # bot reads and replies in chat. Same JSON shape as the web route
        # (`bank_unsupported` code + bank_id + extractor_status), so the
        # backend contract stays uniform between web and bot.
        db.rollback()
        return JSONResponse(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            content={
                "code": "bank_unsupported",
                "bank_id": exc.bank_id,
                "bank_name": exc.bank_name,
                "extractor_status": exc.extractor_status,
                "detail": str(exc),
                "bot_message": (
                    f"Импорт из банка «{exc.bank_name}» пока не поддерживается. "
                    "Открой /import в веб-версии и нажми «Запросить поддержку банка», "
                    "если хочешь, чтобы он появился в whitelist."
                ),
            },
        )
    except ImportValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Этап 0.5 — duplicate detection. Bot has no modal UI, so we render a
    # plain Russian message that points the user back to /import for any
    # decisions (force_new is web-only — too easy to mis-trigger from chat).
    action_required = result.get("action_required")
    bot_message = _format_bot_duplicate_message(action_required, result)

    return TelegramBotUploadResponse(
        ok=True,
        session_id=result["session_id"],
        filename=result["filename"],
        status=result["status"],
        action_required=action_required.value if action_required else None,
        bot_message=bot_message,
    )


def _format_bot_duplicate_message(action_required, result: dict) -> str | None:
    """Plain-Russian text reply for duplicate-detected uploads via bot.

    Returns None on a fresh upload (no message needed — bot just confirms
    "загружено" through its own template). Date is formatted server-side so
    bot and web both see the same wording.
    """
    if action_required is None:
        return None
    created_at = result.get("existing_created_at")
    when = ""
    if created_at is not None:
        try:
            when = f" (загружена {created_at.strftime('%d.%m.%Y')})"
        except AttributeError:
            when = ""
    if action_required.value == "choose":
        return (
            f"Эта выписка уже в работе{when}. "
            "Открой /import в веб-версии чтобы продолжить или удалить старую сессию."
        )
    if action_required.value == "warn":
        return (
            f"Эта выписка уже импортирована{when}. "
            "Если нужно перезагрузить — открой /import в веб-версии."
        )
    return None