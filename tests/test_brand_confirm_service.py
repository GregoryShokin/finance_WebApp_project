"""Tests for BrandConfirmService — Brand registry Ph6."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.user import User
from app.repositories.brand_repository import BrandRepository
from app.services.brand_confirm_service import (
    BrandConfirmError,
    BrandConfirmService,
)


@pytest.fixture
def other_user(db) -> User:
    u = User(email="other@example.com", password_hash="x", is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def brand_pattern(db):
    repo = BrandRepository(db)
    brand = repo.create_brand(
        slug="pyaterochka", canonical_name="Пятёрочка",
        category_hint="Продукты", is_global=True,
    )
    bp, _ = repo.upsert_pattern(
        brand_id=brand.id, kind="text", pattern="pyaterochka", is_global=True,
    )
    db.commit()
    return brand, bp


def _make_session(db, *, user_id: int, status: str = "preview_ready") -> ImportSession:
    session = ImportSession(
        user_id=user_id,
        filename="test.csv",
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
    brand_id: int | None = None,
    brand_pattern_id: int | None = None,
    status: str = "warning",
) -> ImportRow:
    nd: dict = {
        "amount": "100.00",
        "direction": "expense",
        "transaction_date": "2026-01-15T12:00:00+00:00",
        "skeleton": "оплата pyaterochka",
        "fingerprint": f"fp{row_index:014d}",
    }
    if brand_id is not None:
        nd["brand_id"] = brand_id
        nd["brand_slug"] = "pyaterochka"
        nd["brand_canonical_name"] = "Пятёрочка"
        nd["brand_pattern_id"] = brand_pattern_id
        nd["brand_kind"] = "text"
        nd["brand_confidence"] = 0.96
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


# ───────────────────────────────────────────────────────────────────
# confirm — happy path + propagation
# ───────────────────────────────────────────────────────────────────


def test_confirm_predicted_brand_bumps_pattern_and_stamps_row(
    db, user, brand_pattern,
):
    brand, bp = brand_pattern
    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, row_index=1,
        brand_id=brand.id, brand_pattern_id=bp.id,
    )

    svc = BrandConfirmService(db)
    result = svc.confirm_brand_for_row(
        user_id=user.id, row_id=row.id, brand_id=brand.id,
    )

    assert result["brand_id"] == brand.id
    assert result["was_override"] is False
    assert result["propagated_count"] == 0  # no sibling rows yet
    # Ph7c: confirmation materializes a Counterparty for the user.
    assert result["counterparty_id"] is not None
    assert result["counterparty_name"] == brand.canonical_name

    db.refresh(row)
    assert row.normalized_data_json["user_confirmed_brand_id"] == brand.id
    assert "user_confirmed_brand_at" in row.normalized_data_json
    assert row.normalized_data_json["counterparty_id"] == result["counterparty_id"]

    db.refresh(bp)
    assert bp.confirms == Decimal("1")
    assert bp.rejections == Decimal("0")


def test_confirm_creates_counterparty_when_none_exists(
    db, user, brand_pattern,
):
    from app.models.counterparty import Counterparty
    brand, bp = brand_pattern
    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, brand_id=brand.id, brand_pattern_id=bp.id,
    )

    BrandConfirmService(db).confirm_brand_for_row(
        user_id=user.id, row_id=row.id, brand_id=brand.id,
    )

    cps = db.query(Counterparty).filter(
        Counterparty.user_id == user.id,
        Counterparty.name == brand.canonical_name,
    ).all()
    assert len(cps) == 1


def test_confirm_reuses_existing_counterparty_case_insensitive(
    db, user, brand_pattern,
):
    from app.models.counterparty import Counterparty
    brand, bp = brand_pattern
    # User had typed «пятёрочка» (lowercase ё) before any brand existed.
    pre_existing = Counterparty(user_id=user.id, name="пятёрочка")
    db.add(pre_existing)
    db.commit()
    db.refresh(pre_existing)

    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, brand_id=brand.id, brand_pattern_id=bp.id,
    )

    result = BrandConfirmService(db).confirm_brand_for_row(
        user_id=user.id, row_id=row.id, brand_id=brand.id,
    )

    assert result["counterparty_id"] == pre_existing.id
    cps = db.query(Counterparty).filter(
        Counterparty.user_id == user.id,
    ).all()
    # Still only one counterparty — no duplicate created.
    assert len(cps) == 1


def test_confirm_applies_category_from_brand_hint(db, user, brand_pattern):
    from app.models.category import Category as _CategoryModel
    brand, bp = brand_pattern
    cat = _CategoryModel(
        user_id=user.id, name="Продукты", kind="expense",
        priority="expense_essential", icon_name="shopping-basket", is_system=False,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)

    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, brand_id=brand.id, brand_pattern_id=bp.id,
    )

    result = BrandConfirmService(db).confirm_brand_for_row(
        user_id=user.id, row_id=row.id, brand_id=brand.id,
    )

    assert result["category_id"] == cat.id
    assert result["category_name"] == "Продукты"
    db.refresh(row)
    assert row.normalized_data_json["category_id"] == cat.id


def test_confirm_skips_category_when_user_has_no_matching_category(
    db, user, brand_pattern,
):
    """If the user's category set doesn't include 'Продукты', we silently
    skip the auto-category step. Counterparty binding still succeeds."""
    brand, bp = brand_pattern
    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, brand_id=brand.id, brand_pattern_id=bp.id,
    )

    result = BrandConfirmService(db).confirm_brand_for_row(
        user_id=user.id, row_id=row.id, brand_id=brand.id,
    )
    assert result["category_id"] is None
    db.refresh(row)
    # Counterparty still attached even without a category.
    assert row.normalized_data_json["counterparty_id"] is not None


def test_confirm_does_not_overwrite_user_picked_category(
    db, user, brand_pattern,
):
    from app.models.category import Category as _CategoryModel
    brand, bp = brand_pattern
    hint_cat = _CategoryModel(
        user_id=user.id, name="Продукты", kind="expense",
        priority="expense_essential", icon_name="shopping-basket", is_system=False,
    )
    user_cat = _CategoryModel(
        user_id=user.id, name="Готовая еда", kind="expense",
        priority="expense_secondary", icon_name="utensils-crossed", is_system=False,
    )
    db.add_all([hint_cat, user_cat])
    db.commit()
    db.refresh(hint_cat)
    db.refresh(user_cat)

    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, brand_id=brand.id, brand_pattern_id=bp.id,
    )
    # User has manually attached a different category prior to confirming.
    nd = dict(row.normalized_data_json)
    nd["category_id"] = user_cat.id
    row.normalized_data_json = nd
    db.add(row)
    db.commit()

    BrandConfirmService(db).confirm_brand_for_row(
        user_id=user.id, row_id=row.id, brand_id=brand.id,
    )
    db.refresh(row)
    assert row.normalized_data_json["category_id"] == user_cat.id  # preserved
    # Hint category is still resolvable on the brand, just not applied.
    assert hint_cat.id != row.normalized_data_json["category_id"]


def test_confirm_with_explicit_category_saves_user_override(
    db, user, brand_pattern,
):
    from app.models.category import Category as _CategoryModel
    from app.repositories.user_brand_category_override_repository import (
        UserBrandCategoryOverrideRepository,
    )
    brand, bp = brand_pattern
    delivery = _CategoryModel(
        user_id=user.id, name="Доставка еды", kind="expense",
        priority="expense_secondary", icon_name="utensils-crossed",
        is_system=False,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)

    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, brand_id=brand.id, brand_pattern_id=bp.id,
    )

    BrandConfirmService(db).confirm_brand_for_row(
        user_id=user.id, row_id=row.id, brand_id=brand.id,
        category_id=delivery.id,
    )

    db.refresh(row)
    assert row.normalized_data_json["category_id"] == delivery.id

    override = UserBrandCategoryOverrideRepository(db).get(
        user_id=user.id, brand_id=brand.id,
    )
    assert override is not None
    assert override.category_id == delivery.id


def test_confirm_explicit_category_overwrites_sibling_existing_categories(
    db, user, brand_pattern,
):
    """Brand-level decision (user explicitly picks at confirm) wins over
    per-row state — existing category_ids on siblings are overwritten."""
    from app.models.category import Category as _CategoryModel
    brand, bp = brand_pattern
    other_cat = _CategoryModel(
        user_id=user.id, name="Прочее", kind="expense",
        priority="expense_secondary", icon_name="utensils-crossed",
        is_system=False,
    )
    delivery = _CategoryModel(
        user_id=user.id, name="Доставка еды", kind="expense",
        priority="expense_secondary", icon_name="utensils-crossed",
        is_system=False,
    )
    db.add_all([other_cat, delivery])
    db.commit()
    db.refresh(other_cat)
    db.refresh(delivery)

    session = _make_session(db, user_id=user.id)
    triggered = _make_row(
        db, session_id=session.id, row_index=1,
        brand_id=brand.id, brand_pattern_id=bp.id,
    )
    sibling = _make_row(
        db, session_id=session.id, row_index=2,
        brand_id=brand.id, brand_pattern_id=bp.id,
    )
    # Sibling already has a category from a previous (default) confirm.
    nd = dict(sibling.normalized_data_json)
    nd["category_id"] = other_cat.id
    sibling.normalized_data_json = nd
    db.add(sibling)
    db.commit()

    BrandConfirmService(db).confirm_brand_for_row(
        user_id=user.id, row_id=triggered.id, brand_id=brand.id,
        category_id=delivery.id,
    )

    db.refresh(sibling)
    assert sibling.normalized_data_json["category_id"] == delivery.id


def test_apply_brand_category_for_user_sweeps_existing_rows(
    db, user, brand_pattern,
):
    from app.models.category import Category as _CategoryModel
    from app.repositories.user_brand_category_override_repository import (
        UserBrandCategoryOverrideRepository,
    )
    brand, bp = brand_pattern
    cat_a = _CategoryModel(
        user_id=user.id, name="Кафе", kind="expense",
        priority="expense_secondary", icon_name="utensils-crossed",
        is_system=False,
    )
    cat_b = _CategoryModel(
        user_id=user.id, name="Доставка еды", kind="expense",
        priority="expense_secondary", icon_name="utensils-crossed",
        is_system=False,
    )
    db.add_all([cat_a, cat_b])
    db.commit()

    session = _make_session(db, user_id=user.id)
    rows = [
        _make_row(
            db, session_id=session.id, row_index=i,
            brand_id=brand.id, brand_pattern_id=bp.id,
        )
        for i in range(1, 4)
    ]
    # Pre-stamp existing category cat_a on all 3 rows (simulate prior confirm).
    for r in rows:
        rd = dict(r.normalized_data_json)
        rd["category_id"] = cat_a.id
        r.normalized_data_json = rd
        db.add(r)
    db.commit()

    result = BrandConfirmService(db).apply_brand_category_for_user(
        user_id=user.id, brand_id=brand.id, category_id=cat_b.id,
    )

    assert result["rows_updated"] == 3
    assert result["category_id"] == cat_b.id

    for r in rows:
        db.refresh(r)
        assert r.normalized_data_json["category_id"] == cat_b.id

    override = UserBrandCategoryOverrideRepository(db).get(
        user_id=user.id, brand_id=brand.id,
    )
    assert override is not None
    assert override.category_id == cat_b.id


def test_apply_brand_category_idempotent_when_already_set(
    db, user, brand_pattern,
):
    from app.models.category import Category as _CategoryModel
    brand, bp = brand_pattern
    cat = _CategoryModel(
        user_id=user.id, name="Доставка еды", kind="expense",
        priority="expense_secondary", icon_name="utensils-crossed",
        is_system=False,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)

    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, brand_id=brand.id, brand_pattern_id=bp.id,
    )
    rd = dict(row.normalized_data_json)
    rd["category_id"] = cat.id
    row.normalized_data_json = rd
    db.add(row)
    db.commit()

    result = BrandConfirmService(db).apply_brand_category_for_user(
        user_id=user.id, brand_id=brand.id, category_id=cat.id,
    )
    # No row updates because category was already set to the target.
    assert result["rows_updated"] == 0


def test_override_is_used_on_subsequent_confirm(
    db, user, brand_pattern,
):
    """Once override is set (e.g. via apply_brand_category), subsequent
    confirms on other sessions automatically use the override category
    instead of the brand's default hint."""
    from app.models.category import Category as _CategoryModel
    brand, bp = brand_pattern
    cat_b = _CategoryModel(
        user_id=user.id, name="Доставка еды", kind="expense",
        priority="expense_secondary", icon_name="utensils-crossed",
        is_system=False,
    )
    db.add(cat_b)
    db.commit()
    db.refresh(cat_b)

    # Set the override directly via the override repo to skip apply step.
    from app.repositories.user_brand_category_override_repository import (
        UserBrandCategoryOverrideRepository,
    )
    UserBrandCategoryOverrideRepository(db).upsert(
        user_id=user.id, brand_id=brand.id, category_id=cat_b.id,
    )
    db.commit()

    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, brand_id=brand.id, brand_pattern_id=bp.id,
    )
    result = BrandConfirmService(db).confirm_brand_for_row(
        user_id=user.id, row_id=row.id, brand_id=brand.id,
    )
    assert result["category_id"] == cat_b.id
    assert result["category_name"] == "Доставка еды"


def test_confirm_creates_fingerprint_binding(db, user, brand_pattern):
    from app.repositories.counterparty_fingerprint_repository import (
        CounterpartyFingerprintRepository,
    )
    brand, bp = brand_pattern
    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, brand_id=brand.id, brand_pattern_id=bp.id,
    )

    result = BrandConfirmService(db).confirm_brand_for_row(
        user_id=user.id, row_id=row.id, brand_id=brand.id,
    )

    fp = row.normalized_data_json.get("fingerprint")
    binding = CounterpartyFingerprintRepository(db).get_by_fingerprint(
        user_id=user.id, fingerprint=fp,
    )
    assert binding is not None
    assert binding.counterparty_id == result["counterparty_id"]


def test_confirm_propagates_to_sibling_rows_with_same_predicted_brand(
    db, user, brand_pattern,
):
    from app.models.category import Category as _CategoryModel
    brand, bp = brand_pattern
    cat = _CategoryModel(
        user_id=user.id, name="Продукты", kind="expense",
        priority="expense_essential", icon_name="shopping-basket", is_system=False,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)

    session = _make_session(db, user_id=user.id)
    rows = [
        _make_row(
            db, session_id=session.id, row_index=i,
            brand_id=brand.id, brand_pattern_id=bp.id,
        )
        for i in range(1, 5)  # 4 rows of the same brand
    ]
    # One unrelated row that should NOT inherit the confirmation
    other_row = _make_row(db, session_id=session.id, row_index=99)

    svc = BrandConfirmService(db)
    result = svc.confirm_brand_for_row(
        user_id=user.id, row_id=rows[0].id, brand_id=brand.id,
    )

    assert result["propagated_count"] == 3  # 4 same-brand rows; 1 was the trigger

    for r in rows:
        db.refresh(r)
        assert r.normalized_data_json.get("user_confirmed_brand_id") == brand.id
        # Each sibling inherits both counterparty and category.
        assert r.normalized_data_json.get("counterparty_id") == result["counterparty_id"]
        assert r.normalized_data_json.get("category_id") == cat.id

    db.refresh(other_row)
    assert "user_confirmed_brand_id" not in other_row.normalized_data_json
    # And the unrelated row stays untouched.
    assert other_row.normalized_data_json.get("counterparty_id") is None


def test_confirm_clears_prior_rejection_marker(db, user, brand_pattern):
    brand, bp = brand_pattern
    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, row_index=1,
        brand_id=brand.id, brand_pattern_id=bp.id,
    )
    nd = dict(row.normalized_data_json)
    nd["user_rejected_brand_id"] = brand.id
    nd["user_rejected_brand_at"] = "2026-01-01T00:00:00+00:00"
    row.normalized_data_json = nd
    db.add(row)
    db.commit()

    svc = BrandConfirmService(db)
    svc.confirm_brand_for_row(user_id=user.id, row_id=row.id, brand_id=brand.id)

    db.refresh(row)
    assert "user_rejected_brand_id" not in row.normalized_data_json


# ───────────────────────────────────────────────────────────────────
# confirm — override (different brand)
# ───────────────────────────────────────────────────────────────────


def test_confirm_with_different_brand_rejects_predicted_pattern(
    db, user, brand_pattern,
):
    brand, bp = brand_pattern
    repo = BrandRepository(db)
    other_brand = repo.create_brand(
        slug="magnit", canonical_name="Магнит", is_global=True,
    )
    db.commit()

    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, row_index=1,
        brand_id=brand.id, brand_pattern_id=bp.id,
    )

    svc = BrandConfirmService(db)
    result = svc.confirm_brand_for_row(
        user_id=user.id, row_id=row.id, brand_id=other_brand.id,
    )
    assert result["was_override"] is True
    assert result["brand_id"] == other_brand.id
    assert result["propagated_count"] == 0  # never propagate on override

    db.refresh(bp)
    assert bp.rejections == Decimal("1")
    assert bp.confirms == Decimal("0")

    db.refresh(row)
    assert row.normalized_data_json["user_confirmed_brand_id"] == other_brand.id


def test_confirm_override_does_not_touch_sibling_rows(db, user, brand_pattern):
    brand, bp = brand_pattern
    repo = BrandRepository(db)
    other_brand = repo.create_brand(
        slug="magnit", canonical_name="Магнит", is_global=True,
    )
    db.commit()

    session = _make_session(db, user_id=user.id)
    triggered = _make_row(
        db, session_id=session.id, row_index=1,
        brand_id=brand.id, brand_pattern_id=bp.id,
    )
    sibling = _make_row(
        db, session_id=session.id, row_index=2,
        brand_id=brand.id, brand_pattern_id=bp.id,
    )

    svc = BrandConfirmService(db)
    svc.confirm_brand_for_row(
        user_id=user.id, row_id=triggered.id, brand_id=other_brand.id,
    )

    db.refresh(sibling)
    assert "user_confirmed_brand_id" not in sibling.normalized_data_json


# ───────────────────────────────────────────────────────────────────
# reject
# ───────────────────────────────────────────────────────────────────


def test_reject_increments_rejection_and_stamps_row(
    db, user, brand_pattern,
):
    brand, bp = brand_pattern
    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, row_index=1,
        brand_id=brand.id, brand_pattern_id=bp.id,
    )

    svc = BrandConfirmService(db)
    result = svc.reject_brand_for_row(user_id=user.id, row_id=row.id)

    assert result["rejected_brand_id"] == brand.id
    db.refresh(row)
    assert row.normalized_data_json["user_rejected_brand_id"] == brand.id

    db.refresh(bp)
    assert bp.rejections == Decimal("1")


def test_reject_without_predicted_brand_raises(db, user):
    session = _make_session(db, user_id=user.id)
    row = _make_row(db, session_id=session.id, row_index=1)  # no brand fields

    svc = BrandConfirmService(db)
    with pytest.raises(BrandConfirmError, match="нечего отклонять"):
        svc.reject_brand_for_row(user_id=user.id, row_id=row.id)


def test_reject_clears_prior_confirmation(db, user, brand_pattern):
    brand, bp = brand_pattern
    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, row_index=1,
        brand_id=brand.id, brand_pattern_id=bp.id,
    )
    nd = dict(row.normalized_data_json)
    nd["user_confirmed_brand_id"] = brand.id
    nd["user_confirmed_brand_at"] = "2026-01-01T00:00:00+00:00"
    row.normalized_data_json = nd
    db.add(row)
    db.commit()

    svc = BrandConfirmService(db)
    svc.reject_brand_for_row(user_id=user.id, row_id=row.id)

    db.refresh(row)
    assert "user_confirmed_brand_id" not in row.normalized_data_json


# ───────────────────────────────────────────────────────────────────
# Validation guards
# ───────────────────────────────────────────────────────────────────


def test_confirm_unknown_row_raises(db, user, brand_pattern):
    brand, _ = brand_pattern
    svc = BrandConfirmService(db)
    with pytest.raises(BrandConfirmError, match="не найдена"):
        svc.confirm_brand_for_row(
            user_id=user.id, row_id=999999, brand_id=brand.id,
        )


def test_confirm_unknown_brand_raises(db, user, brand_pattern):
    _, bp = brand_pattern
    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, brand_id=1, brand_pattern_id=bp.id,
    )
    svc = BrandConfirmService(db)
    with pytest.raises(BrandConfirmError, match="не найден"):
        svc.confirm_brand_for_row(
            user_id=user.id, row_id=row.id, brand_id=999999,
        )


def test_confirm_other_users_private_brand_raises(
    db, user, other_user, brand_pattern,
):
    repo = BrandRepository(db)
    private = repo.create_brand(
        slug="theirs", canonical_name="Theirs",
        is_global=False, created_by_user_id=other_user.id,
    )
    db.commit()

    _, bp = brand_pattern
    session = _make_session(db, user_id=user.id)
    row = _make_row(
        db, session_id=session.id, brand_id=1, brand_pattern_id=bp.id,
    )

    svc = BrandConfirmService(db)
    with pytest.raises(BrandConfirmError, match="недоступен"):
        svc.confirm_brand_for_row(
            user_id=user.id, row_id=row.id, brand_id=private.id,
        )


def test_confirm_committed_session_raises(db, user, brand_pattern):
    brand, bp = brand_pattern
    session = _make_session(db, user_id=user.id, status="committed")
    row = _make_row(
        db, session_id=session.id,
        brand_id=brand.id, brand_pattern_id=bp.id,
    )

    svc = BrandConfirmService(db)
    with pytest.raises(BrandConfirmError, match="закоммичена"):
        svc.confirm_brand_for_row(
            user_id=user.id, row_id=row.id, brand_id=brand.id,
        )


def test_other_users_row_invisible(db, user, other_user, brand_pattern):
    brand, bp = brand_pattern
    session = _make_session(db, user_id=other_user.id)
    row = _make_row(
        db, session_id=session.id,
        brand_id=brand.id, brand_pattern_id=bp.id,
    )

    svc = BrandConfirmService(db)
    with pytest.raises(BrandConfirmError, match="не найдена"):
        svc.confirm_brand_for_row(
            user_id=user.id, row_id=row.id, brand_id=brand.id,
        )
