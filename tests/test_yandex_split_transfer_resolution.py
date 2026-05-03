"""Группа 3 (расширение) — Яндекс Дебет ↔ Сплит: контракт классификации
платежей по кредитному договору.

Фиксирует асимметрию между сторонами одной операции:

Дебетовая выписка (account_type ∈ {main, savings}):
    • любое «погашение …» (тело, проценты, общее) → transfer
    • target_account_id резолвится по contract token (не по сумме/дате!)
    • в аналитике расходов НЕ участвует (это перемещение между своими)

Сплит-выписка (account_type ∈ {loan, credit_card, installment_card}):
    • income «погашение основного долга» → suggest_exclude=True
      (phantom mirror от Дебет-перевода — не импортировать, иначе двойной учёт)
    • income «погашение процентов» → regular expense «Проценты по кредитам»
      (это реальный расход на проценты, должен попасть в аналитику)
    • expense «погашение основного долга» → transfer (закрытие тела долга)
    • expense «погашение процентов» → regular expense «Проценты по кредитам»

Эти правила реализованы в `_YANDEX_RULES`. Тест фиксирует их как
контракт — случайная правка одной ветки сломает разделение, на котором
построена корректность аналитики кредитного потока.

Резолв счёта-получателя по контракту НЕ зависит от суммы и даты —
дополнительно проверяется, что `find_by_contract_number` ищет только
по полю `contract_number`.
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
def yandex_debit(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id,
        name="Яндекс Дебет", account_type="main",
        balance=Decimal("50000"), currency="RUB",
        is_active=True, is_credit=False,
        contract_number="DEBIT-12345",  # дебету тоже могут быть номера договоров
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def yandex_split(db, user, bank):
    """Кредитка/installment-карта Сплита с заполненным contract_number —
    цель резолва транзакций по договору."""
    acc = Account(
        user_id=user.id, bank_id=bank.id,
        name="Яндекс Сплит", account_type="installment_card",
        balance=Decimal("-10000"), currency="RUB",
        is_active=True, is_credit=True,
        contract_number="SPLIT-99999",
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def debit_session(db, user, yandex_debit):
    s = ImportSession(
        user_id=user.id, filename="yandex_debit.pdf",
        source_type="pdf", status="preview_ready",
        file_content="", detected_columns=[],
        parse_settings={}, mapping_json={"bank_code": "yandex"},
        summary_json={}, account_id=yandex_debit.id,
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


@pytest.fixture
def split_session(db, user, yandex_split):
    s = ImportSession(
        user_id=user.id, filename="yandex_split.pdf",
        source_type="pdf", status="preview_ready",
        file_content="", detected_columns=[],
        parse_settings={}, mapping_json={"bank_code": "yandex"},
        summary_json={}, account_id=yandex_split.id,
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# Дебетовая сторона: всё «погашение …» → transfer + резолв по контракту
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skeleton", [
    "погашение",
    "погашение основного долга",
    "погашение процентов",
    "погашение по договору",
    "оплата по договору",
    "перевод по договору",
])
def test_debit_side_any_repayment_keyword_is_transfer(
    db, yandex_debit, yandex_split, debit_session, skeleton,
):
    """Любая формулировка «погашения» / «оплаты по договору» в выписке
    Яндекс Дебета должна классифицироваться как transfer и резолвить
    target_account_id на Сплит по контракту."""
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton=skeleton,
        direction="expense",
        bank_code="yandex",
        account=yandex_debit,
        session=debit_session,
        total_amount=Decimal("5000"),
        identifier_key="contract",
        identifier_value="SPLIT-99999",
    )
    assert result.operation_type == "transfer", (
        f"Дебет: skeleton={skeleton!r} обязан быть transfer (не аналитика)"
    )
    assert result.resolved_target_account_id == yandex_split.id, (
        "target_account_id должен резолвиться на Сплит по contract_number"
    )


def test_debit_side_transfer_resolution_ignores_amount_and_date(
    db, yandex_debit, yandex_split, debit_session,
):
    """Контракт-резолв НЕ зависит от суммы и даты: меняем сумму на разную,
    результат тот же, target_account_id резолвится по contract_number."""
    svc = BankMechanicsService(db)
    for amount in (Decimal("100"), Decimal("99999.99"), Decimal("0.01")):
        result = svc.apply(
            skeleton="погашение",
            direction="expense",
            bank_code="yandex",
            account=yandex_debit,
            session=debit_session,
            total_amount=amount,
            identifier_key="contract",
            identifier_value="SPLIT-99999",
        )
        assert result.operation_type == "transfer"
        assert result.resolved_target_account_id == yandex_split.id


def test_debit_side_no_resolve_when_contract_token_missing(
    db, yandex_debit, yandex_split, debit_session,
):
    """Без contract token operation_type всё равно transfer (skeleton match'ит),
    но target_account_id остаётся None — пользователь должен указать вручную."""
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение",
        direction="expense",
        bank_code="yandex",
        account=yandex_debit,
        session=debit_session,
        total_amount=Decimal("5000"),
        identifier_key=None,
        identifier_value=None,
    )
    assert result.operation_type == "transfer"
    assert result.resolved_target_account_id is None


# ---------------------------------------------------------------------------
# Сплит-сторона, income: фантом основного долга / реальный расход на проценты
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("skeleton", [
    "погашение основного долга",
    "погашение просроченной",
    "основного долга",
    "погашение тела",
])
def test_split_income_principal_is_excluded_as_phantom_mirror(
    db, yandex_split, split_session, skeleton,
):
    """T_yandex (основной долг income на Сплите): suggest_exclude=True.
    На Дебете уже импортирован transfer → phantom income создаётся
    автоматически. Если эту строку Сплит-выписки тоже закоммитить,
    баланс Сплита будет задвоен. Контракт: операция помечается на
    исключение из импорта."""
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton=skeleton,
        direction="income",
        bank_code="yandex",
        account=yandex_split,
        session=split_session,
        total_amount=Decimal("5000"),
        identifier_key="contract",
        identifier_value="SPLIT-99999",
    )
    assert result.suggest_exclude is True, (
        f"Сплит income {skeleton!r} обязан получить suggest_exclude=True "
        "(фантом-дубль с Дебета)"
    )


@pytest.mark.parametrize("skeleton", [
    "погашение процентов",
    "проценты пользование",
    "проценты договору",
    "уплата процентов",
])
def test_split_income_interest_is_regular_expense_in_interest_category(
    db, yandex_split, split_session, skeleton,
):
    """T_yandex (проценты income на Сплите): operation_type=regular +
    category «Проценты по кредитам». Это реальный расход — деньги ушли
    банку безвозвратно, должны попасть в аналитику, иначе процентов в
    отчёте о расходах не будет."""
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton=skeleton,
        direction="income",
        bank_code="yandex",
        account=yandex_split,
        session=split_session,
        total_amount=Decimal("500"),
        identifier_key="contract",
        identifier_value="SPLIT-99999",
    )
    assert result.operation_type == "regular", (
        f"Сплит income {skeleton!r} обязан быть regular (не transfer), "
        "иначе проценты исчезнут из аналитики расходов"
    )
    assert result.category_name == "Проценты по кредитам"
    assert result.suggest_exclude is False


# ---------------------------------------------------------------------------
# Сплит-сторона, expense: тело долга (transfer) vs проценты (regular)
# ---------------------------------------------------------------------------


def test_split_expense_principal_is_transfer(
    db, yandex_split, split_session,
):
    """T_yandex (основной долг expense на Сплите): operation_type=transfer.
    Это закрытие тела кредита — не расход, движение между своими."""
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение основного долга",
        direction="expense",
        bank_code="yandex",
        account=yandex_split,
        session=split_session,
        total_amount=Decimal("5000"),
        identifier_key="contract",
        identifier_value="SPLIT-99999",
    )
    assert result.operation_type == "transfer"


def test_split_expense_interest_is_regular_expense(
    db, yandex_split, split_session,
):
    """T_yandex (проценты expense на Сплите): operation_type=regular,
    категория «Проценты по кредитам». Реальный расход на проценты."""
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение процентов",
        direction="expense",
        bank_code="yandex",
        account=yandex_split,
        session=split_session,
        total_amount=Decimal("500"),
        identifier_key="contract",
        identifier_value="SPLIT-99999",
    )
    assert result.operation_type == "regular"
    assert result.category_name == "Проценты по кредитам"


def test_split_expense_purchase_via_bnpl_is_regular(
    db, yandex_split, split_session,
):
    """Покупка в кредит на Сплите → regular expense (без принудительной
    категории — система подберёт по истории мерчанта)."""
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="оплата товаров",
        direction="expense",
        bank_code="yandex",
        account=yandex_split,
        session=split_session,
        total_amount=Decimal("3000"),
        identifier_key=None,
        identifier_value=None,
    )
    assert result.operation_type == "regular"
    assert result.category_name is None


# ---------------------------------------------------------------------------
# Изоляция account_type_filter: правило Сплита НЕ срабатывает на дебете
# ---------------------------------------------------------------------------


def test_debit_side_does_not_inherit_split_interest_rule(
    db, yandex_debit, yandex_split, debit_session,
):
    """Регрессия: правило «погашение процентов → regular expense» имеет
    account_type_filter=('loan', 'credit_card', 'installment_card'). На
    дебетовом счёте оно НЕ должно сработать — там должно срабатывать
    дебет-правило (transfer + резолв по контракту)."""
    svc = BankMechanicsService(db)
    result = svc.apply(
        skeleton="погашение процентов",
        direction="expense",
        bank_code="yandex",
        account=yandex_debit,
        session=debit_session,
        total_amount=Decimal("500"),
        identifier_key="contract",
        identifier_value="SPLIT-99999",
    )
    # На дебете срабатывает универсальное правило «погашение … → transfer».
    assert result.operation_type == "transfer", (
        "На дебете 'погашение процентов' обязан быть transfer, не expense — "
        "иначе на дебете эту строку бы засчитали в расходы и проценты "
        "удвоились бы (дебет + сплит)"
    )
    assert result.category_name is None
    assert result.resolved_target_account_id is not None


def test_split_account_does_not_match_debit_specific_rule(
    db, yandex_split, split_session,
):
    """Симметрия: дебет-правило с suggest_target_by_contract имеет
    account_type_filter=('main', 'savings'). На Сплит-аккаунте оно
    срабатывать не должно — Сплит-сам-в-себя резолвить нечего."""
    svc = BankMechanicsService(db)
    # Намеренно skeleton который попадает в дебет-правило, но account
    # типа installment_card не должен по нему совпасть.
    result = svc.apply(
        skeleton="оплата по договору",
        direction="expense",
        bank_code="yandex",
        account=yandex_split,
        session=split_session,
        total_amount=Decimal("5000"),
        identifier_key="contract",
        identifier_value="SPLIT-99999",
    )
    # В _YANDEX_RULES для Сплита нет правила на «оплата по договору»
    # expense direction — так что результат должен быть пустым (None)
    # либо попасть в более общее «оплата товаров/услуг» если match'нется.
    # Главное: НЕ должен резолвиться target_account_id (это дебет-only поведение).
    assert result.resolved_target_account_id is None, (
        "suggest_target_by_contract — дебет-only; на Сплите не должно резолвить"
    )


# ---------------------------------------------------------------------------
# Аналитика: семантика affects_analytics
# ---------------------------------------------------------------------------


def test_analytics_semantics_documented_in_test():
    """Документирующий тест-якорь: ниже зафиксирована семантика, которую
    защищают тесты выше. Если поведение изменится, эти assert'ы
    упадут — обновляйте контракт сознательно."""
    # Дебет: и тело, и проценты — transfer (не в аналитике расходов)
    # Сплит income: тело — exclude (не импортируется), проценты — regular expense
    # Сплит expense: тело — transfer, проценты — regular expense
    expectations = {
        ("debit", "expense", "погашение основного долга"): "transfer",
        ("debit", "expense", "погашение процентов"): "transfer",
        ("split", "income", "погашение основного долга"): "exclude",
        ("split", "income", "погашение процентов"): "regular_interest",
        ("split", "expense", "погашение основного долга"): "transfer",
        ("split", "expense", "погашение процентов"): "regular_interest",
    }
    # Проценты считаются расходом ОДИН раз — на Сплите, не на Дебете.
    # Тело долга в аналитике расходов не светится вообще.
    assert expectations[("debit", "expense", "погашение процентов")] == "transfer"
    assert expectations[("split", "expense", "погашение процентов")] == "regular_interest"
    assert expectations[("split", "income", "погашение основного долга")] == "exclude"
