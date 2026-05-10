"""Regression: credit-repayment symmetry across Дебет ↔ credit-account
sessions (spec v1.26, §9.10 + §8.5 branch B + §12.10).

Live trigger 2026-05-09: user imported Yandex Дебет + Yandex Сплит and
Ozon Дебет + Ozon Кредитка. The Дебет sides correctly became
`operation_type='transfer'` with `target_account_id` resolved by contract
(bank_mechanics path). The credit-side income rows («Погашение основного
долга», «Погашение кредита по договору»), however, ended up
`status='excluded'` BUT without `transfer_match` — silently dropped from
the moderator view, no UI indication of which Дебет row they pair with.

Two underlying bugs:

  A. `apply_bank_mechanics` set `status='excluded'` BEFORE the cross-
     session transfer matcher had a chance to pair the row. The matcher
     filters `status IN ('ready','warning','error')`, so excluded rows
     never receive `transfer_match`. → fix: defer to a pending flag and
     finalize after the matcher.

  B. `_score_pair`'s pro-transfer guard required at least one side to
     contain «перевод» / «transfer» / similar. Credit-repayment phrasings
     («погашение основного долга», «погашение кредита») weren't in the
     set → score=0.0, no pair formed even when both rows looked
     identical. → fix: extend the guard with credit-loan vocabulary.

Tests below verify both fixes end-to-end across the four canonical
flows: cross-session pair, branch-B duplicate against committed phantom,
deferred-then-paired exclusion path, and orphan-then-excluded fallback.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.account import Account
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.repositories.import_repository import ImportRepository
from app.services.import_post_processor import ImportPostProcessor
from app.services.transfer_matcher_service import TransferMatcherService
from tests.conftest import make_transaction


# ---------------------------------------------------------------------------
# Fixtures — accounts mirror the live data layout (account_type set, but
# `is_credit=False` for the credit-style accounts as observed in the user's
# DB; the matcher's `is_credit=False` JOIN filter passes them through).
# ---------------------------------------------------------------------------

@pytest.fixture
def yandex_debit(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id, name="Яндекс Дебет",
        account_type="main", balance=Decimal("100000"),
        currency="RUB", is_active=True, is_credit=False,
        contract_number="Э20240626883885586",
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def yandex_split(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id, name="Яндекс Сплит",
        account_type="installment_card", balance=Decimal("-3210"),
        currency="RUB", is_active=True, is_credit=False,
        contract_number="КС20251126483806054311",
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def ozon_debit(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id, name="Озон Дебет",
        account_type="main", balance=Decimal("50000"),
        currency="RUB", is_active=True, is_credit=False,
        contract_number="2025-11-27-KK",
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def ozon_credit(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id, name="Озон Кредитка",
        account_type="credit_card", balance=Decimal("-9157"),
        currency="RUB", is_active=True, is_credit=False,
        contract_number="2025-11-27-KK-07880171045845068514",
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def matcher(db):
    return TransferMatcherService(db)


@pytest.fixture
def post_proc(db):
    return ImportPostProcessor(db, import_repo=ImportRepository(db))


def _session(db, user, account):
    s = ImportSession(
        user_id=user.id, account_id=account.id,
        filename=f"sess-{account.id}.csv",
        file_content="", file_hash=f"h-{account.id}",
        source_type="csv", status="preview_ready",
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


_row_idx: dict[int, int] = {}


def _import_row(db, session, *, direction, amount, when, description,
                skeleton=None, op_type="regular", tokens=None,
                pending_exclude=False, target_account_id=None):
    idx = _row_idx.get(session.id, 0)
    _row_idx[session.id] = idx + 1
    nd = {
        "operation_type": op_type,
        "account_id": session.account_id,
        "direction": direction,
        "amount": str(amount),
        "date": when.isoformat(),
        "transaction_date": when.isoformat(),
        "description": description,
        "skeleton": skeleton or description.lower(),
        "fingerprint": f"fp-{session.account_id}-{direction}-{amount}-{idx}",
        "tokens": tokens or {},
    }
    if target_account_id is not None:
        nd["target_account_id"] = target_account_id
    if pending_exclude:
        nd["bank_mechanics_pending_exclude"] = True
    row = ImportRow(
        session_id=session.id, row_index=idx, status="ready",
        raw_data_json={}, normalized_data_json=nd,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


# Common amounts / timestamps mirroring the live cases.
WHEN_YANDEX = datetime(2026, 2, 10, 12, 0, tzinfo=timezone.utc)
WHEN_OZON = datetime(2026, 2, 12, 12, 0, tzinfo=timezone.utc)
AMT_YANDEX = Decimal("3210.00")
AMT_OZON_SMALL = Decimal("594.00")
AMT_OZON_LARGE = Decimal("8563.00")


# ---------------------------------------------------------------------------
# 1. Yandex Дебет + Yandex Сплит cross-session pair (§12.10)
# ---------------------------------------------------------------------------

class TestCrossSessionPairYandex:
    def test_credit_repayment_pair_forms_across_sessions(
        self, db, user, yandex_debit, yandex_split, matcher,
    ):
        """v1.26 fix: «погашение основного долга» on both sides must satisfy
        `_score_pair`'s pro-transfer guard via `_CREDIT_PAIR_KEYWORDS` and
        form a cross-session pair — both rows 'ready' with transfer_match
        pointing at each other."""
        sess_d = _session(db, user, yandex_debit)
        sess_s = _session(db, user, yandex_split)
        debit_expense = _import_row(
            db, sess_d,
            direction="expense", amount=AMT_YANDEX, when=WHEN_YANDEX,
            description="Погашение основного долга по договору № КС20251126483806054311",
            skeleton="погашение основного долга <CONTRACT>",
            op_type="transfer",
            tokens={"contract": "КС20251126483806054311"},
            target_account_id=yandex_split.id,
        )
        # Сплит-side row — description has «по договору» but no number.
        # tokens.contract is None; the matcher must fall back to
        # account.contract_number for shared-contract bonus + skeleton-guard.
        split_income = _import_row(
            db, sess_s,
            direction="income", amount=AMT_YANDEX, when=WHEN_YANDEX,
            description="Погашение основного долга по договору",
            skeleton="погашение основного долга договору",
            op_type="transfer",
            tokens={"contract": None},
            pending_exclude=True,  # set by apply_bank_mechanics in real flow
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(debit_expense); db.refresh(split_income)
        # Both sides primary 'ready' (§12.10 cross-session pair semantics).
        assert debit_expense.status == "ready"
        assert split_income.status == "ready"
        # transfer_match populated on both sides — no «несвязанный income».
        d_tm = (debit_expense.normalized_data_json or {}).get("transfer_match") or {}
        s_tm = (split_income.normalized_data_json or {}).get("transfer_match") or {}
        assert d_tm.get("matched_row_id") == split_income.id
        assert s_tm.get("matched_row_id") == debit_expense.id
        assert d_tm.get("match_source") == "cross_session"
        assert s_tm.get("match_source") == "cross_session"
        # target_account_id resolved on both sides.
        assert (debit_expense.normalized_data_json or {}).get("target_account_id") == yandex_split.id
        assert (split_income.normalized_data_json or {}).get("target_account_id") == yandex_debit.id


# ---------------------------------------------------------------------------
# 2. Ozon symmetric coverage (different skeletons, shared contract)
# ---------------------------------------------------------------------------

class TestCrossSessionPairOzon:
    def test_ozon_credit_repayment_pair_forms(
        self, db, user, ozon_debit, ozon_credit, matcher,
    ):
        """Ozon books both sides with «Погашение кредита по договору» —
        skeletons match between Дебет and Кредитка statements. Contract
        token is identical on both sides."""
        sess_d = _session(db, user, ozon_debit)
        sess_c = _session(db, user, ozon_credit)
        debit_expense = _import_row(
            db, sess_d,
            direction="expense", amount=AMT_OZON_SMALL, when=WHEN_OZON,
            description="Погашение кредита по договору №2025-11-27-KK",
            skeleton="погашение кредита договору <CONTRACT>",
            op_type="transfer",
            tokens={"contract": "2025-11-27-KK"},
            target_account_id=ozon_credit.id,
        )
        credit_income = _import_row(
            db, sess_c,
            direction="income", amount=AMT_OZON_SMALL, when=WHEN_OZON,
            description="Погашение кредита по договору №2025-11-27-KK",
            skeleton="погашение кредита договору <CONTRACT>",
            op_type="transfer",
            tokens={"contract": "2025-11-27-KK"},
            pending_exclude=True,
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(debit_expense); db.refresh(credit_income)
        assert debit_expense.status == "ready"
        assert credit_income.status == "ready"
        d_tm = (debit_expense.normalized_data_json or {}).get("transfer_match") or {}
        c_tm = (credit_income.normalized_data_json or {}).get("transfer_match") or {}
        assert d_tm.get("matched_row_id") == credit_income.id
        assert c_tm.get("matched_row_id") == debit_expense.id


# ---------------------------------------------------------------------------
# 3. Branch B (committed phantom income) — §8.5 v1.20
# ---------------------------------------------------------------------------

class TestBranchBCommittedPhantom:
    def test_split_income_marked_duplicate_against_phantom(
        self, db, user, yandex_debit, yandex_split, matcher,
    ):
        """When the user committed the Дебет statement first,
        `_create_transfer_pair` already produced a phantom income on the
        Сплит account. A later import of the Сплит statement must mark
        the matching income row as duplicate via branch B (skeletons
        differ across banks; the branch suppresses skeleton check)."""
        # Committed pair: real expense on Дебет + phantom income on Сплит,
        # both linked via transfer_pair_id.
        tx_expense = make_transaction(
            db, user_id=user.id,
            account_id=yandex_debit.id,
            target_account_id=yandex_split.id,
            amount=AMT_YANDEX, currency="RUB",
            type="expense", operation_type="transfer",
            description="Погашение основного долга по договору № КС20251126483806054311",
            normalized_description="погашение основного долга по договору <CONTRACT>",
            skeleton="погашение основного долга <CONTRACT>",
            transaction_date=WHEN_YANDEX,
        )
        tx_phantom = make_transaction(
            db, user_id=user.id,
            account_id=yandex_split.id,
            target_account_id=yandex_debit.id,
            amount=AMT_YANDEX, currency="RUB",
            type="income", operation_type="transfer",
            description="Погашение основного долга по договору № КС20251126483806054311",
            normalized_description="погашение основного долга по договору <CONTRACT>",
            skeleton="погашение основного долга <CONTRACT>",
            transaction_date=WHEN_YANDEX,
        )
        tx_expense.transfer_pair_id = tx_phantom.id
        tx_phantom.transfer_pair_id = tx_expense.id
        db.add(tx_expense); db.add(tx_phantom); db.commit()

        # Now import the Сплит statement — matching income row.
        sess_s = _session(db, user, yandex_split)
        split_income = _import_row(
            db, sess_s,
            direction="income", amount=AMT_YANDEX, when=WHEN_YANDEX,
            description="Погашение основного долга по договору",
            skeleton="погашение основного долга договору",
            op_type="transfer",
            tokens={"contract": None},
            pending_exclude=True,
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(split_income)
        assert split_income.status == "duplicate", (
            "Branch B: Сплит-side income matching the committed phantom "
            "must be marked duplicate."
        )
        tm = (split_income.normalized_data_json or {}).get("transfer_match") or {}
        assert tm.get("match_source") == "committed_tx_duplicate"
        assert tm.get("match_branch") == "B"
        assert tm.get("matched_tx_id") == tx_phantom.id
        # is_secondary=False for branch B (same-account, not a mirror).
        assert tm.get("is_secondary") is False


# ---------------------------------------------------------------------------
# 4. finalize_bank_mechanics_exclusions — paired vs orphan handling
# ---------------------------------------------------------------------------

class TestFinalizeBankMechanicsExclusions:
    def test_paired_row_keeps_status_and_clears_pending_flag(
        self, db, user, yandex_debit, yandex_split, matcher, post_proc,
    ):
        """When the matcher attached a transfer_match to a row carrying
        bank_mechanics_pending_exclude, finalize must clear the flag and
        leave the row's status untouched (it's now part of a visible
        pair, not silently excluded)."""
        sess_d = _session(db, user, yandex_debit)
        sess_s = _session(db, user, yandex_split)
        _import_row(
            db, sess_d,
            direction="expense", amount=AMT_YANDEX, when=WHEN_YANDEX,
            description="Погашение основного долга по договору № КС20251126483806054311",
            skeleton="погашение основного долга <CONTRACT>",
            op_type="transfer",
            tokens={"contract": "КС20251126483806054311"},
            target_account_id=yandex_split.id,
        )
        split_row = _import_row(
            db, sess_s,
            direction="income", amount=AMT_YANDEX, when=WHEN_YANDEX,
            description="Погашение основного долга по договору",
            skeleton="погашение основного долга договору",
            op_type="transfer",
            tokens={"contract": None},
            pending_exclude=True,
        )

        matcher.match_transfers_for_user(user_id=user.id)
        post_proc.finalize_bank_mechanics_exclusions(user_id=user.id)

        db.refresh(split_row)
        nd = split_row.normalized_data_json or {}
        # Pending flag cleared.
        assert "bank_mechanics_pending_exclude" not in nd
        # Status NOT excluded — matcher set it 'ready' as cross-session pair.
        assert split_row.status == "ready"
        assert nd.get("transfer_match") is not None

    def test_orphan_row_falls_back_to_excluded(
        self, db, user, yandex_split, matcher, post_proc,
    ):
        """If no Дебет partner exists in any active or committed scope, the
        finalize pass must apply the original safety net and set
        status='excluded' — committing the credit-side phantom alone would
        double-credit the Сплит balance when the Дебет statement arrives
        later."""
        sess_s = _session(db, user, yandex_split)
        orphan = _import_row(
            db, sess_s,
            direction="income", amount=AMT_YANDEX, when=WHEN_YANDEX,
            description="Погашение основного долга по договору",
            skeleton="погашение основного долга договору",
            op_type="transfer",
            tokens={"contract": None},
            pending_exclude=True,
        )

        matcher.match_transfers_for_user(user_id=user.id)
        post_proc.finalize_bank_mechanics_exclusions(user_id=user.id)

        db.refresh(orphan)
        nd = orphan.normalized_data_json or {}
        assert orphan.status == "excluded", (
            "Orphan credit-side phantom-mirror with no matcher partner "
            "must fall back to status='excluded' (§9.10 safety net)."
        )
        # Pending flag is cleared (decision finalized).
        assert "bank_mechanics_pending_exclude" not in nd
        # No transfer_match was attached.
        assert nd.get("transfer_match") is None

    def test_finalize_is_noop_without_pending_flag(
        self, db, user, yandex_split, post_proc,
    ):
        """Rows that never had the pending flag must be untouched by
        finalize — it's strictly a deferred-decision finalizer."""
        sess_s = _session(db, user, yandex_split)
        regular = _import_row(
            db, sess_s,
            direction="income", amount=Decimal("100"), when=WHEN_YANDEX,
            description="Возврат от Магнита",
            skeleton="возврат магнит",
        )

        post_proc.finalize_bank_mechanics_exclusions(user_id=user.id)

        db.refresh(regular)
        assert regular.status == "ready"


# ---------------------------------------------------------------------------
# 5. Negative regression: scoring guard expansion stays narrow
# ---------------------------------------------------------------------------

class TestPairGuardStaysNarrow:
    def test_unrelated_skeletons_no_credit_keyword_still_rejected(
        self, db, user, yandex_debit, ozon_debit, matcher,
    ):
        """v1.26 expansion of the pro-transfer guard must not reopen the
        v1.10 false-positive class. Two unrelated rows on different banks
        with neither pro-transfer NOR credit-pair keyword must NOT pair
        on amount + date alone — even if both look like simple income/
        expense matches."""
        sess_a = _session(db, user, yandex_debit)
        sess_b = _session(db, user, ozon_debit)
        a = _import_row(
            db, sess_a,
            direction="expense", amount=Decimal("600.00"), when=WHEN_YANDEX,
            description="Оплата в магазине",
            skeleton="оплата магазин",
        )
        b = _import_row(
            db, sess_b,
            direction="income", amount=Decimal("600.00"), when=WHEN_YANDEX,
            description="Кэшбэк за покупки",
            skeleton="кэшбэк покупки",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(a); db.refresh(b)
        assert (a.normalized_data_json or {}).get("target_account_id") in (None, "", 0)
        assert (b.normalized_data_json or {}).get("target_account_id") in (None, "", 0)


# ---------------------------------------------------------------------------
# 6. Contract-token fallback to Account.contract_number
# ---------------------------------------------------------------------------

class TestContractFallback:
    def test_extract_contract_prefers_tokens_over_legacy_keys(self):
        """`_extract_contract` prefers `tokens.contract` over `nd.contract_number`,
        and ignores `nd.source_reference` entirely (used to mistakenly return
        the date string for Yandex rows)."""
        nd = {
            "tokens": {"contract": "КС-NEW"},
            "contract_number": "КС-OLD",
            "source_reference": "10.02.2026",
        }
        assert TransferMatcherService._extract_contract(nd) == "КС-NEW"

    def test_extract_contract_ignores_date_in_source_reference(self):
        """Without a real contract token, source_reference must NOT pollute
        the result — the legacy fallback is removed in v1.26."""
        nd = {"tokens": {}, "source_reference": "10.02.2026"}
        assert TransferMatcherService._extract_contract(nd) is None

    def test_load_active_falls_back_to_account_contract(
        self, db, user, yandex_debit, yandex_split, matcher,
    ):
        """When neither tokens.contract nor parse_settings carry a contract,
        the matcher reads it from the row's session.account.contract_number.
        This enables shared_contract bonus + skeleton-guard exemption for
        the Yandex Сплит case where the description omits the number."""
        sess_d = _session(db, user, yandex_debit)
        sess_s = _session(db, user, yandex_split)
        # Дебет side carries the contract via tokens.
        debit_expense = _import_row(
            db, sess_d,
            direction="expense", amount=AMT_YANDEX, when=WHEN_YANDEX,
            description="Погашение основного долга по договору № КС20251126483806054311",
            skeleton="погашение основного долга <CONTRACT>",
            op_type="transfer",
            tokens={"contract": "КС20251126483806054311"},
            target_account_id=yandex_split.id,
        )
        # Сплит side has no contract anywhere on the row. Account.contract_number
        # matches the Дебет's contract — fallback should fire.
        split_income = _import_row(
            db, sess_s,
            direction="income", amount=AMT_YANDEX, when=WHEN_YANDEX,
            description="Погашение основного долга по договору",
            skeleton="погашение основного долга договору",
            op_type="transfer",
            tokens={"contract": None},
            pending_exclude=True,
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(debit_expense); db.refresh(split_income)
        # If fallback works, the pair is found — skeleton differs across
        # banks so without shared_contract the pair would be rejected by
        # the v1.10 skeleton-guard.
        assert (split_income.normalized_data_json or {}).get("target_account_id") == yandex_debit.id
