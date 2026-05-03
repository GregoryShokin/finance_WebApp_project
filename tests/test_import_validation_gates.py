"""Группа 5 (T16–T18) — гейты валидации импорта.

  • T16 — `gate_transfer_integrity(final=True)` блокирует трансфер без
    target_account_id (поднимает status в `error`).
  • T17 — `_find_duplicate` детектит совпадение skeleton+amount+account+
    date в окне ±1 день; `find_transfer_pair_duplicate` находит парный
    трансфер.
  • T18 — gate ловит self-loop transfer (account_id == target_account_id):
    выдаёт сообщение «на тот же счёт».
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.transaction import Transaction
from app.services.import_post_processor import ImportPostProcessor


# ---------------------------------------------------------------------------
# T16 — transfer integrity gate
# ---------------------------------------------------------------------------


def test_gate_transfer_without_target_warning_in_preview_phase():
    """Без `final` (фаза preview, ещё до cross-session matcher'а) gate
    переводит в warning, не в error — matcher должен иметь шанс найти пару."""
    normalized = {
        "operation_type": "transfer",
        "type": "expense",
        "account_id": 1,
        "target_account_id": None,
    }
    status, issues = ImportPostProcessor.gate_transfer_integrity(
        normalized=normalized, current_status="ready", issues=[], final=False,
    )
    assert status == "warning"
    assert any("счёт получателя" in m or "счёт отправителя" in m for m in issues)


def test_gate_transfer_without_target_error_when_final():
    """final=True — фаза commit / post-matcher: трансфер без target → error."""
    normalized = {
        "operation_type": "transfer",
        "type": "expense",
        "account_id": 1,
        "target_account_id": None,
    }
    status, issues = ImportPostProcessor.gate_transfer_integrity(
        normalized=normalized, current_status="warning", issues=[], final=True,
    )
    assert status == "error"


def test_gate_transfer_does_not_touch_non_transfer_rows():
    """regular-операция не должна трогаться gate'ом независимо от target."""
    normalized = {"operation_type": "regular", "type": "expense", "account_id": 1}
    status, issues = ImportPostProcessor.gate_transfer_integrity(
        normalized=normalized, current_status="ready", issues=[], final=True,
    )
    assert status == "ready"
    assert issues == []


# ---------------------------------------------------------------------------
# T18 — same-account self-loop transfer rejection
# ---------------------------------------------------------------------------


def test_gate_rejects_transfer_self_loop():
    """T18: `account_id == target_account_id` для transfer → ошибка
    «Перевод указан на тот же счёт»."""
    normalized = {
        "operation_type": "transfer",
        "type": "expense",
        "account_id": 7,
        "target_account_id": 7,
    }
    status, issues = ImportPostProcessor.gate_transfer_integrity(
        normalized=normalized, current_status="ready", issues=[], final=True,
    )
    assert status == "error"
    assert any("тот же счёт" in m for m in issues)


def test_gate_does_not_downgrade_existing_error_status():
    """Контракт: terminal `error` не понижается в warning, даже если
    проблема всё ещё есть и final=False."""
    normalized = {
        "operation_type": "transfer",
        "type": "expense",
        "account_id": 1,
        "target_account_id": None,
    }
    status, issues = ImportPostProcessor.gate_transfer_integrity(
        normalized=normalized, current_status="error", issues=["prior"], final=False,
    )
    assert status == "error"


def test_gate_does_not_downgrade_duplicate_status():
    """`duplicate` тоже terminal — gate не меняет статус."""
    normalized = {
        "operation_type": "transfer",
        "type": "expense",
        "account_id": 1,
        "target_account_id": None,
    }
    status, _ = ImportPostProcessor.gate_transfer_integrity(
        normalized=normalized, current_status="duplicate", issues=[], final=True,
    )
    assert status == "duplicate"


# ---------------------------------------------------------------------------
# T17 — dedup against committed transactions
# ---------------------------------------------------------------------------


def _seed_tx(db, *, account_id: int, user_id: int, amount: str, date: datetime,
             skeleton: str, normalized_description: str = "ozon",
             tx_type: str = "expense"):
    tx = Transaction(
        user_id=user_id, account_id=account_id,
        type=tx_type, operation_type="regular",
        amount=Decimal(amount), currency="RUB",
        description="Оплата OZON",
        normalized_description=normalized_description,
        skeleton=skeleton,
        transaction_date=date,
    )
    db.add(tx)
    db.commit()
    return tx


def test_find_duplicate_strict_match_within_one_day(db, user, regular_account):
    """T17 strict: тот же account+amount+skeleton, дата ±1 день → duplicate."""
    from app.services.import_service import ImportService

    base_dt = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    _seed_tx(db, account_id=regular_account.id, user_id=user.id,
             amount="1500.00", date=base_dt, skeleton="ozon")

    svc = ImportService(db)

    # Тот же день — duplicate
    assert svc._find_duplicate(
        user_id=user.id, account_id=regular_account.id,
        amount=Decimal("1500.00"),
        transaction_date=base_dt,
        skeleton="ozon", normalized_description="ozon",
        transaction_type="expense",
    ) is True

    # +1 день — всё ещё duplicate (±1 день окно)
    assert svc._find_duplicate(
        user_id=user.id, account_id=regular_account.id,
        amount=Decimal("1500.00"),
        transaction_date=base_dt + timedelta(days=1),
        skeleton="ozon", normalized_description="ozon",
        transaction_type="expense",
    ) is True


def test_find_duplicate_misses_on_amount_or_skeleton_mismatch(
    db, user, regular_account
):
    """Mismatch по amount или skeleton → не дубликат."""
    from app.services.import_service import ImportService

    base_dt = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    _seed_tx(db, account_id=regular_account.id, user_id=user.id,
             amount="1500.00", date=base_dt, skeleton="ozon")

    svc = ImportService(db)

    # Другой amount
    assert svc._find_duplicate(
        user_id=user.id, account_id=regular_account.id,
        amount=Decimal("1501.00"),
        transaction_date=base_dt,
        skeleton="ozon", normalized_description="ozon",
        transaction_type="expense",
    ) is False

    # Другой skeleton
    assert svc._find_duplicate(
        user_id=user.id, account_id=regular_account.id,
        amount=Decimal("1500.00"),
        transaction_date=base_dt,
        skeleton="pyaterochka", normalized_description="pyaterochka",
        transaction_type="expense",
    ) is False


def test_find_duplicate_outside_three_day_window_is_not_duplicate(
    db, user, regular_account
):
    """Вне ±3 дней (Level 2) — не дубликат, даже если skeleton совпадает."""
    from app.services.import_service import ImportService

    base_dt = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    _seed_tx(db, account_id=regular_account.id, user_id=user.id,
             amount="1500.00", date=base_dt, skeleton="ozon")

    svc = ImportService(db)
    assert svc._find_duplicate(
        user_id=user.id, account_id=regular_account.id,
        amount=Decimal("1500.00"),
        transaction_date=base_dt + timedelta(days=10),
        skeleton="ozon", normalized_description="ozon",
        transaction_type="expense",
    ) is False


def test_find_duplicate_filters_by_contract(db, user, regular_account):
    """Контракт-аккуратность: skeleton может быть один, но contract разный →
    не дубликат (защита от слипания трансферов на разные контракты)."""
    from app.services.import_service import ImportService

    base_dt = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    # Транзакция с контрактом 1234 в описании.
    _seed_tx(
        db, account_id=regular_account.id, user_id=user.id,
        amount="1500.00", date=base_dt,
        skeleton="<CONTRACT>",
    )
    # Перепишем description чтобы contract совпал.
    tx = db.query(Transaction).first()
    tx.description = "Внутрибанковский перевод по договору 1234"
    db.commit()

    svc = ImportService(db)

    # Запрос с другим контрактом — НЕ дубликат
    assert svc._find_duplicate(
        user_id=user.id, account_id=regular_account.id,
        amount=Decimal("1500.00"),
        transaction_date=base_dt,
        skeleton="<CONTRACT>", normalized_description="contract",
        transaction_type="expense",
        contract="9999",
    ) is False

    # Запрос с тем же контрактом — дубликат
    assert svc._find_duplicate(
        user_id=user.id, account_id=regular_account.id,
        amount=Decimal("1500.00"),
        transaction_date=base_dt,
        skeleton="<CONTRACT>", normalized_description="contract",
        transaction_type="expense",
        contract="1234",
    ) is True
