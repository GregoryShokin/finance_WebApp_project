"""Phase 2 tests: three-layer Flow, Buffer stability, FI-score v1.4.

Ref: financeapp-vault/01-Metrics/Поток.md
Ref: financeapp-vault/13-Prompts/Фаза 2 — Новые формулы метрик в metrics_service.md
"""
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, date, timedelta

import pytest

from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction


TODAY = date.today()
CURRENT_MONTH = date(TODAY.year, TODAY.month, 1)


def _prev_month_date(n: int) -> datetime:
    """Return a datetime inside the n-th previous month (day 15)."""
    total = CURRENT_MONTH.year * 12 + (CURRENT_MONTH.month - 1) - n
    year, month = divmod(total, 12)
    return datetime(year, month + 1, 15)


def _make_tx(db, **kwargs):
    kwargs.setdefault("currency", "RUB")
    kwargs.setdefault("is_regular", True)
    kwargs.setdefault("affects_analytics", True)
    tx = Transaction(**kwargs)
    db.add(tx)
    db.commit()
    return tx


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def deposit_account(db, user, bank):
    acc = Account(
        user_id=user.id,
        bank_id=bank.id,
        name="Вклад",
        account_type="savings",
        balance=Decimal("0"),
        currency="RUB",
        is_active=True,
        is_credit=False,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@pytest.fixture
def cc_account(db, user, bank):
    acc = Account(
        user_id=user.id,
        bank_id=bank.id,
        name="Кредитка",
        account_type="credit_card",
        balance=Decimal("0"),
        currency="RUB",
        is_active=True,
        is_credit=True,
        monthly_payment=Decimal("0"),
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


# ─── 9.1 Free capital (GAP #4) ───────────────────────────────────────────────


def test_free_capital_subtracts_credit_body(db, user, regular_account, credit_account, interest_category):
    """Базовый +58к, кредит monthly_payment=45к, средний процент 42к/мес → тело 3к → free = 55к."""
    # Regular income 100k
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             amount=Decimal("100000"), type="income", operation_type="regular",
             transaction_date=_prev_month_date(0))
    # Regular expenses 42k (жильё, продукты и пр.)
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             amount=Decimal("42000"), type="expense", operation_type="regular",
             transaction_date=_prev_month_date(0))
    # Set monthly_payment on credit = 45k, avg interest ≈ 42k → body ≈ 3k
    credit_account.monthly_payment = Decimal("45000")
    db.add(credit_account)
    db.commit()

    # Interest expenses over last 3 months (42k/mo avg)
    for n in range(1, 4):
        _make_tx(db, user_id=user.id, account_id=regular_account.id,
                 credit_account_id=credit_account.id,
                 category_id=interest_category.id,
                 amount=Decimal("42000"),
                 type="expense", operation_type="regular",
                 transaction_date=_prev_month_date(n))

    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)
    result = svc.calculate_flow(user.id, CURRENT_MONTH.year, CURRENT_MONTH.month)

    # basic_flow = 100k - 42k = 58k
    assert result["basic_flow"] == Decimal("58000.00")
    # body = 45k - 42k (avg interest) = 3k
    assert result["credit_body_payments"] == Decimal("3000.00")
    # free_capital = 58k - 3k = 55k
    assert result["free_capital"] == Decimal("55000.00")


def test_free_capital_zero_credits(db, user, regular_account):
    """Нет кредитов → free_capital == basic_flow."""
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             amount=Decimal("100000"), type="income", operation_type="regular",
             transaction_date=_prev_month_date(0))
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             amount=Decimal("40000"), type="expense", operation_type="regular",
             transaction_date=_prev_month_date(0))

    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)
    r = svc.calculate_flow(user.id, CURRENT_MONTH.year, CURRENT_MONTH.month)

    assert r["basic_flow"] == Decimal("60000.00")
    assert r["credit_body_payments"] == Decimal("0.00")
    assert r["free_capital"] == Decimal("60000.00")


# ─── 9.2 Full flow (balance delta) ───────────────────────────────────────────


def test_full_flow_kk_purchase_no_payment(db, user, regular_account, cc_account):
    """Зарплата 100к, наличные расходы 20к, покупка 40к на КК без погашения.
    Δ дебета = +80к; долг по КК +40к; full_flow = +80к; cc_compensator = +40к."""
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             amount=Decimal("100000"), type="income", operation_type="regular",
             transaction_date=_prev_month_date(0))
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             amount=Decimal("20000"), type="expense", operation_type="regular",
             transaction_date=_prev_month_date(0))
    # Purchase on CC = expense from CC account (balance of CC goes more negative)
    _make_tx(db, user_id=user.id, account_id=cc_account.id,
             amount=Decimal("40000"), type="expense", operation_type="regular",
             transaction_date=_prev_month_date(0))

    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)
    r = svc.calculate_flow(user.id, _prev_month_date(0).year, _prev_month_date(0).month)

    # full_flow = 100k income − 20k expense from regular = 80k
    assert r["full_flow"] == Decimal("80000.00"), f"full_flow={r['full_flow']}"
    # CC compensator = 40k (debt grew)
    assert r["cc_debt_compensator"] == Decimal("40000.00")


def test_compensator_partial_repayment_no_double_counting(db, user, regular_account, cc_account):
    """
    Баг 2026-04-19: компенсатор НЕ ДОЛЖЕН вычитать погашения.
    Погашения уже отражены через credit_body_payments (transfer к credit счёту).
    Если компенсатор тоже их вычтет — двойной учёт и разрыв декомпозиции.
    """
    tx_dt = _prev_month_date(0)
    year, month = tx_dt.year, tx_dt.month

    # Зарплата 100к на дебет
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             amount=Decimal("100000"), type="income", operation_type="regular",
             transaction_date=tx_dt)
    # Обычные расходы 20к с дебета
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             amount=Decimal("20000"), type="expense", operation_type="regular",
             transaction_date=tx_dt)
    # Покупка 40к на КК
    _make_tx(db, user_id=user.id, account_id=cc_account.id,
             amount=Decimal("40000"), type="expense", operation_type="regular",
             transaction_date=tx_dt)
    # Частичное погашение: 30к transfer debit → cc (credit_account_id required for body tracking)
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             target_account_id=cc_account.id,
             credit_account_id=cc_account.id,
             amount=Decimal("30000"), type="expense", operation_type="transfer",
             affects_analytics=False,
             transaction_date=tx_dt)

    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)

    # Compensator = только покупки на КК = 40k, НЕ 10k (Δ долга)
    compensator = svc.calculate_cc_debt_compensator(user.id, year, month)
    assert compensator == Decimal("40000.00"), (
        f"Компенсатор должен быть 40k (только покупки), а не {compensator} "
        f"(это бы значило, что погашения вычтены — двойной учёт)."
    )

    # Δ ликвидного кэша = +100 - 20 (expense debit) - 30 (transfer к CC) = +50k
    r = svc.calculate_flow(user.id, year, month)
    assert r["full_flow"] == Decimal("50000.00"), f"full_flow={r['full_flow']}"
    assert r["cc_debt_compensator"] == Decimal("40000.00")

    # Замкнутость декомпозиции Полного:
    # all_income - all_expenses - credit_body + compensator = full_flow
    # 100 - (20 + 40) - 30 + 40 = 50 ✓
    all_income = Decimal("100000")
    all_expenses = Decimal("60000")  # 20 debit + 40 cc
    credit_body = Decimal("30000")  # transfer к cc
    reconstructed = all_income - all_expenses - credit_body + r["cc_debt_compensator"]
    assert reconstructed == r["full_flow"], (
        f"Декомпозиция не сходится: {reconstructed} ≠ {r['full_flow']}"
    )


def test_full_flow_includes_deposit_transfer_excluded(db, user, regular_account, deposit_account):
    """Перевод regular→deposit (внутри ликвидной сферы) не меняет Полный поток."""
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             amount=Decimal("100000"), type="income", operation_type="regular",
             transaction_date=_prev_month_date(0))
    # Transfer 10k to deposit — both liquid; should be net zero
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             target_account_id=deposit_account.id,
             amount=Decimal("10000"), type="expense", operation_type="transfer",
             affects_analytics=False,
             transaction_date=_prev_month_date(0))

    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)
    r = svc.calculate_flow(user.id, _prev_month_date(0).year, _prev_month_date(0).month)

    # Only the income counts; the transfer is netted
    assert r["full_flow"] == Decimal("100000.00")


# ─── 9.3 Buffer stability ────────────────────────────────────────────────────


def test_buffer_stability_uses_deposit_not_regular(db, user, regular_account, deposit_account):
    """regular 200k, deposit 150k, avg_expenses 50k → buffer = 3.0 мес."""
    regular_account.balance = Decimal("200000")
    deposit_account.balance = Decimal("150000")
    db.add_all([regular_account, deposit_account])
    db.commit()

    # Create 12 months of 50k expenses for proper 12-month average
    for n in range(1, 13):
        _make_tx(db, user_id=user.id, account_id=regular_account.id,
                 amount=Decimal("50000"), type="expense", operation_type="regular",
                 transaction_date=_prev_month_date(n))

    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)
    r = svc.calculate_buffer_stability(user.id)

    # 150k / 50k = 3.0 мес
    assert r["deposit_balance"] == Decimal("150000.00")
    assert r["avg_monthly_expense"] == Decimal("50000.00")
    assert r["months"] == 3.0
    assert r["zone"] == "normal"  # 3 ≤ months ≤ 6


def test_buffer_stability_zero_deposits(db, user, regular_account):
    """Нет deposit-счетов → months=None, zone=None."""
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             amount=Decimal("50000"), type="expense", operation_type="regular",
             transaction_date=_prev_month_date(1))

    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)
    r = svc.calculate_buffer_stability(user.id)

    assert r["deposit_balance"] == Decimal("0.00")
    assert r["months"] is None
    assert r["zone"] is None


# ─── 9.4 FI-score weights v1.4 ───────────────────────────────────────────────


def test_fi_score_weights_v14(db, user):
    """Direct test of _calc_fi_score with known inputs.
    Lifestyle 30% (savings_score=10), trend=null (capital=5),
    DTI=25% (dti_score≈5.83), buffer=3мес (buffer_score=5).
    Expected: 10·0.20 + 5·0.30 + 5.83·0.25 + 5·0.25 = 6.71 ≈ 6.7
    """
    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)

    flow = {"lifestyle_indicator": 30.0}
    capital = {"trend": None}
    dti = {"dti_percent": 25.0}
    buffer = {"months": 3.0}

    score = svc._calc_fi_score(flow, capital, dti, buffer)
    # 10*0.20 + 5*0.30 + (10-25/6)*0.25 + 5*0.25 = 2.0 + 1.5 + 1.4583 + 1.25 = 6.21
    # NOTE: savings_score = min(30/30*10, 10) = 10
    # dti_score = max(10 - 25/6, 0) = 10 - 4.1667 = 5.8333
    # 10*0.20 + 5*0.30 + 5.8333*0.25 + 5*0.25 = 2.0 + 1.5 + 1.4583 + 1.25 = 6.21
    assert abs(score - 6.2) <= 0.1, f"Expected ~6.2, got {score}"


def test_fi_score_null_dti_treated_as_no_debt(db, user):
    """DTI=None (no credits) → dti_score=10 (no debt penalty)."""
    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)
    # Lifestyle 20% → savings 6.67; no trend; no dti; no buffer
    flow = {"lifestyle_indicator": 20.0}
    capital = {"trend": None}
    dti = {"dti_percent": None}
    buffer = {"months": None}
    score = svc._calc_fi_score(flow, capital, dti, buffer)
    # 6.67*0.20 + 5*0.30 + 10*0.25 + 0*0.25 = 1.333 + 1.5 + 2.5 + 0 = 5.33
    assert abs(score - 5.3) <= 0.1, f"Expected ~5.3, got {score}"


def test_fi_score_sensitivity_single_category(db, user):
    """Смена регулярности одной категории ~15k/мес не должна менять FI-score > 1 балл."""
    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)

    # Baseline: lifestyle 20%, dti 30%, buffer 3мес
    baseline = svc._calc_fi_score(
        {"lifestyle_indicator": 20.0},
        {"trend": None},
        {"dti_percent": 30.0},
        {"months": 3.0},
    )

    # Move 15k from regular expenses to irregular → lifestyle grew from 20% to ~35% (15k out of 100k income)
    shifted = svc._calc_fi_score(
        {"lifestyle_indicator": 35.0},  # +15% points
        {"trend": None},
        {"dti_percent": 30.0},
        {"months": 3.0},
    )
    # savings: 20/30*10=6.67 vs min(35/30*10,10)=10 → delta in savings_score: 3.33
    # weighted delta: 3.33 * 0.20 = 0.67
    delta = abs(shifted - baseline)
    assert delta <= 1.0, f"Sensitivity too high: delta={delta}"


# ─── 9.5 12-month window ─────────────────────────────────────────────────────


def test_dti_uses_12_month_window(db, user, regular_account, credit_account, interest_category):
    """Первые 6 мес: доход 100к/мес, последние 6 мес: 200к/мес.
    Средний за 12 мес = 150k. За 3 мес было бы 200k.
    Ожидаем: regular_income = 150k.
    """
    # Months 7..12 back: 100k
    for n in range(7, 13):
        _make_tx(db, user_id=user.id, account_id=regular_account.id,
                 amount=Decimal("100000"), type="income", operation_type="regular",
                 transaction_date=_prev_month_date(n))
    # Months 1..6 back: 200k
    for n in range(1, 7):
        _make_tx(db, user_id=user.id, account_id=regular_account.id,
                 amount=Decimal("200000"), type="income", operation_type="regular",
                 transaction_date=_prev_month_date(n))

    # One interest expense so DTI has a non-zero numerator
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             credit_account_id=credit_account.id,
             category_id=interest_category.id,
             amount=Decimal("15000"), type="expense", operation_type="regular",
             transaction_date=_prev_month_date(1))

    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)
    r = svc.calculate_dti(user.id)

    # avg across 12 months = (6*100k + 6*200k) / 12 = 150k
    assert r["regular_income"] == Decimal("150000.00"), f"Got {r['regular_income']}"


def test_summary_returns_new_fields(db, user, regular_account):
    """calculate_metrics_summary must include free_capital, cc_debt_compensator, buffer_stability."""
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             amount=Decimal("100000"), type="income", operation_type="regular",
             transaction_date=_prev_month_date(0))

    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)
    s = svc.calculate_metrics_summary(user.id)

    assert "free_capital" in s["flow"]
    assert "cc_debt_compensator" in s["flow"]
    assert "credit_body_payments" in s["flow"]
    assert "buffer_stability" in s
    assert "reserve" in s  # legacy compat
    assert "fi_score" in s
