"""T14 / T15 — `ImportPostProcessor.apply_refund_matches` end-to-end.

Чистый матчер уже покрыт в `test_refund_matcher.py`. Здесь проверяется
персистентность результата:

  • refund_match пишется в ImportRow.normalized_data_json НА ОБЕ стороны;
  • контракт payload'а: partner_row_id / partner_date / amount / confidence /
    reasons / side;
  • рои с operation_type='transfer' исключаются (refund и transfer — взаимно
    исключающие лейблы);
  • рои в терминальных статусах (duplicate / skipped / parked / committed /
    error) не попадают в кандидаты;
  • одинокий refund без оригинала не получает refund_match (T15).

Refund-связь хранится ТОЛЬКО на ImportRow — на Transaction нет колонки
refund_for_transaction_id (см. app/models/transaction.py). На коммите эта
связь теряется; зафиксирована только сторона ImportRow.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.repositories.import_repository import ImportRepository
from app.services.import_post_processor import ImportPostProcessor


def _make_session(db, user) -> ImportSession:
    session = ImportSession(
        user_id=user.id,
        filename="t.csv",
        source_type="csv",
        status="preview_ready",
        file_content="",
        detected_columns=[],
        parse_settings={},
        mapping_json={},
        summary_json={},
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _make_row(
    db,
    session: ImportSession,
    *,
    row_index: int,
    direction: str,
    amount: str,
    transaction_date: datetime,
    description: str = "",
    skeleton: str = "",
    tokens: dict | None = None,
    status: str = "ready",
    operation_type: str | None = None,
) -> ImportRow:
    normalized = {
        "amount": amount,
        "direction": direction,
        "transaction_date": transaction_date.isoformat(),
        "description": description,
        "skeleton": skeleton,
        "tokens": tokens or {},
    }
    if operation_type is not None:
        normalized["operation_type"] = operation_type
    row = ImportRow(
        session_id=session.id,
        row_index=row_index,
        raw_data_json={},
        normalized_data_json=normalized,
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _run(db, session: ImportSession) -> None:
    repo = ImportRepository(db)
    ImportPostProcessor(db, import_repo=repo).apply_refund_matches(session_id=session.id)
    db.commit()


def test_stamps_refund_match_on_both_rows(db, user):
    session = _make_session(db, user)
    purchase_dt = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    refund_dt = purchase_dt + timedelta(days=2)

    expense = _make_row(
        db, session, row_index=0,
        direction="expense", amount="1500.00",
        transaction_date=purchase_dt,
        description="Оплата в Pyaterochka",
        skeleton="оплата в pyaterochka",
    )
    income = _make_row(
        db, session, row_index=1,
        direction="income", amount="1500.00",
        transaction_date=refund_dt,
        description="Возврат в Pyaterochka",
        skeleton="возврат в pyaterochka",
    )

    _run(db, session)
    db.refresh(expense)
    db.refresh(income)

    exp_match = (expense.normalized_data_json or {}).get("refund_match")
    inc_match = (income.normalized_data_json or {}).get("refund_match")

    assert exp_match is not None
    assert inc_match is not None

    assert exp_match["partner_row_id"] == income.id
    assert inc_match["partner_row_id"] == expense.id
    assert exp_match["side"] == "expense"
    assert inc_match["side"] == "income"
    assert exp_match["amount"] == "1500.00"
    assert inc_match["amount"] == "1500.00"
    assert exp_match["confidence"] >= 0.6
    assert inc_match["confidence"] >= 0.6
    assert isinstance(exp_match["reasons"], list) and exp_match["reasons"]
    assert isinstance(inc_match["reasons"], list) and inc_match["reasons"]


def test_skips_transfer_rows(db, user):
    session = _make_session(db, user)
    purchase_dt = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)

    transfer_row = _make_row(
        db, session, row_index=0,
        direction="expense", amount="1500.00",
        transaction_date=purchase_dt,
        description="Перевод между своими счетами",
        skeleton="<PHONE>",
        tokens={"phone": "+79161234567"},
        operation_type="transfer",
    )
    refund_row = _make_row(
        db, session, row_index=1,
        direction="income", amount="1500.00",
        transaction_date=purchase_dt + timedelta(days=1),
        description="Возврат в Pyaterochka",
        skeleton="возврат в pyaterochka",
    )

    _run(db, session)
    db.refresh(transfer_row)
    db.refresh(refund_row)

    assert "refund_match" not in (transfer_row.normalized_data_json or {})
    assert "refund_match" not in (refund_row.normalized_data_json or {}), (
        "Без партнёра для матча refund-связь записываться не должна"
    )


def test_skips_terminal_status_rows(db, user):
    session = _make_session(db, user)
    purchase_dt = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)

    parked_expense = _make_row(
        db, session, row_index=0,
        direction="expense", amount="1500.00",
        transaction_date=purchase_dt,
        description="Оплата в Pyaterochka",
        skeleton="оплата в pyaterochka",
        status="parked",
    )
    refund = _make_row(
        db, session, row_index=1,
        direction="income", amount="1500.00",
        transaction_date=purchase_dt + timedelta(days=1),
        description="Возврат в Pyaterochka",
        skeleton="возврат в pyaterochka",
    )

    _run(db, session)
    db.refresh(parked_expense)
    db.refresh(refund)

    assert "refund_match" not in (parked_expense.normalized_data_json or {})
    assert "refund_match" not in (refund.normalized_data_json or {})


def test_lone_refund_without_origin_gets_no_match(db, user):
    """T15 — refund без покупки в окне ±14 дней: refund_match не появляется."""
    session = _make_session(db, user)
    refund_dt = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)

    lone_refund = _make_row(
        db, session, row_index=0,
        direction="income", amount="999.00",
        transaction_date=refund_dt,
        description="Возврат NEVERSEEN",
        skeleton="возврат neverseen",
    )

    _run(db, session)
    db.refresh(lone_refund)

    assert "refund_match" not in (lone_refund.normalized_data_json or {})


def test_pair_with_low_confidence_is_not_persisted(db, user):
    """T15 регрессия: refund-keyword без brand-match → confidence 0.50 → MIN_CONFIDENCE
    не пройден → пара не эмитится → refund_match не пишется ни на одну сторону."""
    session = _make_session(db, user)
    purchase_dt = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    refund_dt = purchase_dt + timedelta(days=1)

    expense = _make_row(
        db, session, row_index=0,
        direction="expense", amount="700.00",
        transaction_date=purchase_dt,
        description="Оплата в POPLAVO Volgodonsk RUS",
        skeleton="оплата в poplavo volgodonsk rus",
    )
    refund = _make_row(
        db, session, row_index=1,
        direction="income", amount="700.00",
        transaction_date=refund_dt,
        description="Отмена операции оплаты KOFEMOLOKO Volgodonsk RUS",
        skeleton="отмена операции оплаты kofemoloko volgodonsk rus",
    )

    _run(db, session)
    db.refresh(expense)
    db.refresh(refund)

    assert "refund_match" not in (expense.normalized_data_json or {})
    assert "refund_match" not in (refund.normalized_data_json or {})
