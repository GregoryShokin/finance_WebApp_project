"""Regression tests for `_resolve_target_account` credit-repayment branch.

Live bug (2026-05-08): row «Погашение кредита по договору №2025-11-27-KK
…» from Ozon Дебет (account_id=262) had `target_account_id=260` (T-Bank
Кредитка) auto-stamped, despite T-Bank being a totally unrelated bank.

Root cause: race condition during initial account setup.

  1. Sessions uploaded (no accounts yet).
  2. T-Bank Кредитка created first.
  3. Ozon Дебет created and assigned to its session → auto-preview runs.
     At THAT moment, the only credit_card account in `accounts` is T-Bank
     Кредитка. The credit-repayment branch:
       • computed source_prefix='озон' from "Озон Дебет"
       • same_bank filter found nothing matching "озон" → fell through
       • the unconditional `if len(all_credit_targets) == 1` returned
         the only credit-type account: T-Bank Кредитка. Wrong bank,
         wrong target.
  4. Ozon Кредитка was created later — but session 699 was never
     re-previewed, so target_account_id=260 stuck.

Fix: when source has a bank-prefix and `same_bank` is empty, treat
`all_credit_targets` as empty too. No auto-target — user picks. This
also matches what `bank_mechanics_service` already does (returns None
when contract doesn't resolve to a same-bank account).
"""
from __future__ import annotations

from decimal import Decimal

from app.models.account import Account
from app.models.bank import Bank
from app.services.transaction_enrichment_service import TransactionEnrichmentService


def _mk_bank(db, *, code: str, name: str | None = None) -> Bank:
    b = Bank(name=name or code.title(), code=code, is_popular=False)
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def _mk_account(
    db,
    *,
    user_id: int,
    bank: Bank,
    name: str,
    account_type: str = "main",
    contract_number: str | None = None,
) -> Account:
    a = Account(
        user_id=user_id, bank_id=bank.id, name=name,
        currency="RUB", balance=Decimal("0"),
        account_type=account_type, contract_number=contract_number,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


# ──────────────────────────────────────────────────────────────────────


def test_credit_repayment_does_not_target_cross_bank_when_no_same_bank_credit(db, user):
    """The exact race-bug scenario: only T-Bank Кредитка exists at
    enrichment time, source is Ozon Дебет. Old behavior returned
    T-Bank as «единственный подходящий кредитный счёт» — wrong.
    New behavior returns None and lets the user pick / lets the next
    re-preview pick up the right same-bank account once it exists.
    """
    sber = _mk_bank(db, code="sber")
    tbank = _mk_bank(db, code="tbank")
    ozon = _mk_bank(db, code="ozon")

    # Ozon Дебет — the source account (this row's session account).
    ozon_debit = _mk_account(
        db, user_id=user.id, bank=ozon, name="Озон Дебет",
        account_type="main", contract_number="2025-11-27-KK",
    )
    # T-Bank Кредитка — a credit card at a different bank. Should NOT
    # be auto-targeted.
    _mk_account(
        db, user_id=user.id, bank=tbank, name="Т-Банк Кредитка",
        account_type="credit_card", contract_number="0504603705",
    )

    svc = TransactionEnrichmentService(db)
    accounts = [ozon_debit, *(
        a for a in db.query(Account).filter(Account.user_id == user.id).all()
        if a.id != ozon_debit.id
    )]
    target_id, conf, reason = svc._resolve_target_account(
        accounts=accounts,
        session_account_id=ozon_debit.id,
        source_account_id=ozon_debit.id,
        operation_type="transfer",
        transaction_type="expense",
        description=(
            "Погашение кредита по договору №2025-11-27-KK 07880171045845068514, "
            "Шокин Григорий Александрович"
        ),
        counterparty="",
    )
    assert target_id is None, f"unexpected cross-bank target: {target_id} ({reason})"
    assert conf == 0.0


def test_credit_repayment_targets_same_bank_credit_when_present(db, user):
    """When the same-bank credit account exists, it WINS — even when
    multiple credit-type accounts are present. This is the happy-path
    behaviour that was already working; we keep it.
    """
    sber = _mk_bank(db, code="sber")
    tbank = _mk_bank(db, code="tbank")
    ozon = _mk_bank(db, code="ozon")

    ozon_debit = _mk_account(
        db, user_id=user.id, bank=ozon, name="Озон Дебет",
        account_type="main", contract_number="2025-11-27-KK",
    )
    ozon_credit = _mk_account(
        db, user_id=user.id, bank=ozon, name="Озон Кредитка",
        account_type="credit_card",
        contract_number="2025-11-27-KK-07880171045845068514",
    )
    _mk_account(
        db, user_id=user.id, bank=tbank, name="Т-Банк Кредитка",
        account_type="credit_card",
    )

    svc = TransactionEnrichmentService(db)
    accounts = db.query(Account).filter(Account.user_id == user.id).all()
    target_id, conf, reason = svc._resolve_target_account(
        accounts=accounts,
        session_account_id=ozon_debit.id,
        source_account_id=ozon_debit.id,
        operation_type="transfer",
        transaction_type="expense",
        description=(
            "Погашение кредита по договору №2025-11-27-KK 07880171045845068514"
        ),
        counterparty="",
    )
    assert target_id == ozon_credit.id
    assert conf >= 0.9
    assert "озон" in reason.lower()


def test_credit_repayment_targets_only_credit_when_source_has_no_bank_prefix(db, user):
    """When the source account name has no recognizable bank prefix
    (e.g. just «Cash» or «Накопительный»), the «single credit target»
    fallback STILL fires — there's no source-bank constraint to
    satisfy. This guards against making the fix overly strict.
    """
    tbank = _mk_bank(db, code="tbank")

    cash = _mk_account(
        db, user_id=user.id, bank=tbank, name="МК",  # 2-char name → no prefix
        account_type="main",
    )
    tbank_credit = _mk_account(
        db, user_id=user.id, bank=tbank, name="Т-Банк Кредитка",
        account_type="credit_card",
    )

    svc = TransactionEnrichmentService(db)
    accounts = db.query(Account).filter(Account.user_id == user.id).all()
    target_id, conf, reason = svc._resolve_target_account(
        accounts=accounts,
        session_account_id=cash.id,
        source_account_id=cash.id,
        operation_type="transfer",
        transaction_type="expense",
        description="Погашение кредита",
        counterparty="",
    )
    assert target_id == tbank_credit.id
