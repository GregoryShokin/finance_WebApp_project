"""Tests for PersonalNameBindService — unified «+ Имя / Бренд» bind flow.

Covers the routing logic between Brand and DebtPartner, identifier
binding, propagation across sibling rows, and the §12.2 / §12.11
invariants. The service commits internally (mirrors BrandConfirmService),
so tests refresh entities after each call rather than asserting on
in-flight session state.
"""
from __future__ import annotations

import pytest

from app.models.brand import Brand
from app.models.category import Category
from app.models.debt_partner import DebtPartner
from app.models.debt_partner_identifier import DebtPartnerIdentifier
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.repositories.brand_repository import BrandRepository
from app.services.personal_name_bind_service import (
    PersonalNameBindError,
    PersonalNameBindService,
    _hash_person_name,
)


# ───────────────────────────────────────────────────────────────────
# Fixtures
# ───────────────────────────────────────────────────────────────────


def _make_session(db, *, user_id: int, status: str = "preview_ready") -> ImportSession:
    session = ImportSession(
        user_id=user_id,
        filename="t.csv",
        source_type="csv",
        status=status,
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
    *,
    session_id: int,
    row_index: int = 1,
    operation_type: str = "regular",
    tokens: dict | None = None,
    extra: dict | None = None,
    status: str = "warning",
) -> ImportRow:
    nd: dict = {
        "amount": "100.00",
        "direction": "expense",
        "operation_type": operation_type,
        "skeleton": "перевод на phone <PHONE>",
        "fingerprint": f"fp{row_index:014d}",
        "description": "Перевод по СБП",
    }
    if tokens is not None:
        nd["tokens"] = tokens
    if extra:
        nd.update(extra)
    row = ImportRow(
        session_id=session_id,
        row_index=row_index,
        raw_data_json={},
        normalized_data_json=nd,
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pytest.fixture
def category(db, user) -> Category:
    cat = Category(
        user_id=user.id,
        name="Семья",
        kind="expense",
        priority="expense_essential",
        regularity="regular",
        is_system=False,
        icon_name="users",
        color="#666",
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


@pytest.fixture
def global_brand(db) -> Brand:
    repo = BrandRepository(db)
    b = repo.create_brand(
        slug="pyaterochka",
        canonical_name="Пятёрочка",
        category_hint="Продукты",
        is_global=True,
    )
    db.commit()
    return b


# ───────────────────────────────────────────────────────────────────
# Brand branch
# ───────────────────────────────────────────────────────────────────


def test_bind_brand_existing_stamps_row(db, user, global_brand):
    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id,
        operation_type="regular",
        tokens={"counterparty_org": "ООО Магнит"},
    )

    svc = PersonalNameBindService(db)
    result = svc.bind_name_to_row(
        user_id=user.id, row_id=row.id, kind="brand",
        existing_id=global_brand.id,
    )

    assert result.kind == "brand"
    assert result.id == global_brand.id
    assert result.name == global_brand.canonical_name

    db.expire_all()
    refreshed = db.query(ImportRow).filter(ImportRow.id == row.id).first()
    nd = refreshed.normalized_data_json
    assert nd["user_confirmed_brand_id"] == global_brand.id
    assert nd["brand_id"] == global_brand.id


def test_bind_brand_creates_private_when_no_existing_id(db, user):
    session = _make_session(db, user_id=user.id)
    row = _make_row(db, session_id=session.id, operation_type="regular")

    svc = PersonalNameBindService(db)
    result = svc.bind_name_to_row(
        user_id=user.id, row_id=row.id, kind="brand",
        name="Кофейня у дома",
    )

    assert result.kind == "brand"
    brand = db.query(Brand).filter(Brand.id == result.id).first()
    assert brand is not None
    assert brand.is_global is False
    assert brand.created_by_user_id == user.id
    assert brand.canonical_name == "Кофейня у дома"


def test_bind_brand_phone_identifier_persists(db, user):
    """Non-transfer brand bind with a phone token populates brand_identifiers."""
    from app.models.brand_identifier import BrandIdentifier

    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, operation_type="regular",
        tokens={"phone": "+79991112233"},
        # Override the default transfer-like skeleton — phone-as-brand
        # binding is guarded against transfer rows by design.
        extra={"skeleton": "оплата курьер еды"},
    )

    svc = PersonalNameBindService(db)
    svc.bind_name_to_row(
        user_id=user.id, row_id=row.id, kind="brand",
        name="Курьер еды",
    )

    bindings = (
        db.query(BrandIdentifier)
        .filter(
            BrandIdentifier.user_id == user.id,
            BrandIdentifier.identifier_kind == "phone",
            BrandIdentifier.identifier_value == "+79991112233",
        )
        .all()
    )
    assert len(bindings) == 1


# ───────────────────────────────────────────────────────────────────
# Contact branch
# ───────────────────────────────────────────────────────────────────


def test_bind_contact_creates_partner_and_stamps_row(db, user, category):
    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, operation_type="regular",
        tokens={"phone": "+79995551111"},
    )

    svc = PersonalNameBindService(db)
    result = svc.bind_name_to_row(
        user_id=user.id, row_id=row.id, kind="contact",
        name="Брат", category_id=category.id,
    )

    assert result.kind == "contact"
    partner = db.query(DebtPartner).filter(DebtPartner.id == result.id).first()
    assert partner.name == "Брат"
    assert partner.user_id == user.id
    assert partner.default_category_id == category.id

    db.refresh(row)
    nd = row.normalized_data_json
    assert nd["personal_counterparty_id"] == partner.id
    assert nd["personal_counterparty_name"] == "Брат"
    assert nd["personal_counterparty_category_id"] == category.id


def test_bind_contact_existing_partner_reused(db, user):
    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, operation_type="regular",
        tokens={"phone": "+79994443333"},
    )
    partner = DebtPartner(user_id=user.id, name="Отец")
    db.add(partner)
    db.commit()
    db.refresh(partner)

    svc = PersonalNameBindService(db)
    result = svc.bind_name_to_row(
        user_id=user.id, row_id=row.id, kind="contact",
        existing_id=partner.id,
    )
    assert result.id == partner.id


def test_bind_contact_persists_phone_identifier(db, user):
    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, operation_type="regular",
        tokens={"phone": "+79991112233"},
    )

    svc = PersonalNameBindService(db)
    svc.bind_name_to_row(
        user_id=user.id, row_id=row.id, kind="contact", name="Друг",
    )

    bindings = (
        db.query(DebtPartnerIdentifier)
        .filter(DebtPartnerIdentifier.user_id == user.id)
        .all()
    )
    assert len(bindings) == 1
    assert bindings[0].identifier_kind == "phone"
    assert bindings[0].identifier_value == "+79991112233"


def test_bind_contact_propagates_to_matching_phone_rows(db, user):
    """Picking «Брат» on one row catches every other row of the user
    that shares the same phone identifier — even across sessions.
    """
    session_a = _make_session(db, user_id=user.id)
    session_b = _make_session(db, user_id=user.id)
    row_a = _make_row(
        db, session_id=session_a.id, row_index=1,
        operation_type="regular",
        tokens={"phone": "+79991112233"},
    )
    row_b = _make_row(
        db, session_id=session_b.id, row_index=2,
        operation_type="regular",
        tokens={"phone": "+79991112233"},
    )
    row_c = _make_row(  # different phone — must NOT be propagated
        db, session_id=session_b.id, row_index=3,
        operation_type="regular",
        tokens={"phone": "+79990000000"},
    )

    svc = PersonalNameBindService(db)
    result = svc.bind_name_to_row(
        user_id=user.id, row_id=row_a.id, kind="contact", name="Брат",
    )

    assert result.propagated_count == 1
    db.expire_all()
    nd_b = db.query(ImportRow).filter(ImportRow.id == row_b.id).first().normalized_data_json
    nd_c = db.query(ImportRow).filter(ImportRow.id == row_c.id).first().normalized_data_json
    assert nd_b["personal_counterparty_id"] == result.id
    assert "personal_counterparty_id" not in nd_c


def test_bind_contact_on_debt_row_stamps_debt_partner_id(db, user):
    """§12.2 — debt rows must carry debt_partner_id at commit. The
    contact stamp on a debt row also writes the FK column so the commit
    orchestrator passes its invariant check.
    """
    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, operation_type="debt",
        tokens={"phone": "+79991115555"},
    )

    svc = PersonalNameBindService(db)
    result = svc.bind_name_to_row(
        user_id=user.id, row_id=row.id, kind="contact", name="Паша",
    )

    db.refresh(row)
    nd = row.normalized_data_json
    assert nd["personal_counterparty_id"] == result.id
    assert nd["debt_partner_id"] == result.id


# ───────────────────────────────────────────────────────────────────
# Validation guards
# ───────────────────────────────────────────────────────────────────


def test_debt_row_rejects_brand_kind(db, user):
    session = _make_session(db, user_id=user.id)
    row = _make_row(db, session_id=session.id, operation_type="debt")
    svc = PersonalNameBindService(db)
    with pytest.raises(PersonalNameBindError):
        svc.bind_name_to_row(
            user_id=user.id, row_id=row.id, kind="brand", name="Х",
        )


def test_transfer_row_rejected(db, user):
    session = _make_session(db, user_id=user.id)
    row = _make_row(db, session_id=session.id, operation_type="transfer")
    svc = PersonalNameBindService(db)
    with pytest.raises(PersonalNameBindError):
        svc.bind_name_to_row(
            user_id=user.id, row_id=row.id, kind="contact", name="Я сам",
        )


def test_missing_name_and_existing_id_rejected(db, user):
    session = _make_session(db, user_id=user.id)
    row = _make_row(db, session_id=session.id, operation_type="regular")
    svc = PersonalNameBindService(db)
    with pytest.raises(PersonalNameBindError):
        svc.bind_name_to_row(
            user_id=user.id, row_id=row.id, kind="contact",
        )


def test_rebind_overwrites_identifier_binding(db, user):
    """Re-binding the same phone to a different partner is the strongest
    signal: «no, this number is THIS person». Repository upsert path
    re-points the binding without creating a duplicate.
    """
    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id,
        operation_type="regular",
        tokens={"phone": "+79991111111"},
    )

    svc = PersonalNameBindService(db)
    first = svc.bind_name_to_row(
        user_id=user.id, row_id=row.id, kind="contact", name="ПервыйКонтакт",
    )

    # Second bind on the same row — different name.
    second = svc.bind_name_to_row(
        user_id=user.id, row_id=row.id, kind="contact", name="ВторойКонтакт",
    )

    assert first.id != second.id
    bindings = (
        db.query(DebtPartnerIdentifier)
        .filter(DebtPartnerIdentifier.user_id == user.id)
        .all()
    )
    assert len(bindings) == 1
    assert bindings[0].debt_partner_id == second.id


def test_person_hash_derived_when_only_name_present(db, user):
    """When the row has `person_name` but no explicit `person_hash`, the
    bind path computes the hash on the fly so the binding survives across
    rows that re-spell the same name.
    """
    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, operation_type="regular",
        tokens={"person_name": "Иванов И. И."},
    )

    svc = PersonalNameBindService(db)
    svc.bind_name_to_row(
        user_id=user.id, row_id=row.id, kind="contact", name="Иванов",
    )

    bindings = (
        db.query(DebtPartnerIdentifier)
        .filter(DebtPartnerIdentifier.user_id == user.id)
        .all()
    )
    kinds = {b.identifier_kind for b in bindings}
    assert "person_hash" in kinds
    expected_hash = _hash_person_name("Иванов И. И.")
    values = {b.identifier_value for b in bindings if b.identifier_kind == "person_hash"}
    assert expected_hash in values
