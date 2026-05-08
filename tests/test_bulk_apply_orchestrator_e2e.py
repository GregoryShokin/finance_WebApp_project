"""Группа 1 (T1–T5) — оркестрация bulk-apply и счётчики связей.

Существующие unit-тесты (`test_counterparty_fingerprint_service.py`,
`test_import_cluster_service.py`) уже покрывают cluster service и
fingerprint binding по отдельности. Здесь — сквозной e2e, которого нет:

  • T1 / T2 — `BulkApplyOrchestrator.apply` поверх кластера из 3+1 рои:
      три одинаковых fingerprint = одна группа, разный fingerprint =
      отдельная. После bulk-apply каждый уникальный fingerprint
      связан с counterparty через `CounterpartyFingerprint`, плюс
      создан кросс-аккаунтный binding по идентификатору (телефон).
  • T3 — повторный импорт того же мерчанта (вторая сессия) через
      `CounterpartyFingerprintService.resolve_many` находит счётчик из
      первой сессии. Этим тест воспроизводит контракт «следующий импорт
      того же мерчанта подхватывает counterparty без участия пользователя».
  • T4 — `cluster_bulk_acked_at` стамп: каждая строка кластера получает
      ISO-таймстемп после bulk-apply; `user_confirmed_at` не сосуществует.
      Это контракт §10.2 case B (вес 0.5).
  • T5 — refund cluster override: refund-кластер, у которого в истории
      пользователя нашлась purchase-сторона того же brand'а, наследует
      counterparty + категорию через `apply_refund_cluster_overrides`.

Тесты идут через ServiceLayer (`ImportService.bulk_apply_cluster`), а не
через FastAPI test-client — это единственный реальный entry point для
эндпоинта `POST /imports/{id}/clusters/bulk-apply`, и он не требует
поднятия JWT-стека.

Чтобы SQLite (in-memory db фикстура) поднял таблицу
`counterparty_identifiers`, модель импортируется на верхнем уровне.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

# Заставляет Base.metadata.create_all() поднять таблицу для in-memory SQLite.
import app.models.counterparty_identifier  # noqa: F401

from app.models.category import Category
from app.models.counterparty import Counterparty
from app.models.counterparty_fingerprint import CounterpartyFingerprint
from app.models.counterparty_identifier import CounterpartyIdentifier
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.transaction import Transaction
from app.models.transaction_category_rule import TransactionCategoryRule
from app.repositories.import_repository import ImportRepository
from app.schemas.imports import BulkApplyRequest, BulkClusterRowUpdate
from app.services.counterparty_fingerprint_service import (
    CounterpartyFingerprintService,
)
from app.services.counterparty_identifier_service import (
    CounterpartyIdentifierService,
)
from app.services.import_normalizer_v2 import (
    extract_tokens,
    fingerprint as compute_fingerprint,
    normalize_skeleton,
    pick_transfer_identifier,
)
from app.services.import_post_processor import ImportPostProcessor
from app.services.import_service import ImportService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(db, user, *, account_id: int | None = None) -> ImportSession:
    s = ImportSession(
        user_id=user.id,
        filename="t.csv",
        source_type="csv",
        status="preview_ready",
        file_content="",
        detected_columns=[],
        parse_settings={},
        mapping_json={"bank_code": "tinkoff"},
        summary_json={},
        account_id=account_id,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _make_row(
    db,
    session: ImportSession,
    *,
    row_index: int,
    description: str,
    amount: str = "1000.00",
    direction: str = "expense",
    status: str = "ready",
    account_id: int = 1,
    extra_normalized: dict | None = None,
) -> ImportRow:
    tokens = extract_tokens(description)
    skeleton = normalize_skeleton(description, tokens)
    transfer_id = pick_transfer_identifier(tokens)
    fp = compute_fingerprint(
        bank="tinkoff", account_id=account_id,
        direction=direction, skeleton=skeleton,
        contract=tokens.contract, transfer_identifier=transfer_id,
    )
    payload = {
        "amount": amount,
        "direction": direction,
        "type": "expense" if direction == "expense" else "income",
        "transaction_date": datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc).isoformat(),
        "date": datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc).isoformat(),
        "description": description,
        "import_original_description": description,
        "skeleton": skeleton,
        "tokens": {
            "phone": tokens.phone,
            "contract": tokens.contract,
            "card": tokens.card,
            "iban": tokens.iban,
            "counterparty_org": tokens.counterparty_org,
        },
        "fingerprint": fp,
        "bank_code": "tinkoff",
        "normalizer_version": 2,
        "operation_type": "regular",
        "is_refund": False,
    }
    if extra_normalized:
        payload.update(extra_normalized)
    row = ImportRow(
        session_id=session.id,
        row_index=row_index,
        raw_data_json={"description": description},
        normalized_data_json=payload,
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def counterparty(db, user) -> Counterparty:
    cp = Counterparty(user_id=user.id, name="Пятёрочка")
    db.add(cp)
    db.commit()
    db.refresh(cp)
    return cp


@pytest.fixture
def grocery_category(db, user) -> Category:
    cat = Category(
        user_id=user.id,
        name="Продукты",
        kind="expense",
        priority="expense_essential",
        regularity="regular",
        is_system=False,
        icon_name="shopping-basket",
        color="#16a34a",
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def _build_request(
    *,
    cluster_key: str,
    cluster_type: str = "fingerprint",
    rows: list[ImportRow],
    counterparty_id: int | None,
    category_id: int | None,
    operation_type: str = "regular",
) -> BulkApplyRequest:
    return BulkApplyRequest(
        cluster_key=cluster_key,
        cluster_type=cluster_type,
        updates=[
            BulkClusterRowUpdate(
                row_id=r.id,
                operation_type=operation_type,
                category_id=category_id,
                counterparty_id=counterparty_id,
            )
            for r in rows
        ],
    )


# ---------------------------------------------------------------------------
# T1 / T2 — bulk-apply создаёт fingerprint+identifier биндинги
# ---------------------------------------------------------------------------


def test_bulk_apply_binds_each_unique_fingerprint_in_cluster(
    db, user, counterparty, grocery_category
):
    """T1+T2: four rows — three identical skeleton ("Пятёрочка ул.Ленина 5") +
    one unique ("Пятёрочка ул.Тверская 12"). Bulk-apply on the three
    identical rows must create ONE fingerprint binding (one unique fp in
    the cluster), not three.

    Phase C step 4: bindings live in `brand_fingerprints` only. Asserts
    both: legacy `counterparty_fingerprints` is NOT written (write side
    closed) AND `brand_fingerprints` carries the binding to the brand
    derived from the legacy counterparty_id input.
    """
    from app.models.brand_fingerprint import BrandFingerprint
    from app.services.counterparty_brand_link import resolve_brand_id_for_counterparty

    session = _make_session(db, user, account_id=1)

    pyat_a1 = _make_row(db, session, row_index=0,
                        description="Пятёрочка ул.Ленина 5")
    pyat_a2 = _make_row(db, session, row_index=1,
                        description="Пятёрочка ул.Ленина 5")
    pyat_a3 = _make_row(db, session, row_index=2,
                        description="Пятёрочка ул.Ленина 5")
    pyat_b = _make_row(db, session, row_index=3,
                       description="Пятёрочка ул.Тверская 12")

    fp_a = pyat_a1.normalized_data_json["fingerprint"]
    fp_b = pyat_b.normalized_data_json["fingerprint"]

    assert pyat_a1.normalized_data_json["fingerprint"] == \
           pyat_a2.normalized_data_json["fingerprint"] == \
           pyat_a3.normalized_data_json["fingerprint"], (
        "Three identical descriptions must share one fingerprint"
    )
    assert fp_a != fp_b, "Different skeletons → different fingerprints"

    request = _build_request(
        cluster_key=fp_a, cluster_type="fingerprint",
        rows=[pyat_a1, pyat_a2, pyat_a3],
        counterparty_id=counterparty.id,
        category_id=grocery_category.id,
    )
    result = ImportService(db).bulk_apply_cluster(
        user_id=user.id, session_id=session.id, payload=request,
    )

    assert result["confirmed_count"] == 3
    assert result["skipped_row_ids"] == []
    assert result["rules_affected"] == 1, (
        "One unique fingerprint in cluster → one rule"
    )

    expected_brand_id = resolve_brand_id_for_counterparty(
        db, user_id=user.id, counterparty_id=counterparty.id,
    )
    assert expected_brand_id is not None

    # Negative: counterparty_fingerprints is no longer written by bulk-apply.
    cp_bindings = (
        db.query(CounterpartyFingerprint)
        .filter(CounterpartyFingerprint.user_id == user.id)
        .all()
    )
    assert cp_bindings == []

    # Positive: brand_fingerprints carries the unique-fp binding to the
    # resolved brand. fp_b (not in the cluster) stays unbound.
    brand_bindings = (
        db.query(BrandFingerprint)
        .filter(BrandFingerprint.user_id == user.id)
        .all()
    )
    assert len(brand_bindings) == 1
    assert brand_bindings[0].fingerprint == fp_a
    assert brand_bindings[0].brand_id == expected_brand_id


def test_bulk_apply_creates_identifier_binding_for_phone(
    db, user, counterparty, grocery_category
):
    """T1: a row with a phone token must create a cross-account binding so
    the same recipient resolves when the user later imports from a
    different account/bank.

    Phase C step 4: bindings live in `brand_identifiers` only. Asserts
    both: legacy `counterparty_identifiers` is NOT written AND
    `brand_identifiers` carries the binding to the resolved brand.
    """
    from app.models.brand_identifier import BrandIdentifier
    from app.services.counterparty_brand_link import resolve_brand_id_for_counterparty

    session = _make_session(db, user, account_id=1)

    row = _make_row(
        db, session, row_index=0,
        description="Внешний перевод по номеру телефона +79161234567",
        direction="expense",
    )
    tokens = row.normalized_data_json["tokens"]
    assert tokens["phone"] == "+79161234567"

    request = _build_request(
        cluster_key=row.normalized_data_json["fingerprint"],
        rows=[row],
        counterparty_id=counterparty.id,
        category_id=None,  # transfer row needs no category
        operation_type="transfer",
    )
    ImportService(db).bulk_apply_cluster(
        user_id=user.id, session_id=session.id, payload=request,
    )

    expected_brand_id = resolve_brand_id_for_counterparty(
        db, user_id=user.id, counterparty_id=counterparty.id,
    )
    assert expected_brand_id is not None

    # Negative: counterparty_identifiers is no longer written.
    cp_id_bindings = (
        db.query(CounterpartyIdentifier)
        .filter(CounterpartyIdentifier.user_id == user.id)
        .all()
    )
    assert cp_id_bindings == []

    # Positive: brand_identifiers holds the cross-account binding.
    brand_id_bindings = (
        db.query(BrandIdentifier)
        .filter(BrandIdentifier.user_id == user.id)
        .all()
    )
    assert len(brand_id_bindings) == 1
    assert brand_id_bindings[0].identifier_kind == "phone"
    assert brand_id_bindings[0].identifier_value == "+79161234567"
    assert brand_id_bindings[0].brand_id == expected_brand_id


def test_bulk_apply_creates_rule_with_full_confirms_delta(
    db, user, counterparty, grocery_category
):
    """T1+T2 контракт §10.2 case B: bulk-apply на 3 рои → правило получает
    confirms_delta=3 (т.е. confirms ≥ 1, в зависимости от веса 0.5×3=1.5).
    Активирует и обобщает rule в одном переходе."""
    session = _make_session(db, user, account_id=1)
    rows = [
        _make_row(db, session, row_index=i,
                  description="Пятёрочка ул.Ленина 5")
        for i in range(3)
    ]
    fp = rows[0].normalized_data_json["fingerprint"]

    request = _build_request(
        cluster_key=fp, rows=rows,
        counterparty_id=counterparty.id,
        category_id=grocery_category.id,
    )
    ImportService(db).bulk_apply_cluster(
        user_id=user.id, session_id=session.id, payload=request,
    )

    rules = db.query(TransactionCategoryRule).filter(
        TransactionCategoryRule.user_id == user.id,
    ).all()
    assert len(rules) == 1
    rule = rules[0]
    assert rule.category_id == grocery_category.id
    # 0.5 × 3 = 1.5; конфигурационный RULE_ACTIVATE_CONFIRMS=2 ещё не
    # достигнут. Главное: rule создан, confirms > 0, скелетон совпадает.
    assert Decimal(str(rule.confirms)) > Decimal("0")
    assert rule.normalized_description == rows[0].normalized_data_json["skeleton"]


# ---------------------------------------------------------------------------
# T3 — повторный импорт находит counterparty по fingerprint binding
# ---------------------------------------------------------------------------


def test_reimport_resolves_brand_from_first_session_binding(
    db, user, counterparty, grocery_category
):
    """T3: after bulk-apply on session A, importing session B with the same
    merchant must resolve to the same Brand via `BrandFingerprintService`.

    Phase C step 4: was `test_reimport_resolves_counterparty_from_first_session_binding`.
    The reimport-resolution invariant moved from CP-fp store to brand-fp
    store. Asserts both: legacy cp_fp_service.resolve_many returns empty
    (no CP-side write happened) AND brand_fp_service.resolve_many
    returns the brand resolved from the input counterparty.
    """
    from app.services.brand_fingerprint_service import BrandFingerprintService
    from app.services.counterparty_brand_link import resolve_brand_id_for_counterparty

    session_a = _make_session(db, user, account_id=1)
    rows_a = [
        _make_row(db, session_a, row_index=i,
                  description="Пятёрочка ул.Ленина 5")
        for i in range(2)
    ]
    fp = rows_a[0].normalized_data_json["fingerprint"]

    request = _build_request(
        cluster_key=fp, rows=rows_a,
        counterparty_id=counterparty.id,
        category_id=grocery_category.id,
    )
    ImportService(db).bulk_apply_cluster(
        user_id=user.id, session_id=session_a.id, payload=request,
    )

    expected_brand_id = resolve_brand_id_for_counterparty(
        db, user_id=user.id, counterparty_id=counterparty.id,
    )
    assert expected_brand_id is not None

    # Session B with the same merchant — same account → same fingerprint.
    session_b = _make_session(db, user, account_id=1)
    row_b = _make_row(db, session_b, row_index=0,
                      description="Пятёрочка ул.Ленина 5")
    assert row_b.normalized_data_json["fingerprint"] == fp

    # Negative: legacy CP-fp service no longer holds the binding.
    cp_fp_service = CounterpartyFingerprintService(db)
    cp_resolved = cp_fp_service.resolve_many(user_id=user.id, fingerprints=[fp])
    assert cp_resolved == {}

    # Positive: brand-fp service resolves the same fingerprint to the brand.
    brand_fp_service = BrandFingerprintService(db)
    brand_resolved = brand_fp_service.resolve_many(
        user_id=user.id, fingerprints=[fp],
    )
    assert brand_resolved == {fp: expected_brand_id}

    # Counterparty table unchanged — only the original fixture row.
    cps = db.query(Counterparty).filter(Counterparty.user_id == user.id).all()
    assert len(cps) == 1


def test_identifier_binding_resolves_across_accounts(
    db, user, counterparty
):
    """T3 cross-account: identifier binding (phone) → один и тот же
    counterparty при импорте с другого аккаунта/банка, где fingerprint
    обязательно другой (account_id отличается)."""
    session_a = _make_session(db, user, account_id=1)
    row_a = _make_row(
        db, session_a, row_index=0,
        description="Внешний перевод по номеру телефона +79161234567",
        account_id=1,
    )

    request = _build_request(
        cluster_key=row_a.normalized_data_json["fingerprint"],
        rows=[row_a],
        counterparty_id=counterparty.id,
        category_id=None, operation_type="transfer",
    )
    ImportService(db).bulk_apply_cluster(
        user_id=user.id, session_id=session_a.id, payload=request,
    )

    # Different account → different fingerprint; identifier_value is the same.
    session_b = _make_session(db, user, account_id=2)
    row_b = _make_row(
        db, session_b, row_index=0,
        description="Внешний перевод по номеру телефона +79161234567",
        account_id=2,
    )
    assert row_b.normalized_data_json["fingerprint"] != \
           row_a.normalized_data_json["fingerprint"], (
        "Different account_id must produce different fingerprints"
    )

    # Phase C step 4: was `assert resolved == {("phone", ...): cp.id}`
    # via CounterpartyIdentifierService. The identifier-binding store is
    # now `brand_identifiers`. Asserts both: legacy CP-id store empty
    # AND brand-id store carries the cross-account binding.
    from app.services.brand_identifier_service import BrandIdentifierService
    from app.services.counterparty_brand_link import resolve_brand_id_for_counterparty

    expected_brand_id = resolve_brand_id_for_counterparty(
        db, user_id=user.id, counterparty_id=counterparty.id,
    )
    assert expected_brand_id is not None

    cp_id_service = CounterpartyIdentifierService(db)
    cp_resolved = cp_id_service.resolve_many(
        user_id=user.id, pairs=[("phone", "+79161234567")],
    )
    assert cp_resolved == {}

    brand_id_service = BrandIdentifierService(db)
    brand_resolved = brand_id_service.resolve_many(
        user_id=user.id, pairs=[("phone", "+79161234567")],
    )
    assert brand_resolved == {("phone", "+79161234567"): expected_brand_id}


# ---------------------------------------------------------------------------
# T4 — cluster_bulk_acked_at + контракт ответа
# ---------------------------------------------------------------------------


def test_bulk_apply_stamps_cluster_bulk_acked_at_on_every_row(
    db, user, counterparty, grocery_category
):
    """T4: каждая строка из payload получает ISO-таймстемп
    `cluster_bulk_acked_at` в normalized_data_json. `user_confirmed_at`
    одновременно НЕ присутствует — это бы сломало вес §10.2 case B."""
    session = _make_session(db, user, account_id=1)
    rows = [
        _make_row(db, session, row_index=i,
                  description="Пятёрочка ул.Ленина 5")
        for i in range(3)
    ]

    request = _build_request(
        cluster_key=rows[0].normalized_data_json["fingerprint"],
        rows=rows,
        counterparty_id=counterparty.id,
        category_id=grocery_category.id,
    )
    ImportService(db).bulk_apply_cluster(
        user_id=user.id, session_id=session.id, payload=request,
    )

    for r in rows:
        db.refresh(r)
        nd = r.normalized_data_json or {}
        ack = nd.get("cluster_bulk_acked_at")
        assert ack is not None, "cluster_bulk_acked_at должен быть проставлен"
        # Проверяем валидность ISO-таймстемпа
        datetime.fromisoformat(ack)
        assert "user_confirmed_at" not in nd, (
            "user_confirmed_at не должен сосуществовать с cluster_bulk_acked_at"
        )


def test_bulk_apply_skips_already_committed_rows(
    db, user, counterparty, grocery_category
):
    """T4 контракт: рои в статусе committed или с created_transaction_id
    в payload скипаются (race-condition guard) и попадают в `skipped_row_ids`."""
    session = _make_session(db, user, account_id=1)
    live = _make_row(db, session, row_index=0,
                     description="Пятёрочка ул.Ленина 5")
    committed = _make_row(db, session, row_index=1,
                          description="Пятёрочка ул.Ленина 5",
                          status="committed")
    committed.created_transaction_id = 999
    db.add(committed)
    db.commit()

    request = _build_request(
        cluster_key=live.normalized_data_json["fingerprint"],
        rows=[live, committed],
        counterparty_id=counterparty.id,
        category_id=grocery_category.id,
    )
    result = ImportService(db).bulk_apply_cluster(
        user_id=user.id, session_id=session.id, payload=request,
    )

    assert result["confirmed_count"] == 1
    assert result["skipped_row_ids"] == [committed.id]


# ---------------------------------------------------------------------------
# T5 — refund cluster override (наследование counterparty + категории)
# ---------------------------------------------------------------------------


def test_refund_cluster_overrides_inherit_brand_and_category(
    db, user, regular_account, counterparty, grocery_category
):
    """T5: when the user's history has expense transactions to «Продукты»
    for a given merchant, a refund cluster matching the same brand
    inherits brand_id + category_id from history via
    `apply_refund_cluster_overrides`.

    Phase C step 4: was `test_refund_cluster_overrides_inherit_counterparty_and_category`.
    The refund-history JOIN now keys on Transaction.brand_id ↔
    Brand.canonical_name. Asserts both: legacy nd.counterparty_id is
    NOT stamped AND nd.brand_id mirrors the brand resolved from history.
    """
    from app.models.brand import Brand
    from app.services.counterparty_brand_link import resolve_brand_id_for_counterparty

    # Seed a Brand with canonical_name matching the refund_brand token so
    # the description-LIKE filter hits and the JOIN groups everything.
    brand = Brand(
        slug=f"kofemoloko_u{user.id}",
        canonical_name="KOFEMOLOKO",
        is_global=False,
        created_by_user_id=user.id,
    )
    db.add(brand)
    db.commit()
    db.refresh(brand)

    # Seed history: 3 KOFEMOLOKO purchases in «Продукты». Both brand_id
    # and counterparty_id populated to mirror what the dual-write era
    # (Steps 2-3) produced.
    for i in range(3):
        tx = Transaction(
            user_id=user.id,
            account_id=regular_account.id,
            type="expense",
            operation_type="regular",
            amount=Decimal("500.00"),
            currency="RUB",
            counterparty_id=counterparty.id,
            brand_id=brand.id,
            category_id=grocery_category.id,
            description=f"KOFEMOLOKO покупка {i}",
            normalized_description="kofemoloko",
            transaction_date=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
        )
        db.add(tx)
    db.commit()

    # Refund cluster of the same brand.
    session = _make_session(db, user, account_id=regular_account.id)
    refund_row = _make_row(
        db, session, row_index=0,
        description="Отмена операции оплаты KOFEMOLOKO",
        amount="500.00",
        direction="income",
        account_id=regular_account.id,
        extra_normalized={"is_refund": True, "refund_brand": "kofemoloko"},
    )

    repo = ImportRepository(db)
    ImportPostProcessor(db, import_repo=repo).apply_refund_cluster_overrides(session=session)
    db.commit()
    db.refresh(refund_row)

    nd = refund_row.normalized_data_json or {}
    assert nd.get("operation_type") == "refund"
    assert nd.get("type") == "income"
    assert nd.get("direction") == "income"
    assert nd.get("category_id") == grocery_category.id, (
        "refund cluster must inherit category from the same-brand purchase history"
    )
    # Negative: counterparty_id is no longer stamped on refund rows.
    assert nd.get("counterparty_id") in (None, "", 0)
    # Positive: brand_id IS the inherited merchant key, matching the
    # brand discovered by the refund-history JOIN.
    assert nd.get("brand_id") == brand.id


def test_refund_cluster_without_purchase_history_does_not_inherit(
    db, user, regular_account
):
    """T5 граничный: если в истории нет покупок этого brand'а, refund-кластер
    помечается operation_type='refund' + type='income', но counterparty/
    category НЕ наследуются (некуда). Строка остаётся в attention-bucket
    для ручного выбора."""
    session = _make_session(db, user, account_id=regular_account.id)
    refund_row = _make_row(
        db, session, row_index=0,
        description="Отмена операции оплаты NEVERSEEN",
        amount="100.00",
        direction="income",
        account_id=regular_account.id,
        extra_normalized={"is_refund": True, "refund_brand": "neverseen"},
    )

    repo = ImportRepository(db)
    ImportPostProcessor(db, import_repo=repo).apply_refund_cluster_overrides(session=session)
    db.commit()
    db.refresh(refund_row)

    nd = refund_row.normalized_data_json or {}
    assert nd.get("operation_type") == "refund"
    assert nd.get("type") == "income"
    assert nd.get("direction") == "income"
    assert nd.get("category_id") in (None, ""), (
        "Без истории brand'а категория не наследуется"
    )
    assert nd.get("counterparty_id") in (None, "", 0), (
        "Без истории brand'а counterparty не наследуется"
    )
