"""§8.1 — deduplication key must include skeleton, not normalized_description.

Covers both the new skeleton-based path and the legacy fallback path used
for transactions created before migration 0052 (skeleton IS NULL).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.services.import_service import ImportService
from tests.conftest import make_transaction


@pytest.fixture
def svc(db):
    return ImportService(db)


@pytest.fixture
def account_id(regular_account):
    return regular_account.id


def _tx(db, user, account, *, skeleton, amount="100.00", description="Магазин 5", when=None):
    return make_transaction(
        db,
        user_id=user.id,
        account_id=account.id,
        amount=Decimal(amount),
        currency="RUB",
        type="expense",
        operation_type="regular",
        description=description,
        normalized_description=description.lower(),
        skeleton=skeleton,
        transaction_date=when or datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
    )


class TestSkeletonBasedDedup:
    def test_same_skeleton_same_date_same_amount_is_duplicate(
        self, svc, db, user, regular_account
    ):
        _tx(db, user, regular_account, skeleton="магазин <NUM>")

        is_dup = svc._find_duplicate(
            user_id=user.id,
            account_id=regular_account.id,
            amount=Decimal("100.00"),
            transaction_date=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
            skeleton="магазин <NUM>",
            normalized_description="магазин 5",
        )
        assert is_dup is True

    def test_different_skeleton_is_not_duplicate(
        self, svc, db, user, regular_account
    ):
        _tx(db, user, regular_account, skeleton="магазин <NUM>")

        is_dup = svc._find_duplicate(
            user_id=user.id,
            account_id=regular_account.id,
            amount=Decimal("100.00"),
            transaction_date=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
            skeleton="другой магазин <NUM>",
            normalized_description="другой магазин 7",
        )
        assert is_dup is False

    def test_same_skeleton_different_amount_is_not_duplicate(
        self, svc, db, user, regular_account
    ):
        _tx(db, user, regular_account, skeleton="магазин <NUM>", amount="100.00")

        is_dup = svc._find_duplicate(
            user_id=user.id,
            account_id=regular_account.id,
            amount=Decimal("200.00"),
            transaction_date=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
            skeleton="магазин <NUM>",
            normalized_description="магазин 5",
        )
        assert is_dup is False

    def test_identifier_placeholder_collapses_variants(
        self, svc, db, user, regular_account
    ):
        """Two 'transfer to <phone>' rows with different phones but same
        skeleton must dedup against each other — the point of §8.1."""
        _tx(
            db,
            user,
            regular_account,
            skeleton="перевод на <PHONE>",
            description="Перевод на +79991234567",
        )

        is_dup = svc._find_duplicate(
            user_id=user.id,
            account_id=regular_account.id,
            amount=Decimal("100.00"),
            transaction_date=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
            skeleton="перевод на <PHONE>",
            normalized_description="перевод на +79997654321",  # different phone
        )
        assert is_dup is True


class TestLegacyFallback:
    """For transactions created before migration 0052 (skeleton IS NULL),
    we fall back to normalized_description matching. Once the backfill
    script runs this path won't fire, but it must work in the meantime."""

    def test_legacy_row_without_skeleton_still_dedupes_by_normalized_description(
        self, svc, db, user, regular_account
    ):
        # Insert with skeleton=None to simulate a pre-0052 row.
        _tx(
            db,
            user,
            regular_account,
            skeleton=None,
            description="Магазин 5",
        )

        is_dup = svc._find_duplicate(
            user_id=user.id,
            account_id=regular_account.id,
            amount=Decimal("100.00"),
            transaction_date=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
            skeleton="магазин <NUM>",
            normalized_description="магазин 5",
        )
        assert is_dup is True

    def test_new_row_with_skeleton_does_not_match_legacy_by_skeleton(
        self, svc, db, user, regular_account
    ):
        """A new transaction with a different skeleton should NOT match a
        legacy (skeleton=None) row just because their normalized_description
        collides. The legacy fallback requires a normalized_description
        match — if the incoming normalized_description differs, it shouldn't
        fire."""
        _tx(
            db,
            user,
            regular_account,
            skeleton=None,
            description="Магазин 5",
        )

        is_dup = svc._find_duplicate(
            user_id=user.id,
            account_id=regular_account.id,
            amount=Decimal("100.00"),
            transaction_date=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
            skeleton="магазин <NUM>",
            normalized_description="совсем другая строка",
        )
        assert is_dup is False
