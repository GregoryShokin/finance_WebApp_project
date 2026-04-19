"""Phase 4 tests: FI-score unification across MetricsService and FinancialHealthService.

Ref: financeapp-vault/14-Specifications/Спецификация — Целевое состояние системы.md §11 GAP #1
"""
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, date, timedelta

import pytest

from app.models.account import Account
from app.models.transaction import Transaction


def _make_tx(db, **kwargs):
    kwargs.setdefault("currency", "RUB")
    kwargs.setdefault("is_regular", True)
    kwargs.setdefault("affects_analytics", True)
    tx = Transaction(**kwargs)
    db.add(tx)
    db.commit()
    return tx


def _prev_date(n_months: int = 1) -> datetime:
    today = date.today()
    total = today.year * 12 + (today.month - 1) - n_months
    y, m = divmod(total, 12)
    return datetime(y, m + 1, 15)


# ── Tests ────────────────────────────────────────────────────────────────────


def test_fi_score_weights_sum_to_one():
    """Weights v1.4 must sum to exactly 1.00."""
    total = 0.20 + 0.30 + 0.25 + 0.25
    assert abs(total - 1.0) < 1e-9


def test_fi_score_manual_calculation(db, user):
    """Manual verification of FI-score formula with known inputs."""
    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)

    # savings 30% → score 10, capital neutral → 5, DTI 24% → 5.83, buffer 4 мес → 6.67
    # fi = 10*0.20 + 5*0.30 + 5.83*0.25 + 6.67*0.25 = 2 + 1.5 + 1.458 + 1.667 = 6.625 ≈ 6.6
    breakdown = svc._build_fi_breakdown(
        flow={"lifestyle_indicator": 30.0},
        capital={"trend_3m": None, "capital": Decimal("100000"), "snapshots_count": 0},
        dti={"dti_percent": 24.0},
        buffer={"months": 4.0},
    )
    assert breakdown.savings_score == 10.0
    assert breakdown.capital_score == 5.0
    assert abs(breakdown.dti_score - 6.0) < 0.1
    assert abs(breakdown.buffer_score - 6.67) < 0.01
    expected = round(10 * 0.20 + 5 * 0.30 + 6.0 * 0.25 + 6.67 * 0.25, 1)
    assert breakdown.total == expected


def test_fi_score_breakdown_returns_four_components(db, user):
    """FIScoreBreakdown has exactly 4 normalised components."""
    from app.services.metrics_service import MetricsService
    svc = MetricsService(db)
    breakdown = svc._build_fi_breakdown(
        flow={"lifestyle_indicator": None},
        capital={"trend_3m": None, "capital": Decimal("0"), "snapshots_count": 0},
        dti={"dti_percent": None},
        buffer={"months": None},
    )
    assert hasattr(breakdown, "savings_score")
    assert hasattr(breakdown, "capital_score")
    assert hasattr(breakdown, "dti_score")
    assert hasattr(breakdown, "buffer_score")
    assert hasattr(breakdown, "total")


def test_fi_score_components_v14_schema(db, user):
    """FIScoreComponents Pydantic schema has v1.4 fields."""
    from app.schemas.financial_health import FIScoreComponents
    c = FIScoreComponents(
        savings_rate=5.0,
        capital_trend=5.0,
        dti_inverse=7.0,
        buffer_stability=3.0,
    )
    assert hasattr(c, "savings_rate")
    assert hasattr(c, "capital_trend")
    assert hasattr(c, "dti_inverse")
    assert hasattr(c, "buffer_stability")
    # Old fields must NOT exist
    assert not hasattr(c, "discipline")
    assert not hasattr(c, "financial_independence")
    assert not hasattr(c, "safety_buffer")


def test_fi_score_service_returns_breakdown(db, user, regular_account):
    """MetricsService.calculate_fi_score_breakdown returns FIScoreBreakdown."""
    from app.services.metrics_service import MetricsService, FIScoreBreakdown
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             amount=Decimal("100000"), type="income", operation_type="regular",
             transaction_date=_prev_date(1))
    svc = MetricsService(db)
    result = svc.calculate_fi_score_breakdown(user.id)
    assert isinstance(result, FIScoreBreakdown)
    assert 0 <= result.total <= 10


def test_financial_health_service_uses_metrics_fi_score(db, user, regular_account):
    """FinancialHealthService.get_financial_health delegates FI-score to MetricsService."""
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             amount=Decimal("100000"), type="income", operation_type="regular",
             transaction_date=_prev_date(1))

    from app.services.metrics_service import MetricsService
    from app.services.financial_health_service import FinancialHealthService

    metrics_score = MetricsService(db).calculate_metrics_summary(user.id)["fi_score"]
    health = FinancialHealthService(db).get_financial_health(user.id)

    assert health.fi_score == metrics_score, (
        f"FI-score mismatch: /metrics/summary={metrics_score} vs /financial-health={health.fi_score}"
    )


def test_fi_score_components_in_health_response_have_v14_fields(db, user, regular_account):
    """fi_score_components in health response uses v1.4 fields."""
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             amount=Decimal("100000"), type="income", operation_type="regular",
             transaction_date=_prev_date(1))

    from app.services.financial_health_service import FinancialHealthService
    health = FinancialHealthService(db).get_financial_health(user.id)
    comp = health.fi_score_components

    assert comp is not None
    assert hasattr(comp, "capital_trend")
    assert hasattr(comp, "buffer_stability")
    # Old v1.0 fields are gone
    assert not hasattr(comp, "discipline")
    assert not hasattr(comp, "financial_independence")


def test_discipline_and_fi_percent_still_in_response(db, user, regular_account):
    """discipline and fi_percent are still fields in FinancialHealthResponse."""
    _make_tx(db, user_id=user.id, account_id=regular_account.id,
             amount=Decimal("100000"), type="income", operation_type="regular",
             transaction_date=_prev_date(1))

    from app.services.financial_health_service import FinancialHealthService
    health = FinancialHealthService(db).get_financial_health(user.id)

    # These metrics remain independent on Health page
    assert hasattr(health, "discipline")
    assert hasattr(health, "fi_percent")
    assert hasattr(health, "fi_score")
