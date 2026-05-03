"""Debounced global transfer matcher.

Единая точка запуска `TransferMatcherService.match_transfers_for_user`.
Все места, которые раньше вызывали матчер синхронно или через отдельные таски
(`build_preview`, `auto_preview_import_session`, `PATCH /imports/{id}/account`,
`POST /imports/rematch-transfers`), теперь вызывают `schedule_transfer_match(user_id)`.

Алгоритм коалесценции (token-based debounce):
    1. При каждом вызове `schedule_transfer_match` генерируется свежий token
       (time.time_ns()) и кладётся в Redis под ключом `tm:debounce:{user_id}`
       с TTL 30с (перетирая предыдущие).
    2. Ставится Celery-task `match_transfers_for_user_debounced.apply_async`
       с countdown=3 секунды и передачей user_id + token.
    3. Когда задача срабатывает, она сверяет переданный token с текущим
       значением ключа в Redis. Если значение в Redis НЕ равно token (т.е.
       уже был более поздний вызов и он перепишет ключ на свой token), задача
       выходит как superseded — другая задача запустит матчер позже.
    4. Если token совпал — запускается матчер, ключ чистится.

Пять триггеров попадают в один канал `tm:debounce:{user_id}`. Быстрая серия
событий (5 файлов за 2 секунды) породит 5 задач, но 4 из них выйдут no-op.

Статус операции отражается в `ImportSession.summary_json["transfer_match"]`:

    {
      "status": "pending" | "running" | "ready" | "failed",
      "queued_at": iso,
      "started_at": iso | null,
      "finished_at": iso | null,
      "error": str | null,
    }

Фронт использует этот статус для продолжения polling preview.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import redis

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.db import SessionLocal
# Eagerly load every ORM model (see note in moderate_import_session.py).
import app.models  # noqa: F401

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 3
TOKEN_TTL_SECONDS = 30

_redis_client_singleton: redis.Redis | None = None


def _redis_client() -> redis.Redis:
    global _redis_client_singleton
    if _redis_client_singleton is None:
        _redis_client_singleton = redis.Redis.from_url(settings.REDIS_URL)
    return _redis_client_singleton


def _debounce_key(user_id: int) -> str:
    return f"tm:debounce:{user_id}"


def schedule_transfer_match(user_id: int) -> None:
    """Триггер debounced-матчинга для пользователя.

    Коалесценция: несколько вызовов в окне DEBOUNCE_SECONDS схлопываются
    в один реальный запуск матчера. Безопасно вызывать как из FastAPI
    request handler, так и из Celery-тасков — функция синхронная, публикует
    task через Celery broker и записывает token в Redis.
    """
    try:
        token = str(time.time_ns())
        client = _redis_client()
        client.set(_debounce_key(user_id), token, ex=TOKEN_TTL_SECONDS)
        _mark_sessions_pending(user_id)
        match_transfers_for_user_debounced.apply_async(
            args=[user_id, token],
            countdown=DEBOUNCE_SECONDS,
        )
    except Exception:
        logger.exception("schedule_transfer_match failed for user %s", user_id)


@celery_app.task(name="match_transfers_for_user_debounced")
def match_transfers_for_user_debounced(user_id: int, token: str) -> dict[str, Any]:
    """Запуск `TransferMatcherService.match_transfers_for_user` с token-check.

    Если в Redis лежит НЕ наш token — выходим как superseded. Иначе запускаем
    матчер, обновляем статус в `summary_json["transfer_match"]` всех активных
    сессий пользователя и удаляем token.
    """
    from app.services.transfer_matcher_service import TransferMatcherService

    try:
        client = _redis_client()
        current = client.get(_debounce_key(user_id))
        if current is None:
            return {"status": "superseded", "reason": "token expired"}
        current_token = current.decode() if isinstance(current, bytes) else str(current)
        if current_token != token:
            return {"status": "superseded", "reason": "newer token enqueued"}
    except Exception:
        logger.exception("redis token check failed for user %s — running matcher anyway", user_id)

    db = SessionLocal()
    try:
        _mark_sessions_status(db, user_id, status="running", started_at=_now_iso())
        db.commit()
        try:
            TransferMatcherService(db).match_transfers_for_user(user_id=user_id)
            db.commit()
            # spec §8.10 — Fee-aware suspect-pair second pass on leftovers.
            try:
                from app.services.fee_matcher_service import FeeMatcherService
                FeeMatcherService(db).detect_for_user(user_id=user_id)
                db.commit()
            except Exception:
                logger.exception("FeeMatcherService failed for user %s", user_id)
                db.rollback()
            _mark_sessions_status(db, user_id, status="ready", finished=True)
            db.commit()
        except Exception as exc:
            logger.exception("match_transfers_for_user_debounced failed for user %s", user_id)
            db.rollback()
            try:
                _mark_sessions_status(db, user_id, status="failed", finished=True, error=str(exc))
                db.commit()
            except Exception:
                db.rollback()
            return {"status": "failed", "error": str(exc)}
    finally:
        db.close()

    try:
        client = _redis_client()
        current = client.get(_debounce_key(user_id))
        if current is not None:
            current_token = current.decode() if isinstance(current, bytes) else str(current)
            if current_token == token:
                client.delete(_debounce_key(user_id))
    except Exception:
        logger.exception("redis cleanup failed for user %s", user_id)

    return {"status": "ok"}


def _mark_sessions_pending(user_id: int) -> None:
    """Optimistic флаг на момент постановки задачи в очередь (pending)."""
    db = SessionLocal()
    try:
        _mark_sessions_status(db, user_id, status="pending", queued_at=_now_iso())
        db.commit()
    except Exception:
        logger.exception("_mark_sessions_pending failed for user %s", user_id)
        db.rollback()
    finally:
        db.close()


def _mark_sessions_status(
    db,
    user_id: int,
    *,
    status: str,
    queued_at: str | None = None,
    started_at: str | None = None,
    finished: bool = False,
    error: str | None = None,
) -> None:
    """Пишет `summary_json["transfer_match"]` во все активные сессии пользователя."""
    from app.models.import_session import ImportSession

    sessions = (
        db.query(ImportSession)
        .filter(
            ImportSession.user_id == user_id,
            ImportSession.status.in_(["analyzed", "preview_ready"]),
        )
        .all()
    )
    for session in sessions:
        summary = dict(session.summary_json or {})
        current = dict(summary.get("transfer_match") or {})
        current["status"] = status
        if queued_at is not None:
            current["queued_at"] = queued_at
        if started_at is not None:
            current["started_at"] = started_at
        if finished:
            current["finished_at"] = _now_iso()
        if error is not None:
            current["error"] = error
        elif status in ("running", "pending", "ready"):
            current["error"] = None
        summary["transfer_match"] = current
        session.summary_json = summary
        db.add(session)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
