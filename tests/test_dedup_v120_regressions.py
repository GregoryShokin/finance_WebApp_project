"""Regression tests for spec v1.20: four-branch _detect_committed_duplicates +
FeeMatcherService.

Each scenario corresponds to a real bug observed on user pavel.shokin1991
(import sessions 153/154/156) and closes one specific class of false-positive
duplicate or false-negative pairing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.account import Account
from app.models.bank import Bank
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.transaction import Transaction
from app.services.fee_matcher_service import FeeMatcherService
from app.services.transfer_matcher_service import TransferMatcherService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def matcher(db):
    return TransferMatcherService(db)


@pytest.fixture
def fee_matcher(db):
    return FeeMatcherService(db)


@pytest.fixture
def sber_account(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id, name="Сбер дебет",
        account_type="main", balance=Decimal("50000"),
        currency="RUB", is_active=True, is_credit=False,
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def tinkoff_credit(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id, name="Тинькоф кредитка",
        account_type="credit_card", balance=Decimal("0"),
        currency="RUB", is_active=True, is_credit=False,
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def tinkoff_debit(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id, name="Тинькоф дебет",
        account_type="main", balance=Decimal("50000"),
        currency="RUB", is_active=True, is_credit=False,
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


def _commit_pair(db, *, user, src, dst, amount, when, description, skeleton):
    """Helper: create a paired (expense, income) transfer with `transfer_pair_id`
    set on both — emulates the result of `TransferLinkingService.create_transfer_pair`.
    """
    tx_e = Transaction(
        user_id=user.id, account_id=src.id, target_account_id=dst.id,
        amount=amount, currency="RUB", type="expense", operation_type="transfer",
        description=description,
        normalized_description=description.lower(),
        skeleton=skeleton,
        transaction_date=when,
        affects_analytics=False,
    )
    tx_i = Transaction(
        user_id=user.id, account_id=dst.id, target_account_id=src.id,
        amount=amount, currency="RUB", type="income", operation_type="transfer",
        description=description,
        normalized_description=description.lower(),
        skeleton=skeleton,
        transaction_date=when,
        affects_analytics=False,
    )
    db.add(tx_e); db.add(tx_i); db.flush()
    tx_e.transfer_pair_id = tx_i.id
    tx_i.transfer_pair_id = tx_e.id
    db.commit()
    return tx_e, tx_i


def _row(db, session, *, direction, amount, when, description, skeleton, status="warning"):
    idx_q = db.query(ImportRow).filter(ImportRow.session_id == session.id).count()
    nd = {
        "operation_type": "regular",
        "account_id": session.account_id,
        "direction": direction,
        "amount": str(amount),
        "date": when.isoformat(),
        "description": description,
        "skeleton": skeleton,
    }
    row = ImportRow(
        session_id=session.id, row_index=idx_q, status=status,
        raw_data_json={}, normalized_data_json=nd,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def _session(db, user, account):
    s = ImportSession(
        user_id=user.id, account_id=account.id,
        filename=f"sess-{account.id}.csv",
        file_content="", file_hash=f"h-{account.id}",
        source_type="csv", status="preview_ready",
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# Bug 16216: ATM cash-withdrawal must NOT mirror-match a transfer
# (target=main account, anti-transfer keyword on row → branch D not activated)
# ---------------------------------------------------------------------------


class TestATMNotMirrorDuplicate:
    """Sber ATM cash withdrawal of 42 000 ₽ on the same day as a committed
    Tinkoff→Sber transfer of 42 000 ₽ must NOT be marked duplicate.

    Pre-v1.20: mirror+expense index under (target=Sber, expense, 42000) caught
    the ATM expense; skeleton guard was disabled for is_mirror=True.

    Post-v1.20: target.account_type='main' (not credit) → branch D not activated.
    Additionally, anti-transfer keyword 'atm' would block branch D anyway.
    """

    def test_atm_withdrawal_not_marked_duplicate_of_committed_transfer(
        self, db, user, sber_account, tinkoff_credit, matcher,
    ):
        AMOUNT = Decimal("42000.00")
        WHEN_TX = datetime(2026, 3, 13, 11, 57, tzinfo=timezone.utc)
        WHEN_ROW = datetime(2026, 3, 13, 13, 47, tzinfo=timezone.utc)  # ~2 hours later

        # Committed transfer Tinkoff кредитка → Sber дебет
        _commit_pair(
            db, user=user, src=tinkoff_credit, dst=sber_account,
            amount=AMOUNT, when=WHEN_TX,
            description="Внешний перевод по номеру телефона +79195599996",
            skeleton="внешний перевод номеру телефона <PHONE>",
        )

        # New Sber statement: ATM cash withdrawal — independent operation
        sess = _session(db, user, sber_account)
        atm_row = _row(
            db, sess,
            direction="expense",
            amount=AMOUNT,
            when=WHEN_ROW,
            description="ATM 60022829 VOLGODONSK RUS. Операция по карте ****7123",
            skeleton="atm 60022829 операция карте <CARD>",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(atm_row)
        assert atm_row.status != "duplicate", (
            "ATM cash withdrawal must not be marked duplicate of a phone transfer "
            "even though they share (account, expense, amount, ±2 days). "
            "Sber is account_type='main', so branch D (mirror+expense) is not "
            "activated for non-credit targets."
        )


# ---------------------------------------------------------------------------
# Bug 16312: contract-mismatch must reject mirror-expense match
# ---------------------------------------------------------------------------


class TestContractMismatchRejectsMirror:
    """«Досрочное погашение 8845» on Tinkoff debit must NOT be flagged as
    duplicate of a committed transfer with contract 5422638063.

    Even if branch D activated (e.g., target was credit), contract-token
    mismatch is a hard reject. In production, target=main here too, so
    branch D doesn't activate and the row stays as warning regardless.
    """

    def test_different_contracts_reject_mirror_match_when_target_is_credit(
        self, db, user, sber_account, tinkoff_credit, tinkoff_debit, matcher,
    ):
        """Strong test: even if target IS credit, contract mismatch reject still fires.

        Realistic scenario: user has TWO credit contracts on the same Сплит-style
        account. Same-amount payments to two different contracts on consecutive
        days. The committed one (contract A) must NOT match the new row referencing
        contract B.
        """
        AMOUNT = Decimal("20840.00")
        WHEN_TX = datetime(2026, 4, 17, 9, 41, tzinfo=timezone.utc)
        WHEN_ROW = datetime(2026, 4, 19, 9, 35, tzinfo=timezone.utc)  # ~2 days later

        # Promote tinkoff_debit to credit_card to test branch D contract guard.
        tinkoff_debit.account_type = "credit_card"
        db.add(tinkoff_debit); db.commit()

        # Committed transfer with contract 5422638063 onto tinkoff_debit (now credit-target)
        _commit_pair(
            db, user=user, src=tinkoff_credit, dst=tinkoff_debit,
            amount=AMOUNT, when=WHEN_TX,
            description="Внутренний перевод на договор 5422638063",
            skeleton="внутренний перевод договор <CONTRACT>",
        )

        # New row: payment to a DIFFERENT contract (8845876543) — different operation
        sess = _session(db, user, tinkoff_debit)
        row = _row(
            db, sess,
            direction="expense",
            amount=AMOUNT,
            when=WHEN_ROW,
            description="Досрочное погашение по договору 8845876543",
            skeleton="досрочное погашение договор <CONTRACT>",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(row)
        assert row.status != "duplicate", (
            "Different contract numbers (8845876543 vs 5422638063) must hard-reject "
            "the mirror match even though target is credit and credit-keyword "
            "(«погашение») is present in row description."
        )

    def test_main_target_blocks_branch_D_regardless_of_contract(
        self, db, user, sber_account, tinkoff_credit, tinkoff_debit, matcher,
    ):
        """Production case 16312: target.account_type='main' — branch D never
        activates, contract-guard never even runs. The narrow activation of
        branch D for credit-targets only is what closes the production bug.
        """
        AMOUNT = Decimal("20840.00")
        WHEN_TX = datetime(2026, 4, 17, 9, 41, tzinfo=timezone.utc)
        WHEN_ROW = datetime(2026, 4, 19, 9, 35, tzinfo=timezone.utc)

        # tinkoff_debit stays as account_type='main'.
        _commit_pair(
            db, user=user, src=tinkoff_credit, dst=tinkoff_debit,
            amount=AMOUNT, when=WHEN_TX,
            description="Внутренний перевод на договор 5422638063",
            skeleton="внутренний перевод договор <CONTRACT>",
        )

        sess = _session(db, user, tinkoff_debit)
        row = _row(
            db, sess,
            direction="expense", amount=AMOUNT, when=WHEN_ROW,
            description="Досрочное погашение 8845",
            skeleton="досрочное погашение 8845",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(row)
        assert row.status != "duplicate", (
            "main-target accounts must never trigger branch D. Production case "
            "16312: «Досрочное погашение 8845» on tinkoff_debit (main) — must "
            "not be glued to the committed transfer on the same account+amount."
        )


# ---------------------------------------------------------------------------
# Bug 16210/16212: 1-to-1 assignment with closest-time tie-breaker
# ---------------------------------------------------------------------------


class TestOneToOneAssignment:
    """Two repeated transfers of 200 ₽ in adjacent minutes (18:01 and 18:02)
    create two phantom income transactions on the receiving account. When the
    receiving statement is imported with two rows (also at 18:01 and 18:02),
    each row must match its OWN closest-time phantom — not both to the first
    one in the index.

    Pre-v1.20: `for tx in matches: ... break` picked first available; both
    rows matched the same tx 5057 (18:01).
    Post-v1.20: greedy 1-to-1 with `used_tx_ids` set + sort by |Δseconds| ASC.
    """

    def test_two_repeated_transfers_get_distinct_partners(
        self, db, user, sber_account, tinkoff_credit, matcher,
    ):
        AMOUNT = Decimal("200.00")
        T1 = datetime(2026, 3, 18, 15, 1, tzinfo=timezone.utc)  # 18:01 МСК
        T2 = datetime(2026, 3, 18, 15, 2, tzinfo=timezone.utc)  # 18:02 МСК

        # Two separate committed transfer pairs
        _, tx_phantom1 = _commit_pair(
            db, user=user, src=tinkoff_credit, dst=sber_account,
            amount=AMOUNT, when=T1,
            description="Внешний перевод по номеру телефона +79195599996",
            skeleton="внешний перевод номеру телефона <PHONE>",
        )
        _, tx_phantom2 = _commit_pair(
            db, user=user, src=tinkoff_credit, dst=sber_account,
            amount=AMOUNT, when=T2,
            description="Внешний перевод по номеру телефона +79195599996",
            skeleton="внешний перевод номеру телефона <PHONE>",
        )

        # Sber statement: two income rows at the matching minutes
        sess = _session(db, user, sber_account)
        row1 = _row(
            db, sess,
            direction="income", amount=AMOUNT, when=T1,
            description="Перевод от Ш. Павел Александрович. Операция по карте ****7123",
            skeleton="перевод ш <PERSON> операция карте <CARD>",
        )
        row2 = _row(
            db, sess,
            direction="income", amount=AMOUNT, when=T2,
            description="Перевод от Ш. Павел Александрович. Операция по карте ****7123",
            skeleton="перевод ш <PERSON> операция карте <CARD>",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(row1); db.refresh(row2)
        assert row1.status == "duplicate" and row2.status == "duplicate", (
            "Both rows must be marked duplicate (each matches its own phantom)."
        )
        m1 = (row1.normalized_data_json or {}).get("transfer_match", {})
        m2 = (row2.normalized_data_json or {}).get("transfer_match", {})
        # Each row must point to a DISTINCT phantom (no double-binding).
        assert m1.get("matched_tx_id") != m2.get("matched_tx_id"), (
            "Greedy 1-to-1 + closest-time tie-breaker must assign each row to a "
            "distinct phantom; bug 16210/16212 had both rows pointing to the same tx."
        )
        # 18:01 row must match the 18:01 phantom; 18:02 row matches 18:02 phantom.
        assert m1.get("matched_tx_id") == tx_phantom1.id
        assert m2.get("matched_tx_id") == tx_phantom2.id


# ---------------------------------------------------------------------------
# Branch D activation: Сплит credit-keyword case (positive test)
# ---------------------------------------------------------------------------


class TestSplitCreditKeywordActivatesBranchD:
    """Yandex Дебет → Yandex Сплит «Погашение основного долга» — credit
    repayment that legitimately should be detected as duplicate via branch D.
    """

    def test_credit_repayment_correctly_detected_via_branch_D(
        self, db, user, sber_account, tinkoff_credit, matcher,
    ):
        AMOUNT = Decimal("18000.00")
        WHEN = datetime(2025, 12, 12, 14, 28, tzinfo=timezone.utc)

        # Committed pair: Sber (debit) → Tinkoff credit
        _commit_pair(
            db, user=user, src=sber_account, dst=tinkoff_credit,
            amount=AMOUNT, when=WHEN,
            description="Перевод на договор 5422638063",
            skeleton="перевод договор <CONTRACT>",
        )

        # Tinkoff кредитка statement: «Погашение основного долга» as expense.
        sess = _session(db, user, tinkoff_credit)
        repayment = _row(
            db, sess,
            direction="expense", amount=AMOUNT, when=WHEN,
            description="Погашение основного долга по договору 5422638063",
            skeleton="погашение основного долга договор <CONTRACT>",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(repayment)
        assert repayment.status == "duplicate"
        tm = (repayment.normalized_data_json or {}).get("transfer_match", {})
        assert tm.get("match_branch") == "D"
        assert tm.get("is_secondary") is True


# ---------------------------------------------------------------------------
# FeeMatcher §8.10: transfer-with-fee suspect-pair
# ---------------------------------------------------------------------------


class TestFeeAwareSuspectPair:
    """Cross-bank transfer with bank-side fee: −37 000 ₽ from Sber, +36 943 ₽
    on Tinkoff (delta 57 ₽, same minute, both transfer-keywords, no anti-
    transfer keyword). FeeMatcher should emit a suspect-pair on both rows.
    """

    def test_fee_pair_suggested_when_income_lt_expense_within_tolerance(
        self, db, user, sber_account, tinkoff_debit, fee_matcher,
    ):
        T = datetime(2026, 3, 12, 4, 54, tzinfo=timezone.utc)  # 07:54 МСК

        sess_a = _session(db, user, sber_account)
        sess_b = _session(db, user, tinkoff_debit)
        row_exp = _row(
            db, sess_a,
            direction="expense", amount=Decimal("37000.00"), when=T,
            description="Внешний перевод по номеру телефона +79195599996",
            skeleton="внешний перевод номеру телефона <PHONE>",
        )
        row_inc = _row(
            db, sess_b,
            direction="income", amount=Decimal("36943.00"), when=T,
            description="Перевод от Ш. Павел Александрович. Операция по карте ****7818",
            skeleton="перевод ш <PERSON> операция карте <CARD>",
        )

        pairs = fee_matcher.detect_for_user(user_id=user.id)
        assert len(pairs) == 1
        p = pairs[0]
        assert p.expense_row_id == row_exp.id
        assert p.income_row_id == row_inc.id
        assert p.delta_amount == Decimal("57.00")

        db.refresh(row_exp); db.refresh(row_inc)
        # Both rows have the suspect-pair metadata; status is unchanged
        # (no auto-trust per §8.10).
        assert row_exp.status == "warning"
        assert row_inc.status == "warning"
        suspect_e = (row_exp.normalized_data_json or {}).get("fee_suspect_pair")
        suspect_i = (row_inc.normalized_data_json or {}).get("fee_suspect_pair")
        assert suspect_e is not None and suspect_i is not None
        assert suspect_e.get("partner_row_id") == row_inc.id
        assert suspect_i.get("partner_row_id") == row_exp.id

    def test_fee_pair_rejected_when_income_greater_than_expense(
        self, db, user, sber_account, tinkoff_debit, fee_matcher,
    ):
        """Multi-source SBP (income > expense) is sсope-out per §8.11 —
        bank cannot legitimately add money during transfer."""
        T = datetime(2026, 3, 12, 4, 54, tzinfo=timezone.utc)
        sess_a = _session(db, user, sber_account)
        sess_b = _session(db, user, tinkoff_debit)
        _row(db, sess_a,
             direction="expense", amount=Decimal("37000.00"), when=T,
             description="Внешний перевод по номеру телефона +79195599996",
             skeleton="внешний перевод номеру телефона <PHONE>")
        _row(db, sess_b,
             direction="income", amount=Decimal("37052.00"), when=T,
             description="Перевод от Ш. Павел Александрович",
             skeleton="перевод ш <PERSON>")

        pairs = fee_matcher.detect_for_user(user_id=user.id)
        assert len(pairs) == 0, (
            "Income > expense (multi-source funding) is out of fee-matcher scope."
        )

    def test_fee_pair_rejected_when_delta_above_tolerance(
        self, db, user, sber_account, tinkoff_debit, fee_matcher,
    ):
        """Delta > min(5%, 500₽) cannot be auto-classified as fee."""
        T = datetime(2026, 3, 12, 4, 54, tzinfo=timezone.utc)
        sess_a = _session(db, user, sber_account)
        sess_b = _session(db, user, tinkoff_debit)
        _row(db, sess_a,
             direction="expense", amount=Decimal("10000.00"), when=T,
             description="Внешний перевод по номеру телефона +79195599996",
             skeleton="внешний перевод номеру телефона <PHONE>")
        _row(db, sess_b,
             direction="income", amount=Decimal("9000.00"), when=T,  # delta=1000 > 500
             description="Перевод от Ш. Павел Александрович",
             skeleton="перевод ш <PERSON>")

        pairs = fee_matcher.detect_for_user(user_id=user.id)
        assert len(pairs) == 0

    def test_fee_pair_rejected_when_time_diff_above_60s(
        self, db, user, sber_account, tinkoff_debit, fee_matcher,
    ):
        """≥61 sec between sides is not a fee transfer."""
        T1 = datetime(2026, 3, 12, 4, 54, 0, tzinfo=timezone.utc)
        T2 = datetime(2026, 3, 12, 4, 56, 0, tzinfo=timezone.utc)  # +120 sec
        sess_a = _session(db, user, sber_account)
        sess_b = _session(db, user, tinkoff_debit)
        _row(db, sess_a,
             direction="expense", amount=Decimal("5000.00"), when=T1,
             description="Внешний перевод по номеру телефона +79195599996",
             skeleton="внешний перевод номеру телефона <PHONE>")
        _row(db, sess_b,
             direction="income", amount=Decimal("4980.00"), when=T2,
             description="Перевод от Ш. Павел Александрович",
             skeleton="перевод ш <PERSON>")

        pairs = fee_matcher.detect_for_user(user_id=user.id)
        assert len(pairs) == 0
