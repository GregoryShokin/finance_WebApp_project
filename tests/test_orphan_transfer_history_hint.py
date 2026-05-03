"""Tests for history-based orphan-transfer hint (spec §5.2 v1.20).

When a row is classified as transfer but has no target_account_id and
no cross-session partner appeared in the matcher, `_escalate_orphan_transfers`
now consults committed history by fingerprint BEFORE demoting to regular.

  • ≥3 committed tx of this fingerprint AND ≥80% of them were transfer
    → keep operation_type='transfer', surface suggested_target_*.
  • Fewer or weaker history → fall through to v1.9 demote path.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.account import Account
from app.models.bank import Bank
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.transaction import Transaction
from app.services.transfer_matcher_service import TransferMatcherService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FP = "abc123fp"


@pytest.fixture
def matcher(db):
    return TransferMatcherService(db)


@pytest.fixture
def sber_acc(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id, name="Сбер дебет",
        account_type="main", balance=Decimal("0"),
        currency="RUB", is_active=True, is_credit=False,
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def closed_tinkoff(db, user, bank):
    """A closed Tinkoff account — the historical target for the orphan."""
    acc = Account(
        user_id=user.id, bank_id=bank.id, name="Тинькоф (закрыт)",
        account_type="main", balance=Decimal("0"),
        currency="RUB", is_active=False, is_credit=False,
        is_closed=True, closed_at=date(2026, 4, 1),
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


def _tx(db, *, user, account, target_account_id, fingerprint, op_type, when):
    """Helper: create a committed transaction with the given fingerprint."""
    t = Transaction(
        user_id=user.id, account_id=account.id,
        target_account_id=target_account_id,
        amount=Decimal("1000"), currency="RUB",
        type="income" if target_account_id else "expense",
        operation_type=op_type,
        description=f"hist {when.isoformat()}",
        normalized_description=f"hist {when.isoformat()}",
        skeleton="hist <PHONE>",
        fingerprint=fingerprint,
        transaction_date=when,
    )
    db.add(t); db.commit(); db.refresh(t)
    return t


def _orphan_row(db, *, sess, account, fingerprint):
    nd = {
        "operation_type": "transfer",
        "account_id": account.id,
        "direction": "income",
        "amount": "1000",
        "date": datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc).isoformat(),
        "description": "Поступление с карты Тинькофф",
        "skeleton": "поступление карты <BANK>",
        "fingerprint": fingerprint,
        # NO target_account_id, NO transfer_match → orphan after matcher.
    }
    row = ImportRow(
        session_id=sess.id, row_index=0, status="warning",
        raw_data_json={}, normalized_data_json=nd,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def _session(db, user, account):
    s = ImportSession(
        user_id=user.id, account_id=account.id,
        filename="x.csv", file_content="", file_hash="hf",
        source_type="csv", status="preview_ready",
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# Strong history (≥3 confirms, ≥80% transfer) → keep transfer + suggest
# ---------------------------------------------------------------------------


class TestStrongHistory:
    def test_orphan_with_strong_history_keeps_transfer_op_type(
        self, db, user, sber_acc, closed_tinkoff, matcher,
    ):
        # 5/5 prior commits with this fingerprint were transfers TO closed_tinkoff
        for i in range(5):
            _tx(
                db, user=user, account=sber_acc,
                target_account_id=closed_tinkoff.id,
                fingerprint=FP, op_type="transfer",
                when=datetime(2026, i + 1, 15, 10, 0, tzinfo=timezone.utc),
            )

        sess = _session(db, user, sber_acc)
        row = _orphan_row(db, sess=sess, account=sber_acc, fingerprint=FP)

        matcher._escalate_orphan_transfers(user_id=user.id)
        db.refresh(row)

        nd = row.normalized_data_json or {}
        assert nd.get("operation_type") == "transfer"
        assert nd.get("suggested_target_account_id") == closed_tinkoff.id
        assert nd.get("suggested_target_is_closed") is True
        assert nd.get("suggested_target_account_name") == "Тинькоф (закрыт)"
        assert nd.get("suggested_reason", "").startswith("transfer-history")
        assert row.status == "warning"

    def test_orphan_history_hint_includes_most_common_target(
        self, db, user, sber_acc, closed_tinkoff, bank, matcher,
    ):
        # 4 to closed_tinkoff, 1 to a different account → mode is closed_tinkoff
        other_target = Account(
            user_id=user.id, bank_id=bank.id, name="Другой счёт",
            account_type="main", balance=Decimal("0"),
            currency="RUB", is_active=True, is_credit=False,
        )
        db.add(other_target); db.commit(); db.refresh(other_target)

        for _ in range(4):
            _tx(db, user=user, account=sber_acc, target_account_id=closed_tinkoff.id,
                fingerprint=FP, op_type="transfer", when=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc))
        _tx(db, user=user, account=sber_acc, target_account_id=other_target.id,
            fingerprint=FP, op_type="transfer", when=datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc))

        sess = _session(db, user, sber_acc)
        row = _orphan_row(db, sess=sess, account=sber_acc, fingerprint=FP)

        matcher._escalate_orphan_transfers(user_id=user.id)
        db.refresh(row)

        nd = row.normalized_data_json or {}
        assert nd.get("suggested_target_account_id") == closed_tinkoff.id


# ---------------------------------------------------------------------------
# Weak / no history → demote to regular
# ---------------------------------------------------------------------------


class TestWeakHistory:
    def test_orphan_with_weak_history_demotes_to_regular(
        self, db, user, sber_acc, closed_tinkoff, matcher,
    ):
        # 1/5 transfer, 4/5 regular → ratio 0.2 < 0.8 → demote.
        _tx(db, user=user, account=sber_acc, target_account_id=closed_tinkoff.id,
            fingerprint=FP, op_type="transfer", when=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc))
        for i in range(4):
            _tx(db, user=user, account=sber_acc, target_account_id=None,
                fingerprint=FP, op_type="regular",
                when=datetime(2026, 3, 2 + i, 10, 0, tzinfo=timezone.utc))

        sess = _session(db, user, sber_acc)
        row = _orphan_row(db, sess=sess, account=sber_acc, fingerprint=FP)

        matcher._escalate_orphan_transfers(user_id=user.id)
        db.refresh(row)

        nd = row.normalized_data_json or {}
        assert nd.get("operation_type") == "regular"
        assert nd.get("was_orphan_transfer") is True
        assert "suggested_target_account_id" not in nd

    def test_orphan_with_no_history_demotes_to_regular(
        self, db, user, sber_acc, matcher,
    ):
        sess = _session(db, user, sber_acc)
        row = _orphan_row(db, sess=sess, account=sber_acc, fingerprint=FP)

        matcher._escalate_orphan_transfers(user_id=user.id)
        db.refresh(row)

        nd = row.normalized_data_json or {}
        assert nd.get("operation_type") == "regular"
        assert nd.get("was_orphan_transfer") is True

    def test_orphan_below_min_history_demotes(
        self, db, user, sber_acc, closed_tinkoff, matcher,
    ):
        # Only 2 committed tx, both transfer (100%) — but below MIN=3 → demote.
        for i in range(2):
            _tx(db, user=user, account=sber_acc, target_account_id=closed_tinkoff.id,
                fingerprint=FP, op_type="transfer",
                when=datetime(2026, 3, 1 + i, 10, 0, tzinfo=timezone.utc))

        sess = _session(db, user, sber_acc)
        row = _orphan_row(db, sess=sess, account=sber_acc, fingerprint=FP)

        matcher._escalate_orphan_transfers(user_id=user.id)
        db.refresh(row)

        nd = row.normalized_data_json or {}
        assert nd.get("operation_type") == "regular"


# ---------------------------------------------------------------------------
# Edge: target account deleted between commits and now
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_orphan_history_hint_skips_target_if_account_deleted(
        self, db, user, sber_acc, bank, matcher,
    ):
        # Target had id=999 in history but no longer exists.
        # Simulate by creating tx pointing to a real account, then deleting it.
        ghost = Account(
            user_id=user.id, bank_id=bank.id, name="ghost",
            account_type="main", balance=Decimal("0"),
            currency="RUB", is_active=True, is_credit=False,
        )
        db.add(ghost); db.commit(); db.refresh(ghost)
        ghost_id = ghost.id

        for i in range(3):
            _tx(db, user=user, account=sber_acc, target_account_id=ghost_id,
                fingerprint=FP, op_type="transfer",
                when=datetime(2026, 3, 1 + i, 10, 0, tzinfo=timezone.utc))

        # Delete the ghost account (FK SET NULL on transactions.target_account_id).
        # NOTE: In real production deleting an account with transactions is
        # blocked, but here we simulate post-deletion state by clearing the FK.
        db.query(Transaction).filter(Transaction.target_account_id == ghost_id).update(
            {Transaction.target_account_id: None}
        )
        db.delete(ghost)
        db.commit()

        sess = _session(db, user, sber_acc)
        row = _orphan_row(db, sess=sess, account=sber_acc, fingerprint=FP)

        matcher._escalate_orphan_transfers(user_id=user.id)
        db.refresh(row)

        nd = row.normalized_data_json or {}
        # History ratio still ≥0.8 (3/3 transfer), so kept as transfer,
        # but target_counter is empty → no suggested target.
        # OR: ratio is computed against transfers with non-None target.
        # In our impl: all 3 had operation_type='transfer' so ratio is 1.0.
        # target_counter sees None → no suggested_target_*.
        # operation_type stays 'transfer'.
        assert nd.get("operation_type") == "transfer"
        assert nd.get("suggested_target_account_id") is None or "suggested_target_account_id" not in nd

    def test_orphan_with_closed_target_account_works(
        self, db, user, sber_acc, closed_tinkoff, matcher,
    ):
        # Target is closed (is_closed=True). History pass should still
        # find the account (it stays in DB) and suggest it.
        for i in range(3):
            _tx(db, user=user, account=sber_acc, target_account_id=closed_tinkoff.id,
                fingerprint=FP, op_type="transfer",
                when=datetime(2026, 2, 1 + i, 10, 0, tzinfo=timezone.utc))

        sess = _session(db, user, sber_acc)
        row = _orphan_row(db, sess=sess, account=sber_acc, fingerprint=FP)

        matcher._escalate_orphan_transfers(user_id=user.id)
        db.refresh(row)

        nd = row.normalized_data_json or {}
        assert nd.get("suggested_target_account_id") == closed_tinkoff.id
        assert nd.get("suggested_target_is_closed") is True

    def test_orphan_with_user_confirmed_at_is_skipped(
        self, db, user, sber_acc, closed_tinkoff, matcher,
    ):
        # User explicitly confirmed; matcher must not touch the row.
        for i in range(5):
            _tx(db, user=user, account=sber_acc, target_account_id=closed_tinkoff.id,
                fingerprint=FP, op_type="transfer",
                when=datetime(2026, 3, 1 + i, 10, 0, tzinfo=timezone.utc))

        sess = _session(db, user, sber_acc)
        row = _orphan_row(db, sess=sess, account=sber_acc, fingerprint=FP)
        nd = dict(row.normalized_data_json or {})
        nd["user_confirmed_at"] = "2026-05-01T10:00:00+00:00"
        row.normalized_data_json = nd
        db.add(row); db.commit(); db.refresh(row)

        matcher._escalate_orphan_transfers(user_id=user.id)
        db.refresh(row)

        nd_after = row.normalized_data_json or {}
        assert nd_after.get("operation_type") == "transfer"
        # No hint added — user_confirmed_at means hands off.
        assert "suggested_target_account_id" not in nd_after
