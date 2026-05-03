"""Mirror duplicate detection with differing skeletons (§8.6 + fix).

Real-world scenario: an SBP transfer from T-Bank to Yandex Debit shows up
with completely different descriptions in the two banks' statements:

  • Sender side (Тинькоф Дебет, committed):
      "Внешний перевод по номеру телефона +79222624977"
      skeleton → "внешний перевод номеру телефона <PHONE>"

  • Receiver side (Яндекс Дебет, new import):
      "Входящий перевод СБП, Григорий Александрович Ш., +7 932 630-24 25, Т-Банк"
      skeleton → "входящий перевод сбп <PERSON> ш <PHONE> т банк"

Before the fix, `_detect_committed_duplicates` applied the skeleton guard
to the mirror index entry and skipped the match — the Яндекс Дебет import
row was left as 'warning' instead of 'duplicate'.

Fix: skeleton guard is skipped for mirror matches (tx.account_id != row's
account_id), because the committed tx's skeleton reflects the SENDER's
bank wording, not the RECEIVER's.  The §8.6 guard is preserved for
same-account re-import (row's account_id == tx.account_id).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.account import Account
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.services.transfer_matcher_service import TransferMatcherService
from tests.conftest import make_transaction


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tinkoff_account(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id, name="Тинькоф Дебет",
        account_type="main", balance=Decimal("50000"),
        currency="RUB", is_active=True, is_credit=False,
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def yandex_account(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id, name="Яндекс Дебет",
        account_type="main", balance=Decimal("80000"),
        currency="RUB", is_active=True, is_credit=False,
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def matcher(db):
    return TransferMatcherService(db)


def _session(db, user, account):
    s = ImportSession(
        user_id=user.id, account_id=account.id,
        filename=f"sess-{account.id}.csv",
        file_content="", file_hash=f"h-{account.id}",
        source_type="csv", status="preview_ready",
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


_row_counter: dict[int, int] = {}


def _import_row(db, session, *, direction, amount, when, description, skeleton):
    idx = _row_counter.get(session.id, 0)
    _row_counter[session.id] = idx + 1
    row = ImportRow(
        session_id=session.id, row_index=idx, status="ready",
        raw_data_json={},
        normalized_data_json={
            "operation_type": "regular",
            "account_id": session.account_id,
            "direction": direction,
            "amount": str(amount),
            "date": when.isoformat(),
            "description": description,
            "skeleton": skeleton,
        },
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

AMOUNT = Decimal("4000.00")
WHEN = datetime(2026, 2, 27, 14, 21, tzinfo=timezone.utc)

TINKOFF_SKELETON = "внешний перевод номеру телефона <PHONE>"
YANDEX_SKELETON = "входящий перевод сбп <PERSON> ш <PHONE> т банк"


class TestMirrorDedupDifferentSkeletons:
    def test_phantom_income_with_different_skeleton_marked_duplicate(
        self, db, user, tinkoff_account, yandex_account, matcher,
    ):
        """Spec §8.5 branch B (v1.20).

        When user commits Tinkoff→Yandex transfer, `_create_transfer_pair`
        creates BOTH halves: real expense on Tinkoff AND phantom income on
        Yandex (both physical Transaction records). Phantom inherits the
        sender-bank skeleton.

        Later, user imports the Yandex statement. The income row has
        Yandex-bank skeleton (different wording). It must still be marked
        duplicate via branch B (same-account phantom-transfer-income),
        because skeleton check is intentionally suppressed for phantom
        income (skeletons differ by design across banks).
        """
        # Committed expense on Тинькоф (sender side) AND phantom income on
        # Яндекс — real `_create_transfer_pair` would create both, linked
        # via `transfer_pair_id`. Without the link, the main matcher would
        # pick them as orphan candidates and pair the new import row to the
        # phantom income via cross_session match before _detect_committed_
        # duplicates gets a chance to run branch B.
        tx_expense = make_transaction(
            db,
            user_id=user.id,
            account_id=tinkoff_account.id,
            target_account_id=yandex_account.id,
            amount=AMOUNT,
            currency="RUB",
            type="expense",
            operation_type="transfer",
            description="Внешний перевод по номеру телефона +79222624977",
            normalized_description="внешний перевод по номеру телефона +79222624977",
            skeleton=TINKOFF_SKELETON,
            transaction_date=WHEN,
        )
        tx_income = make_transaction(
            db,
            user_id=user.id,
            account_id=yandex_account.id,
            target_account_id=tinkoff_account.id,
            amount=AMOUNT,
            currency="RUB",
            type="income",
            operation_type="transfer",
            description="Внешний перевод по номеру телефона +79222624977",
            normalized_description="внешний перевод по номеру телефона +79222624977",
            skeleton=TINKOFF_SKELETON,
            transaction_date=WHEN,
        )
        tx_expense.transfer_pair_id = tx_income.id
        tx_income.transfer_pair_id = tx_expense.id
        db.add(tx_expense); db.add(tx_income); db.commit()

        # New import session for Яндекс Дебет — the receiving side.
        sess_y = _session(db, user, yandex_account)
        income_row = _import_row(
            db, sess_y,
            direction="income",
            amount=AMOUNT,
            when=WHEN,
            description="Входящий перевод СБП, Григорий Александрович Ш., +7 932 630-24 25, Т-Банк",
            skeleton=YANDEX_SKELETON,
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(income_row)
        assert income_row.status == "duplicate", (
            "Branch B: phantom transfer-income on the same account must be "
            "detected as duplicate even when the row's skeleton differs from "
            "the phantom's (skeleton check is suppressed for phantom branch)."
        )
        tm = (income_row.normalized_data_json or {}).get("transfer_match", {})
        # Branch B is same-account, so is_secondary must be False
        # (UI shows «Дубль · другая сессия», not a self-loop pairLabel).
        assert tm.get("is_secondary") is False
        assert tm.get("match_source") == "committed_tx_duplicate"
        assert tm.get("match_branch") == "B"

    def test_same_account_different_skeletons_not_duplicate(
        self, db, user, yandex_account, matcher,
    ):
        """Regression: same-account skeleton guard must remain intact.

        Two different operations on the same account with the same amount and
        date but different skeletons must NOT be merged into a duplicate.
        The guard in _detect_committed_duplicates must still fire when
        is_mirror=False.
        """
        # Committed transaction on the same account — different skeleton.
        make_transaction(
            db,
            user_id=user.id,
            account_id=yandex_account.id,
            amount=AMOUNT,
            currency="RUB",
            type="income",
            operation_type="regular",
            description="Входящий платёж за услуги ООО Ромашка",
            normalized_description="входящий платёж за услуги ооо ромашка",
            skeleton="входящий платёж услуги <ORG>",
            transaction_date=WHEN,
        )

        # Import row on the SAME account — different skeleton (different operation).
        sess_y = _session(db, user, yandex_account)
        income_row = _import_row(
            db, sess_y,
            direction="income",
            amount=AMOUNT,
            when=WHEN,
            description="Входящий перевод СБП, Григорий Александрович Ш., +7 932 630-24 25, Т-Банк",
            skeleton=YANDEX_SKELETON,
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(income_row)
        assert income_row.status != "duplicate", (
            "Same-account skeleton guard must still block false duplicate detection "
            "when skeletons differ — these are two unrelated income operations."
        )


class TestCreditAccountRepaymentDedup:
    """Spec §8.5 branch D + §8.9 (v1.20).

    Credit account repayments appear as expense in the bank statement
    (debt decreases = credit limit consumed → returned), while the
    transfer model creates a phantom income on the receiving account.

    Real case: Tinkoff Дебет commits expense→Yandex Сплит (credit_card).
    When Yandex Сплит statement is imported, «Погашение основного долга»
    is classified as expense (not income). Branch D activates ONLY when:
      • target account_type ∈ {credit_card, installment_card, loan}
      • row.description contains a credit-keyword
      • identifier-mismatch absent (or no shared identifier type)
      • anti-transfer keyword absent
    """

    def test_credit_repayment_marked_duplicate_via_branch_D(
        self, db, user, tinkoff_account, yandex_account, matcher,
    ):
        """Committed debit→credit transfer must detect the credit statement's
        repayment row as duplicate even when the credit bank classifies the
        repayment as expense (direction mismatch vs transfer model's income).
        """
        AMOUNT = Decimal("20000.00")
        WHEN = datetime(2025, 12, 12, 17, 28, tzinfo=timezone.utc)

        # Promote yandex_account to credit_card so branch D activates.
        yandex_account.account_type = "credit_card"
        db.add(yandex_account)
        db.commit()

        # Committed transfer pair: expense on Tinkoff Дебет + phantom income
        # on Yandex Сплит (credit). Real `_create_transfer_pair` links both
        # via `transfer_pair_id`.
        tx_expense = make_transaction(
            db,
            user_id=user.id,
            account_id=tinkoff_account.id,        # debit account
            target_account_id=yandex_account.id,  # credit account (credit_card)
            amount=AMOUNT,
            currency="RUB",
            type="expense",
            operation_type="transfer",
            description="Погашение основного долга по договору №КС20251126483806054311",
            normalized_description="погашение основного долга по договору кс20251126483806054311",
            skeleton="погашение основного долга договор <CONTRACT>",
            transaction_date=WHEN,
        )
        tx_phantom = make_transaction(
            db,
            user_id=user.id,
            account_id=yandex_account.id,
            target_account_id=tinkoff_account.id,
            amount=AMOUNT,
            currency="RUB",
            type="income",
            operation_type="transfer",
            description="Погашение основного долга по договору №КС20251126483806054311",
            normalized_description="погашение основного долга по договору кс20251126483806054311",
            skeleton="погашение основного долга договор <CONTRACT>",
            transaction_date=WHEN,
        )
        tx_expense.transfer_pair_id = tx_phantom.id
        tx_phantom.transfer_pair_id = tx_expense.id
        db.add(tx_expense); db.add(tx_phantom); db.commit()

        # New import of the credit account statement.
        # The bank classifies repayment as EXPENSE (debt reduction = credit used → returned).
        sess_credit = _session(db, user, yandex_account)
        repayment_row = _import_row(
            db, sess_credit,
            direction="expense",   # ← credit bank's perspective: expense
            amount=AMOUNT,
            when=WHEN,
            description="Погашение основного долга по договору №КС20251126483806054311",
            skeleton="погашение основного долга договор <CONTRACT>",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(repayment_row)
        assert repayment_row.status == "duplicate", (
            "Branch D: mirror-expense for credit-target with credit-keyword "
            "must mark this row as duplicate of the committed debit→credit transfer."
        )
        tm = (repayment_row.normalized_data_json or {}).get("transfer_match", {})
        assert tm.get("match_branch") == "D"
        assert tm.get("is_secondary") is True
        assert tm.get("match_source") == "committed_tx_duplicate"
