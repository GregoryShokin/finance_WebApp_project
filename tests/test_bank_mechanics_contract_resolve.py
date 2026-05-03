"""Группа 3 (T11) — bank_mechanics: auto-resolve target_account по
contract_number.

T13 (cross-session transfer match) уже исчерпывающе покрыт в
`test_transfer_matcher_simple_keyword_filter.py` (test_pair_with_keyword_*,
test_pair_across_adjacent_calendar_days_is_matched и т.д.) — там же
тесты что matcher работает по committed/analyzed/preview rows одного
пользователя. Дублировать не имеет смысла.

T12 («re-run для sibling sessions») в коде отсутствует как отдельная
ветка — `TransferMatcherService.match_transfers_for_user(user_id)` уже
по контракту глобален, обрабатывает все активные сессии пользователя
сразу. Зафиксируем это как явный invariant.

Здесь — `BankMechanicsService.apply` для Ozon-правила
«погашение кредита → transfer + suggest_target_by_contract». Level 1
поиска (`Account.contract_number`) работает в SQLite; Levels 2/3 требуют
PostgreSQL JSON-операторов и проверяются интеграционно.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.account import Account
from app.models.import_session import ImportSession
from app.services.bank_mechanics_service import BankMechanicsService


@pytest.fixture
def ozon_debit_account(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id,
        name="Озон Дебет", account_type="main",
        balance=Decimal("10000"), currency="RUB",
        is_active=True, is_credit=False,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@pytest.fixture
def ozon_credit_account(db, user, bank):
    """Кредитка с заполненным contract_number — это тот target, который
    bank_mechanics должен найти при погашении."""
    acc = Account(
        user_id=user.id, bank_id=bank.id,
        name="Озон Кредитка", account_type="main",
        balance=Decimal("-5000"),
        currency="RUB", is_active=True, is_credit=True,
        contract_number="2025-11-27-KK",
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@pytest.fixture
def ozon_session(db, user, ozon_debit_account):
    s = ImportSession(
        user_id=user.id, filename="ozon.pdf",
        source_type="pdf", status="preview_ready",
        file_content="", detected_columns=[],
        parse_settings={}, mapping_json={"bank_code": "ozon"},
        summary_json={}, account_id=ozon_debit_account.id,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def test_ozon_credit_repayment_resolves_target_by_contract(
    db, user, ozon_debit_account, ozon_credit_account, ozon_session
):
    """T11: правило Ozon с suggest_target_by_contract=True + identifier_key
    'contract' → BankMechanicsService.apply возвращает
    resolved_target_account_id = id кредитки с тем же contract_number."""
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение кредита",
        direction="expense",
        bank_code="ozon",
        account=ozon_debit_account,
        session=ozon_session,
        total_amount=Decimal("5000"),
        identifier_key="contract",
        identifier_value="2025-11-27-KK",
    )
    assert result.operation_type == "transfer"
    assert result.resolved_target_account_id == ozon_credit_account.id
    assert "кредитному" in (result.label or "").lower()


def test_ozon_credit_repayment_no_match_when_contract_unknown(
    db, user, ozon_debit_account, ozon_session
):
    """Контракта не существует ни на одном аккаунте → resolved_target_account_id None,
    но operation_type всё равно поднимется до transfer (rule сработал по skeleton)."""
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение кредита",
        direction="expense",
        bank_code="ozon",
        account=ozon_debit_account,
        session=ozon_session,
        total_amount=Decimal("5000"),
        identifier_key="contract",
        identifier_value="UNKNOWN-CONTRACT-123",
    )
    assert result.operation_type == "transfer"
    assert result.resolved_target_account_id is None


def test_bank_mechanics_returns_empty_for_unknown_bank(
    db, user, ozon_debit_account, ozon_session
):
    """Bank не из BANK_RULES → пустой BankMechanicsResult."""
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение кредита",
        direction="expense",
        bank_code="unknown_bank",
        account=ozon_debit_account,
        session=ozon_session,
        total_amount=Decimal("5000"),
        identifier_key="contract",
        identifier_value="2025-11-27-KK",
    )
    assert result.operation_type is None
    assert result.resolved_target_account_id is None


def test_bank_mechanics_returns_empty_when_account_missing(
    db, user, ozon_session
):
    """Без account резолвить контракт не от чего, и матчинг правил тоже
    short-circuit'ит."""
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение кредита",
        direction="expense",
        bank_code="ozon",
        account=None,
        session=ozon_session,
        total_amount=Decimal("5000"),
        identifier_key="contract",
        identifier_value="2025-11-27-KK",
    )
    assert result.operation_type is None
    assert result.resolved_target_account_id is None


# ---------------------------------------------------------------------------
# T12 — глобальность TransferMatcherService по user_id
# ---------------------------------------------------------------------------


def test_transfer_matcher_signature_is_user_global():
    """T12 контракт: TransferMatcherService не имеет per-session варианта.
    Public API — `match_transfers_for_user(user_id)` — глобален по
    пользователю. «Sibling re-run» как отдельная ветка отсутствует:
    каждый прогон уже видит все активные сессии."""
    from app.services.transfer_matcher_service import TransferMatcherService

    svc_methods = [
        name for name in dir(TransferMatcherService)
        if not name.startswith("_") and callable(getattr(TransferMatcherService, name))
    ]
    assert "match_transfers_for_user" in svc_methods
    # Защита от регрессии: если когда-то добавят `match_transfers_for_session`,
    # тесты надо будет переделать под per-session вариант.
    assert "match_transfers_for_session" not in svc_methods, (
        "Появился per-session matcher — обнови тесты Группы 3 (T12) под новый API."
    )
