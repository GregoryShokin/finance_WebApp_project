"""Группа 2 (T6, T7, T9, T10) — категоризация и rules.

  • T6 — `_resolve_category` извлекает категорию из истории похожих
    транзакций (majority vote).
  • T7 — `set_row_label` создаёт `TransactionCategoryRule` с `user_label`,
    skeleton'ом строки и категорией. Повторный вызов — upsert.
  • T9 — `_resolve_category(skip_llm=True)` НЕ дёргает LLM сервис, даже
    если он включён. С `skip_llm=False` и enabled-LLM — вызывает.
  • T10 — `set_row_label` отказывается от системной категории /
    отсутствующего норм-описания / трансфера.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.models.category import Category
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.transaction import Transaction
from app.models.transaction_category_rule import TransactionCategoryRule
from app.services.import_service import (
    ImportService,
    ImportValidationError,
)
from app.services.transaction_enrichment_service import TransactionEnrichmentService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def grocery_category(db, user) -> Category:
    cat = Category(
        user_id=user.id, name="Продукты",
        kind="expense", priority="expense_essential", regularity="regular",
        is_system=False, icon_name="shopping-basket", color="#16a34a",
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@pytest.fixture
def cafe_category(db, user) -> Category:
    cat = Category(
        user_id=user.id, name="Кафе и рестораны",
        kind="expense", priority="expense_secondary", regularity="regular",
        is_system=False, icon_name="utensils-crossed", color="#ea580c",
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def _seed_history_tx(
    db, user, account, *, count: int, category: Category, normalized_desc: str,
):
    """Сидируем `count` похожих расходных транзакций в одну категорию."""
    for i in range(count):
        tx = Transaction(
            user_id=user.id, account_id=account.id,
            type="expense", operation_type="regular",
            amount=Decimal("500.00"), currency="RUB",
            category_id=category.id,
            description=f"Пятёрочка ул.Ленина {i}",
            normalized_description=normalized_desc,
            transaction_date=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
        )
        db.add(tx)
    db.commit()


def _make_session(db, user) -> ImportSession:
    s = ImportSession(
        user_id=user.id, filename="t.csv",
        source_type="csv", status="preview_ready",
        file_content="", detected_columns=[],
        parse_settings={}, mapping_json={}, summary_json={},
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# T6 — категория из истории
# ---------------------------------------------------------------------------


def test_resolve_category_picks_dominant_from_history(
    db, user, regular_account, grocery_category, cafe_category
):
    """T6: 3 истории расходов в Продукты + 1 в Кафе → majority vote отдаёт
    Продукты. Передаём history-sample напрямую (как делает
    `enrich_import_row` через `history_sample_cache`)."""
    _seed_history_tx(
        db, user, regular_account, count=3, category=grocery_category,
        normalized_desc="пятёрочка ул ленина",
    )
    _seed_history_tx(
        db, user, regular_account, count=1, category=cafe_category,
        normalized_desc="пятёрочка ул ленина",
    )

    history = (
        db.query(Transaction)
        .filter(Transaction.user_id == user.id)
        .all()
    )
    assert len(history) == 4

    service = TransactionEnrichmentService(db)
    cat_id, confidence, reason = service._resolve_category(
        categories=service.category_repo.list(user_id=user.id),
        history=history,
        normalized_description="пятёрочка ул ленина",
        operation_type="regular",
        transaction_type="expense",
        description="Пятёрочка ул.Ленина 5",
        counterparty="",
        skip_llm=True,
    )
    assert cat_id == grocery_category.id, (
        "Должна победить категория с большим числом совпадений"
    )
    assert confidence > 0.9
    assert "истории" in reason.lower()


def test_resolve_category_returns_none_when_history_empty(
    db, user, grocery_category
):
    """Без истории и keyword'ов — категории не подобрать (skip_llm)."""
    service = TransactionEnrichmentService(db)
    cat_id, confidence, reason = service._resolve_category(
        categories=[grocery_category],
        history=[],
        normalized_description="случайное описание xyz",
        operation_type="regular",
        transaction_type="expense",
        description="случайное описание xyz",
        counterparty="",
        skip_llm=True,
    )
    assert cat_id is None
    assert confidence == 0.0


def test_resolve_category_skips_for_transfer(db, user, grocery_category):
    """Трансфер не нуждается в категории — короткое замыкание."""
    service = TransactionEnrichmentService(db)
    cat_id, _, _ = service._resolve_category(
        categories=[grocery_category],
        history=[],
        normalized_description="перевод",
        operation_type="transfer",
        transaction_type="expense",
        description="перевод",
        counterparty="",
        skip_llm=True,
    )
    assert cat_id is None


# ---------------------------------------------------------------------------
# T9 — LLM gate
# ---------------------------------------------------------------------------


def test_resolve_category_with_skip_llm_does_not_call_llm(
    db, user, grocery_category
):
    """Контракт `skip_llm=True`: LLM не вызывается даже если is_enabled=True."""
    service = TransactionEnrichmentService(db)
    # Подменяем provider на mock с is_enabled=True.
    fake_llm = MagicMock()
    fake_llm.is_enabled = True
    fake_llm.classify_transaction_category = MagicMock(
        return_value=(grocery_category.id, 0.9, "from_llm")
    )
    service.llm_service = fake_llm

    service._resolve_category(
        categories=[grocery_category], history=[],
        normalized_description="random", operation_type="regular",
        transaction_type="expense", description="random",
        counterparty="", skip_llm=True,
    )

    fake_llm.classify_transaction_category.assert_not_called()


def test_resolve_category_with_skip_llm_false_calls_llm_when_enabled(
    db, user, grocery_category
):
    """Контракт `skip_llm=False` + LLM enabled → вызов классификации."""
    service = TransactionEnrichmentService(db)
    fake_llm = MagicMock()
    fake_llm.is_enabled = True
    fake_llm.classify_transaction_category = MagicMock(
        return_value=(grocery_category.id, 0.9, "from_llm")
    )
    service.llm_service = fake_llm

    cat_id, _, reason = service._resolve_category(
        categories=[grocery_category], history=[],
        normalized_description="random unmatched", operation_type="regular",
        transaction_type="expense", description="random unmatched",
        counterparty="", skip_llm=False,
    )
    assert cat_id == grocery_category.id
    assert reason == "from_llm"
    fake_llm.classify_transaction_category.assert_called_once()


def test_resolve_category_does_not_call_llm_when_disabled(
    db, user, grocery_category
):
    """LLM disabled → вызова нет, даже если skip_llm=False."""
    service = TransactionEnrichmentService(db)
    fake_llm = MagicMock()
    fake_llm.is_enabled = False
    fake_llm.classify_transaction_category = MagicMock()
    service.llm_service = fake_llm

    service._resolve_category(
        categories=[grocery_category], history=[],
        normalized_description="random", operation_type="regular",
        transaction_type="expense", description="random",
        counterparty="", skip_llm=False,
    )
    fake_llm.classify_transaction_category.assert_not_called()


def test_enrich_import_row_default_skip_llm_is_true(
    db, user, regular_account, grocery_category
):
    """Контракт enrich_import_row: по умолчанию skip_llm=True
    (preview-фаза не платит LLM-токенами)."""
    service = TransactionEnrichmentService(db)
    fake_llm = MagicMock()
    fake_llm.is_enabled = True
    fake_llm.classify_transaction_category = MagicMock(
        return_value=(None, 0.0, "")
    )
    service.llm_service = fake_llm

    service.enrich_import_row(
        user_id=user.id,
        session_account_id=regular_account.id,
        normalized_payload={
            "description": "Random Merchant",
            "direction": "expense",
            "amount": "100",
            "type": "expense",
        },
    )
    fake_llm.classify_transaction_category.assert_not_called()


# ---------------------------------------------------------------------------
# T10 — set_row_label (save-as-rule)
# ---------------------------------------------------------------------------


def _make_row_with_normalized(db, session, **payload) -> ImportRow:
    row = ImportRow(
        session_id=session.id, row_index=0,
        raw_data_json={}, normalized_data_json=payload,
        status="ready",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_set_row_label_creates_rule(db, user, grocery_category):
    """T10: set_row_label создаёт TransactionCategoryRule с user_label,
    skeleton'ом и категорией из normalized_data."""
    session = _make_session(db, user)
    row = _make_row_with_normalized(
        db, session,
        description="Пятёрочка ул.Ленина 5",
        normalized_description="пятёрочка ул ленина",
        skeleton="пятёрочка ул ленина",
        import_original_description="Пятёрочка ул.Ленина 5",
        category_id=grocery_category.id,
        operation_type="regular",
        amount="500.00",
        direction="expense",
    )

    result = ImportService(db).set_row_label(
        user_id=user.id, row_id=row.id, user_label="Магазин Пятёрочка",
    )
    assert result["category_id"] == grocery_category.id
    assert result["user_label"] == "Магазин Пятёрочка"

    rule = db.query(TransactionCategoryRule).filter(
        TransactionCategoryRule.id == result["rule_id"],
    ).first()
    assert rule is not None
    assert rule.normalized_description == "пятёрочка ул ленина"
    assert rule.category_id == grocery_category.id
    assert rule.user_label == "Магазин Пятёрочка"


def test_set_row_label_is_upsert(db, user, grocery_category):
    """Повторный вызов с теми же скелетоном+категорией обновляет user_label."""
    session = _make_session(db, user)
    row = _make_row_with_normalized(
        db, session,
        description="Пятёрочка",
        normalized_description="пятёрочка",
        skeleton="пятёрочка",
        category_id=grocery_category.id,
        operation_type="regular",
        amount="500.00", direction="expense",
    )
    svc = ImportService(db)
    first = svc.set_row_label(user_id=user.id, row_id=row.id, user_label="A")
    second = svc.set_row_label(user_id=user.id, row_id=row.id, user_label="B")

    assert first["rule_id"] == second["rule_id"]
    rule = db.query(TransactionCategoryRule).filter(
        TransactionCategoryRule.id == first["rule_id"],
    ).first()
    assert rule.user_label == "B"

    rules_count = db.query(TransactionCategoryRule).filter(
        TransactionCategoryRule.user_id == user.id,
    ).count()
    assert rules_count == 1, "Дубликат правила создаваться не должен"


def test_set_row_label_rejects_row_without_category(db, user):
    """T10 контракт: без category_id правило создавать не из чего."""
    session = _make_session(db, user)
    row = _make_row_with_normalized(
        db, session,
        description="x", normalized_description="x",
        skeleton="x", operation_type="regular",
        amount="100", direction="expense",
        # без category_id
    )
    with pytest.raises(ImportValidationError) as exc:
        ImportService(db).set_row_label(
            user_id=user.id, row_id=row.id, user_label="L",
        )
    assert "категори" in str(exc.value).lower()


def test_set_row_label_rejects_transfer_row(db, user, grocery_category):
    """Для трансфера правило категории не применимо — должно отвергаться."""
    session = _make_session(db, user)
    row = _make_row_with_normalized(
        db, session,
        description="Перевод", normalized_description="перевод",
        skeleton="перевод", operation_type="transfer",
        amount="100", direction="expense",
        category_id=grocery_category.id,
    )
    with pytest.raises(ImportValidationError) as exc:
        ImportService(db).set_row_label(
            user_id=user.id, row_id=row.id, user_label="L",
        )
    assert "тип операции" in str(exc.value).lower() or "не применяется" in str(exc.value).lower()


def test_set_row_label_rejects_row_without_normalized_description(
    db, user, grocery_category
):
    """Без normalized_description правило не на что повесить."""
    session = _make_session(db, user)
    row = _make_row_with_normalized(
        db, session,
        description="x", skeleton="x",
        operation_type="regular",
        category_id=grocery_category.id,
        amount="100", direction="expense",
        # нет normalized_description
    )
    with pytest.raises(ImportValidationError) as exc:
        ImportService(db).set_row_label(
            user_id=user.id, row_id=row.id, user_label="L",
        )
    assert "норм" in str(exc.value).lower() or "описан" in str(exc.value).lower()
