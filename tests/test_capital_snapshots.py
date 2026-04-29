"""Phase 3 Block A: Capital snapshot tests.

Ref: financeapp-vault/14-Specifications/Спецификация — Целевое состояние системы.md §2.3
"""
from __future__ import annotations

from decimal import Decimal
from datetime import date, datetime, timezone, timedelta

import pytest

from app.models.account import Account
from app.models.capital_snapshot import CapitalSnapshot
from app.models.transaction import Transaction


def _make_tx(db, **kwargs):
    kwargs.setdefault("currency", "RUB")
    kwargs.setdefault("is_regular", True)
    kwargs.setdefault("affects_analytics", True)
    tx = Transaction(**kwargs)
    db.add(tx)
    db.commit()
    return tx


@pytest.fixture(autouse=True)
def import_snapshot_model():
    """Ensure CapitalSnapshot is imported so SQLAlchemy maps it."""
    import app.models.capital_snapshot  # noqa: F401


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def deposit_account(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id, name="Вклад", account_type="savings",
        balance=Decimal("150000"), currency="RUB", is_active=True, is_credit=False,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@pytest.fixture
def credit_account2(db, user, bank):
    acc = Account(
        user_id=user.id, bank_id=bank.id, name="Кредит2", account_type="loan",
        balance=Decimal("-50000"), credit_current_amount=Decimal("50000"),
        currency="RUB", is_active=True, is_credit=True,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


# ── А.6 Tests ────────────────────────────────────────────────────────────────


def test_snapshot_creates_components(db, user, regular_account, deposit_account, credit_account):
    """Snapshot correctly computes liquid / deposit / credit_debt."""
    regular_account.balance = Decimal("200000")
    deposit_account.balance = Decimal("150000")
    credit_account.credit_current_amount = Decimal("80000")
    credit_account.balance = Decimal("-80000")
    db.add_all([regular_account, deposit_account, credit_account])
    db.commit()

    from app.services.capital_snapshot_service import CapitalSnapshotService
    svc = CapitalSnapshotService(db)
    # Snapshot for last month (no post-date transactions → balances are exact)
    today = date.today()
    last_month = date(today.year, today.month, 1) - timedelta(days=1)
    snap_month = date(last_month.year, last_month.month, 1)

    snap = svc.create_snapshot_for_month(user.id, snap_month)
    db.commit()

    assert snap.liquid_amount == Decimal("200000.00")
    assert snap.deposit_amount == Decimal("150000.00")
    assert snap.credit_debt == Decimal("80000.00")
    assert snap.capital == Decimal("270000.00")  # 200k + 150k - 80k


def test_snapshot_idempotent(db, user, regular_account):
    """Two calls for same month → only one row in DB (UPSERT)."""
    regular_account.balance = Decimal("100000")
    db.add(regular_account)
    db.commit()

    from app.services.capital_snapshot_service import CapitalSnapshotService
    svc = CapitalSnapshotService(db)
    today = date.today()
    last_month = date(today.year, today.month, 1) - timedelta(days=1)
    snap_month = date(last_month.year, last_month.month, 1)

    svc.create_snapshot_for_month(user.id, snap_month)
    db.commit()
    svc.create_snapshot_for_month(user.id, snap_month)
    db.commit()

    count = db.query(CapitalSnapshot).filter(
        CapitalSnapshot.user_id == user.id,
        CapitalSnapshot.snapshot_month == snap_month,
    ).count()
    assert count == 1, f"Expected 1 snapshot, got {count}"


def test_trend_calculation(db, user, regular_account):
    """3 snapshots with different capitals → trend correctly computed."""
    from app.services.capital_snapshot_service import CapitalSnapshotService

    today = date.today()
    def prev_month_date(n):
        total = today.year * 12 + (today.month - 1) - n
        y, m = divmod(total, 12)
        return date(y, m + 1, 1)

    # Insert snapshots: latest = prev_month_date(1), base for trend_3m = prev_month_date(4)
    snaps = [
        (prev_month_date(4), Decimal("100000")),  # base for trend_3m
        (prev_month_date(3), Decimal("105000")),
        (prev_month_date(2), Decimal("110000")),
        (prev_month_date(1), Decimal("120000")),  # latest
    ]
    for sm, cap in snaps:
        db.add(CapitalSnapshot(
            user_id=user.id, snapshot_month=sm,
            liquid_amount=cap, deposit_amount=Decimal("0"),
            credit_debt=Decimal("0"), capital=cap,
            net_capital=cap,
        ))
    db.commit()

    regular_account.balance = Decimal("120000")
    db.add(regular_account)
    db.commit()

    svc = CapitalSnapshotService(db)
    trend = svc.get_trend(user.id)

    assert trend["snapshots_count"] == 4
    # trend_3m = latest (120k) - snapshot 3 months before latest (100k) = +20k
    assert trend["trend_3m"] == Decimal("20000.00")
    assert trend["trend_6m"] is None  # no snapshot 6 months before latest


def test_trend_no_snapshots(db, user, regular_account):
    """No snapshots → all trends None."""
    from app.services.capital_snapshot_service import CapitalSnapshotService
    svc = CapitalSnapshotService(db)
    trend = svc.get_trend(user.id)
    assert trend["trend_3m"] is None
    assert trend["trend_6m"] is None
    assert trend["trend_12m"] is None
    assert trend["snapshots_count"] == 0


def test_fi_score_with_positive_trend(db, user):
    """Positive trend → capital_score > 5."""
    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)
    capital = {"trend_3m": Decimal("50000"), "capital": Decimal("200000"), "snapshots_count": 3}
    flow = {"lifestyle_indicator": None}
    dti = {"dti_percent": None}
    buf = {"months": None}
    score_positive = svc._calc_fi_score(flow, capital, dti, buf)
    capital_no_trend = {"trend_3m": None, "capital": Decimal("200000"), "snapshots_count": 1}
    score_neutral = svc._calc_fi_score(flow, capital_no_trend, dti, buf)
    assert score_positive > score_neutral


def test_fi_score_with_negative_trend(db, user):
    """Negative trend → capital_score < 5."""
    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)
    capital_neg = {"trend_3m": Decimal("-50000"), "capital": Decimal("200000"), "snapshots_count": 3}
    capital_neutral = {"trend_3m": None, "capital": Decimal("200000"), "snapshots_count": 0}
    flow = {"lifestyle_indicator": None}
    dti = {"dti_percent": None}
    buf = {"months": None}
    assert svc._calc_fi_score(flow, capital_neg, dti, buf) < svc._calc_fi_score(flow, capital_neutral, dti, buf)


# ── Блок Б tests ──────────────────────────────────────────────────────────────


def test_dti_includes_body_not_only_interest(db, user, regular_account, credit_account, interest_category):
    """Ипотека 45к/мес = тело 3к + проценты 42к. DTI должен считать = 45/200 = 22.5%."""
    from app.models.transaction import Transaction
    today = date.today()
    prev_month = date(today.year, today.month, 1) - timedelta(days=1)
    prev_date = datetime(prev_month.year, prev_month.month, 15)

    # Salary 200k last 12 months
    for n in range(1, 13):
        total = today.year * 12 + (today.month - 1) - n
        y, m = divmod(total, 12)
        d = datetime(y, m + 1, 15)
        _make_tx(db, user_id=user.id, account_id=regular_account.id,
                 amount=Decimal("200000"), type="income", operation_type="regular",
                 transaction_date=d)

    # Interest expense 42k last month
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             credit_account_id=credit_account.id, category_id=interest_category.id,
             amount=Decimal("42000"), type="expense", operation_type="regular",
             transaction_date=prev_date)
    # Body transfer 3k last month (credit_account_id required to distinguish from plain top-up)
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             target_account_id=credit_account.id, credit_account_id=credit_account.id,
             amount=Decimal("3000"), type="expense", operation_type="transfer",
             affects_analytics=False, transaction_date=prev_date)

    from app.services.metrics_service import MetricsService
    r = MetricsService(db).calculate_dti(user.id)
    assert r["monthly_payments"] == Decimal("45000.00"), f"Expected 45000, got {r['monthly_payments']}"
    expected_dti = round(45000 / 200000 * 100, 2)
    assert abs((r["dti_percent"] or 0) - expected_dti) < 0.1, f"DTI={r['dti_percent']}, expected {expected_dti}"


def test_dti_first_shag_scenario(db, user, regular_account, interest_category):
    """«Первый шаг»: доход 120к, ипотека 28к (тело 3 + % 25), потребкредит 20к (тело 15 + % 5).
    Ожидаем DTI = (3+25+15+5) / 120 = 48/120 = 40%."""
    from app.models.account import Account
    from app.models.transaction import Transaction

    today = date.today()
    prev_month = date(today.year, today.month, 1) - timedelta(days=1)
    prev_date = datetime(prev_month.year, prev_month.month, 15)

    # Two credit accounts — share the test bank from regular_account.
    mortgage = Account(user_id=user.id, bank_id=regular_account.bank_id, name="Ипотека", account_type="loan",
                       balance=Decimal("-2000000"), credit_current_amount=Decimal("2000000"),
                       currency="RUB", is_active=True, is_credit=True)
    loan = Account(user_id=user.id, bank_id=regular_account.bank_id, name="Потребкредит", account_type="loan",
                   balance=Decimal("-500000"), credit_current_amount=Decimal("500000"),
                   currency="RUB", is_active=True, is_credit=True)
    db.add_all([mortgage, loan])
    db.commit()

    # Salary 120k × 12 months
    for n in range(1, 13):
        total = today.year * 12 + (today.month - 1) - n
        y, m = divmod(total, 12)
        d = datetime(y, m + 1, 15)
        _make_tx(db, user_id=user.id, account_id=regular_account.id,
                 amount=Decimal("120000"), type="income", operation_type="regular",
                 transaction_date=d)

    # Mortgage: interest 25k + body 3k
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             credit_account_id=mortgage.id, category_id=interest_category.id,
             amount=Decimal("25000"), type="expense", operation_type="regular",
             transaction_date=prev_date)
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             target_account_id=mortgage.id, credit_account_id=mortgage.id,
             amount=Decimal("3000"), type="expense", operation_type="transfer",
             affects_analytics=False, transaction_date=prev_date)

    # Loan: interest 5k + body 15k
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             credit_account_id=loan.id, category_id=interest_category.id,
             amount=Decimal("5000"), type="expense", operation_type="regular",
             transaction_date=prev_date)
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             target_account_id=loan.id, credit_account_id=loan.id,
             amount=Decimal("15000"), type="expense", operation_type="transfer",
             affects_analytics=False, transaction_date=prev_date)

    from app.services.metrics_service import MetricsService
    r = MetricsService(db).calculate_dti(user.id)
    assert r["monthly_payments"] == Decimal("48000.00"), f"Expected 48000, got {r['monthly_payments']}"
    assert abs((r["dti_percent"] or 0) - 40.0) < 0.1, f"DTI={r['dti_percent']}, expected 40%"
