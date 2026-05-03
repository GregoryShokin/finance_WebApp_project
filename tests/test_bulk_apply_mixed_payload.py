"""Группа 8 (T29, T30) — bulk-confirm с разными полями в одном payload.

Базовый сценарий "одна категория на 5 рои" уже покрыт в
`test_bulk_apply_orchestrator_e2e.py::test_bulk_apply_creates_rule_with_full_confirms_delta`.
Здесь — производные сценарии:

  • T29 расширение: bulk-apply на кластере смешанного типа (категория +
    counterparty + operation_type), все три поля проставляются на каждой
    строке.
  • T30: разные category_id в одном payload (маркетплейс-кейс) →
    создаётся столько правил, сколько уникальных (fingerprint, category)
    пар.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

import app.models.counterparty_identifier  # noqa: F401  — поднять таблицу

from app.models.category import Category
from app.models.counterparty import Counterparty
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.transaction_category_rule import TransactionCategoryRule
from app.schemas.imports import BulkApplyRequest, BulkClusterRowUpdate
from app.services.import_normalizer_v2 import (
    extract_tokens,
    fingerprint as compute_fingerprint,
    normalize_skeleton,
    pick_transfer_identifier,
)
from app.services.import_service import ImportService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_session(db, user) -> ImportSession:
    s = ImportSession(
        user_id=user.id, filename="t.csv",
        source_type="csv", status="preview_ready",
        file_content="", detected_columns=[],
        parse_settings={}, mapping_json={"bank_code": "tinkoff"},
        summary_json={},
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


def _make_row(
    db, session, *, row_index: int, description: str,
    direction: str = "expense", account_id: int = 1,
):
    tokens = extract_tokens(description)
    skeleton = normalize_skeleton(description, tokens)
    fp = compute_fingerprint(
        bank="tinkoff", account_id=account_id, direction=direction,
        skeleton=skeleton, contract=tokens.contract,
        transfer_identifier=pick_transfer_identifier(tokens),
    )
    payload = {
        "amount": "100.00",
        "direction": direction, "type": direction,
        "description": description,
        "import_original_description": description,
        "skeleton": skeleton,
        "tokens": {
            "phone": tokens.phone, "contract": tokens.contract,
            "card": tokens.card, "iban": tokens.iban,
        },
        "fingerprint": fp, "bank_code": "tinkoff",
        "normalizer_version": 2, "operation_type": "regular",
        "transaction_date": datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc).isoformat(),
    }
    row = ImportRow(
        session_id=session.id, row_index=row_index,
        raw_data_json={}, normalized_data_json=payload,
        status="ready",
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


@pytest.fixture
def counterparty(db, user):
    cp = Counterparty(user_id=user.id, name="Озон")
    db.add(cp); db.commit(); db.refresh(cp)
    return cp


def _category(db, user, name, kind="expense", priority="expense_secondary"):
    cat = Category(
        user_id=user.id, name=name, kind=kind, priority=priority,
        regularity="regular", is_system=False, icon_name="tag", color="#fff",
    )
    db.add(cat); db.commit(); db.refresh(cat)
    return cat


# ---------------------------------------------------------------------------
# T29 — bulk-edit нескольких полей одновременно
# ---------------------------------------------------------------------------


def test_bulk_apply_sets_category_and_counterparty_on_every_row(
    db, user, counterparty
):
    cat = _category(db, user, "Маркетплейсы")
    session = _make_session(db, user)
    rows = [
        _make_row(db, session, row_index=i,
                  description="Озон Маркетплейс заказ")
        for i in range(3)
    ]

    request = BulkApplyRequest(
        cluster_key=rows[0].normalized_data_json["fingerprint"],
        cluster_type="fingerprint",
        updates=[
            BulkClusterRowUpdate(
                row_id=r.id, operation_type="regular",
                category_id=cat.id, counterparty_id=counterparty.id,
            )
            for r in rows
        ],
    )
    ImportService(db).bulk_apply_cluster(
        user_id=user.id, session_id=session.id, payload=request,
    )

    for r in rows:
        db.refresh(r)
        nd = r.normalized_data_json or {}
        assert nd.get("category_id") == cat.id
        assert nd.get("counterparty_id") == counterparty.id
        assert nd.get("operation_type") == "regular"


# ---------------------------------------------------------------------------
# T30 — маркетплейс-кейс: разные категории в одном payload
# ---------------------------------------------------------------------------


def test_bulk_apply_with_two_categories_creates_two_rules(db, user, counterparty):
    """Маркетплейс-кейс из bulk_apply_orchestrator: пользователь в одном
    bulk-payload может назначить разные категории разным rows. Контракт:
    создаётся столько правил, сколько уникальных (fingerprint, category)
    пар. Все рои здесь имеют один fingerprint, но 2 разные категории →
    2 правила."""
    cat_groceries = _category(db, user, "Продукты", priority="expense_essential")
    cat_other = _category(db, user, "Маркетплейсы", priority="expense_secondary")
    session = _make_session(db, user)
    rows = [
        _make_row(db, session, row_index=i, description="Озон Маркетплейс заказ")
        for i in range(4)
    ]

    request = BulkApplyRequest(
        cluster_key=rows[0].normalized_data_json["fingerprint"],
        cluster_type="fingerprint",
        updates=[
            # 2 рои в Продукты, 2 в Маркетплейсы — всё в одном payload.
            BulkClusterRowUpdate(
                row_id=rows[0].id, operation_type="regular",
                category_id=cat_groceries.id, counterparty_id=counterparty.id,
            ),
            BulkClusterRowUpdate(
                row_id=rows[1].id, operation_type="regular",
                category_id=cat_groceries.id, counterparty_id=counterparty.id,
            ),
            BulkClusterRowUpdate(
                row_id=rows[2].id, operation_type="regular",
                category_id=cat_other.id, counterparty_id=counterparty.id,
            ),
            BulkClusterRowUpdate(
                row_id=rows[3].id, operation_type="regular",
                category_id=cat_other.id, counterparty_id=counterparty.id,
            ),
        ],
    )
    result = ImportService(db).bulk_apply_cluster(
        user_id=user.id, session_id=session.id, payload=request,
    )
    assert result["confirmed_count"] == 4
    assert result["rules_affected"] == 2, "Один fingerprint × 2 категории → 2 правила"

    rules = db.query(TransactionCategoryRule).filter(
        TransactionCategoryRule.user_id == user.id,
    ).all()
    cat_ids_in_rules = {r.category_id for r in rules}
    assert cat_ids_in_rules == {cat_groceries.id, cat_other.id}


def test_bulk_apply_skips_rule_creation_for_transfer_rows(db, user, counterparty):
    """Transfer-рои без category_id в payload → правило не создаётся
    (правило категории не применимо к трансферу), но fingerprint binding
    к counterparty всё равно создаётся."""
    session = _make_session(db, user)
    row = _make_row(
        db, session, row_index=0,
        description="Внешний перевод по номеру телефона +79161234567",
    )
    request = BulkApplyRequest(
        cluster_key=row.normalized_data_json["fingerprint"],
        cluster_type="fingerprint",
        updates=[BulkClusterRowUpdate(
            row_id=row.id, operation_type="transfer",
            category_id=None, counterparty_id=counterparty.id,
        )],
    )
    result = ImportService(db).bulk_apply_cluster(
        user_id=user.id, session_id=session.id, payload=request,
    )
    assert result["confirmed_count"] == 1
    assert result["rules_affected"] == 0

    rules = db.query(TransactionCategoryRule).filter(
        TransactionCategoryRule.user_id == user.id,
    ).count()
    assert rules == 0
