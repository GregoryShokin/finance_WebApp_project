"""Группа 3 (расширение) — Ozon Дебет ↔ Ozon кредитка.

По задаче пользователя: «логика там должна применяться такая же как у
Яндекс Сплита». Спека описывает Яндекс-вариант в §9.10, и тот разбивает
кредитный платёж на ДВЕ ветки на стороне кредитки:
   • «погашение основного долга» — phantom-mirror, suggest_exclude=True
   • «погашение процентов»       — regular expense, категория «Проценты по кредитам»

Тесты ниже разделены на две части:

  Часть 1 — текущий контракт Ozon (что РАБОТАЕТ).
    Дебет → кредитка по contract_number; общая «погашение кредита» income
    на кредитке помечается suggest_exclude. Эти тесты должны быть зелёными
    и будут защищать существующее поведение от случайных регрессий.

  Часть 2 — спека-расхождение (`xfail(strict=True)`, что мы НЕ делаем).
    Различение «основного долга» и «процентов» на стороне Ozon-кредитки
    в `_OZON_RULES` НЕ реализовано. Тесты помечены `xfail`, чтобы:
      (а) явно подсветить gap для будущей доделки;
      (б) сразу провалиться (strict=True), когда правила доведут до
          симметрии с Яндекс — тогда xfail нужно убрать.

См. [bank_mechanics_service.py:206–252](app/services/bank_mechanics_service.py)
и spec §9.10.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.account import Account
from app.models.import_session import ImportSession
from app.services.bank_mechanics_service import BankMechanicsService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ozon_debit(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id,
        name="Озон Дебет", account_type="main",
        balance=Decimal("30000"), currency="RUB",
        is_active=True, is_credit=False,
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def ozon_credit(db, user, bank):
    """Кредитка Ozon. По комментарию в коде спецификации (см. правило
    в `_OZON_RULES`) пользователи часто заводят её как `account_type='main'`,
    поэтому в правиле phantom-mirror `account_type_filter=None`."""
    acc = Account(
        user_id=user.id, bank_id=bank.id,
        name="Озон Кредитка", account_type="main",  # как заводят пользователи
        balance=Decimal("-15000"), currency="RUB",
        is_active=True, is_credit=True,
        contract_number="2025-11-27-KK",
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def ozon_credit_as_credit_card(db, user, bank):
    """Альтернативная конфигурация: account_type='credit_card' — для
    проверки правил, чувствительных к типу счёта."""
    acc = Account(
        user_id=user.id, bank_id=bank.id,
        name="Озон Кредитка (credit_card)", account_type="credit_card",
        balance=Decimal("-5000"), currency="RUB",
        is_active=True, is_credit=True,
        contract_number="2025-11-27-CC",
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


def _session(db, user, account, *, bank_code="ozon"):
    s = ImportSession(
        user_id=user.id, filename="ozon.pdf",
        source_type="pdf", status="preview_ready",
        file_content="", detected_columns=[],
        parse_settings={}, mapping_json={"bank_code": bank_code},
        summary_json={}, account_id=account.id,
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


# ===========================================================================
# Часть 1 — текущий контракт Ozon (зелёные тесты)
# ===========================================================================


# ---------------------------------------------------------------------------
# Дебет/expense → transfer + резолв target по contract_number
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skeleton", [
    "погашение кредита",
    "погашение задолженности",
])
def test_ozon_debit_repayment_is_transfer_with_target_resolved(
    db, user, ozon_debit, ozon_credit, skeleton,
):
    """Дебетовая выписка Ozon, expense «погашение кредита/задолженности»
    → operation_type=transfer + resolved_target_account_id на кредитку
    через contract_number. Сумма и дата на резолв не влияют."""
    session = _session(db, user, ozon_debit)
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton=skeleton,
        direction="expense",
        bank_code="ozon",
        account=ozon_debit,
        session=session,
        total_amount=Decimal("18000"),
        identifier_key="contract",
        identifier_value="2025-11-27-KK",
    )
    assert result.operation_type == "transfer"
    assert result.resolved_target_account_id == ozon_credit.id


def test_ozon_debit_expense_repayment_resolves_to_credit_account(
    db, user, ozon_debit, ozon_credit,
):
    """Базовый кейс T11-Ozon: «погашение кредита» с дебета → перевод на
    кредитку, target резолвится по contract_number."""
    session = _session(db, user, ozon_debit)
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение кредита",
        direction="expense",
        bank_code="ozon",
        account=ozon_debit,
        session=session,
        total_amount=Decimal("18000"),
        identifier_key="contract",
        identifier_value="2025-11-27-KK",
    )
    assert result.operation_type == "transfer"
    assert result.resolved_target_account_id == ozon_credit.id


@pytest.mark.parametrize("amount", [
    Decimal("0.01"), Decimal("18000"), Decimal("99999.99"),
])
def test_ozon_debit_resolution_ignores_amount(
    db, user, ozon_debit, ozon_credit, amount,
):
    """Резолв target_account_id зависит только от contract_number,
    не от суммы (как в спеке Яндекс §9.10)."""
    session = _session(db, user, ozon_debit)
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение кредита",
        direction="expense",
        bank_code="ozon",
        account=ozon_debit,
        session=session,
        total_amount=amount,
        identifier_key="contract",
        identifier_value="2025-11-27-KK",
    )
    assert result.operation_type == "transfer"
    assert result.resolved_target_account_id == ozon_credit.id


def test_ozon_debit_no_resolution_when_contract_unknown(
    db, user, ozon_debit, ozon_credit,
):
    """Контракт неизвестен → operation_type=transfer, но
    resolved_target_account_id=None (юзер выбирает руками)."""
    session = _session(db, user, ozon_debit)
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение кредита",
        direction="expense",
        bank_code="ozon",
        account=ozon_debit,
        session=session,
        total_amount=Decimal("100"),
        identifier_key="contract",
        identifier_value="DOES-NOT-EXIST",
    )
    assert result.operation_type == "transfer"
    assert result.resolved_target_account_id is None


# ---------------------------------------------------------------------------
# Кредитка/income «погашение …» → suggest_exclude=True
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skeleton", [
    "погашение кредита",
    "погашение задолженности",
])
@pytest.mark.parametrize("account_fixture", [
    "ozon_credit",  # account_type='main' (типичная конфигурация юзера)
    "ozon_credit_as_credit_card",  # account_type='credit_card'
])
def test_ozon_credit_income_repayment_is_excluded_as_phantom(
    db, user, request, skeleton, account_fixture,
):
    """На кредитке Ozon входящие «погашение кредита/задолженности» —
    phantom-mirror Дебет-перевода. Контракт: suggest_exclude=True
    независимо от account_type (filter=None в правиле, потому что юзеры
    заводят кредитку как 'main')."""
    credit = request.getfixturevalue(account_fixture)
    session = _session(db, user, credit)
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton=skeleton,
        direction="income",
        bank_code="ozon",
        account=credit,
        session=session,
        total_amount=Decimal("18000"),
        identifier_key="contract",
        identifier_value=credit.contract_number,
    )
    assert result.suggest_exclude is True, (
        f"Кредитка/income {skeleton!r} ({account_fixture}) обязан быть "
        "suggest_exclude=True — иначе баланс кредитки задвоится на коммите"
    )


# ---------------------------------------------------------------------------
# Cashback / маркетплейс — orthogonal-правила (не относятся к погашениям,
# но защищают от регрессий, что cashback не попадает в погашение-ветку)
# ---------------------------------------------------------------------------


def test_ozon_cashback_classified_as_refund_with_category(
    db, user, ozon_debit,
):
    """Регрессия: cashback на дебете → refund + категория «Кэшбэк»,
    а не transfer. Защищает от случайного срабатывания правила
    «погашение» по skeleton'у с «возврат»."""
    session = _session(db, user, ozon_debit)
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="кэшбэк",
        direction="income",
        bank_code="ozon",
        account=ozon_debit,
        session=session,
        total_amount=Decimal("100"),
        identifier_key=None,
        identifier_value=None,
    )
    assert result.operation_type == "refund"
    assert result.category_name == "Кэшбэк"
    assert result.suggest_exclude is False


# ===========================================================================
# Часть 2 — Расхождения со спекой §9.10 (xfail — gap, требует доработки)
# ===========================================================================


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Gap: спека §9.10 требует разделения «основного долга» и «процентов» "
        "на стороне кредитки (как у Яндекс Сплита). В _OZON_RULES — только "
        "общее правило «погашение кредита/задолженности» с suggest_exclude. "
        "Когда правила Ozon будут доведены до симметрии с Яндексом — снять xfail."
    ),
)
def test_ozon_credit_income_interest_is_regular_expense(
    db, user, ozon_credit,
):
    """Целевой контракт (по аналогии с Яндекс Сплитом):
    «погашение процентов» income на Ozon-кредитке → regular expense
    + категория «Проценты по кредитам». Сейчас под общее правило падает
    как suggest_exclude — проценты пропадают из аналитики."""
    session = _session(db, user, ozon_credit)
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение процентов",
        direction="income",
        bank_code="ozon",
        account=ozon_credit,
        session=session,
        total_amount=Decimal("500"),
        identifier_key="contract",
        identifier_value=ozon_credit.contract_number,
    )
    assert result.operation_type == "regular"
    assert result.category_name == "Проценты по кредитам"
    assert result.suggest_exclude is False


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Gap: целевой контракт §9.10 — на кредитке expense «погашение "
        "основного долга» → transfer (закрытие тела долга). В _OZON_RULES "
        "правила для expense-стороны кредитки нет вообще."
    ),
)
def test_ozon_credit_expense_principal_is_transfer(
    db, user, ozon_credit,
):
    session = _session(db, user, ozon_credit)
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение основного долга",
        direction="expense",
        bank_code="ozon",
        account=ozon_credit,
        session=session,
        total_amount=Decimal("17500"),
        identifier_key="contract",
        identifier_value=ozon_credit.contract_number,
    )
    assert result.operation_type == "transfer"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Gap: целевой контракт §9.10 — на кредитке expense «погашение "
        "процентов» → regular + «Проценты по кредитам». В _OZON_RULES "
        "правила для expense-стороны кредитки нет."
    ),
)
def test_ozon_credit_expense_interest_is_regular_expense(
    db, user, ozon_credit,
):
    session = _session(db, user, ozon_credit)
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение процентов",
        direction="expense",
        bank_code="ozon",
        account=ozon_credit,
        session=session,
        total_amount=Decimal("500"),
        identifier_key="contract",
        identifier_value=ozon_credit.contract_number,
    )
    assert result.operation_type == "regular"
    assert result.category_name == "Проценты по кредитам"


# ===========================================================================
# Документирующий якорь
# ===========================================================================


def test_ozon_vs_yandex_split_symmetry_documented():
    """Зафиксирована текущая асимметрия Ozon vs Яндекс §9.10:

      Аспект                                    Яндекс  | Ozon (текущий)
      Дебет/expense погашение → transfer+resolve  ✓     |  ✓
      Кредитка/income «осн. долг» → exclude       ✓     |  ✓ (общее правило)
      Кредитка/income «проценты» → regular+cat    ✓     |  ❌ (попадает под exclude — потеря процентов!)
      Кредитка/expense «осн. долг» → transfer     ✓     |  ❌ (нет правила)
      Кредитка/expense «проценты» → regular+cat   ✓     |  ❌ (нет правила)
      Кредитка/expense «оплата товаров» → regular ✓     |  ⚠ (есть общее «ozon/маркетплейс»)

    Строки с ❌ покрыты xfail-тестами выше. При расширении _OZON_RULES до
    симметрии — xfail-маркеры автоматически зашумят при прохождении и
    их нужно будет снять.
    """
    # Этот тест намеренно тривиален — он живёт ради docstring'а как
    # видимый якорь в test-runner output'е.
    assert True
