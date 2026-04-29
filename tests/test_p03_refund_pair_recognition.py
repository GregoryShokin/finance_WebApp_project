"""Regression test for P-03.

Problem statement (from `financeapp-vault/11-problems/Улучшение импорта/Импорт — проблемы и решения.md#P-03`):

> Возврат (refund) распознаётся по ключевым словам, но не использует контекст пары:
> - две строки с одинаковой суммой и противоположными направлениями за короткое
>   время — это возврат, а не пара «расход + доход».

Verification scenarios:

1. Same brand, opposite directions, same amount, within 14d → matched as refund
   pair via `RefundMatcherService`. Brand-only match (no «возврат» keyword).
2. Refund keyword + brand match → high-confidence (0.95) refund pair.
3. Same-amount coincidence across UNRELATED merchants (no brand match, no
   keyword) → NOT matched (false-positive guard).
4. Pair window > 14d → NOT matched.

Closes P-03 if all four pass.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.services.refund_matcher_service import RefundMatcherService


def _row(row_id: int, *, amount: str, direction: str, date: datetime,
         description: str, skeleton: str = "", tokens: dict | None = None) -> dict:
    return {
        "row_id": row_id,
        "amount": amount,
        "direction": direction,
        "transaction_date": date.isoformat(),
        "description": description,
        "skeleton": skeleton,
        "tokens": tokens or {},
    }


def test_refund_pair_matched_by_brand_alone():
    """Same brand, opposite directions, same amount, 5 days apart, no «возврат»
    keyword. Brand-only match yields 0.75 confidence — passes MIN_CONFIDENCE
    (0.60), so the pair is emitted."""
    base = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    rows = [
        _row(1, amount="700.00", direction="expense", date=base,
             description="Оплата POPLAVO Москва",
             skeleton="оплата poplavo москва"),
        _row(2, amount="700.00", direction="income", date=base + timedelta(days=5),
             description="POPLAVO зачисление",
             skeleton="poplavo зачисление"),
    ]
    matches = RefundMatcherService().match(rows)
    assert len(matches) == 1, f"expected exactly one refund pair, got {matches}"
    m = matches[0]
    assert m.expense_row_id == 1
    assert m.income_row_id == 2
    assert m.confidence >= 0.60


def test_refund_pair_matched_by_keyword_plus_brand():
    """Refund keyword («Отмена операции») + brand match → 0.95 confidence."""
    base = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    rows = [
        _row(1, amount="450.00", direction="expense", date=base,
             description="Оплата KOFEMOLOKO",
             skeleton="оплата kofemoloko"),
        _row(2, amount="450.00", direction="income", date=base + timedelta(days=2),
             description="Отмена операции оплаты KOFEMOLOKO",
             skeleton="отмена операции kofemoloko"),
    ]
    matches = RefundMatcherService().match(rows)
    assert len(matches) == 1
    m = matches[0]
    assert m.confidence == 0.95
    assert "refund_keyword" in m.reasons
    assert "same_brand" in m.reasons


def test_amount_coincidence_across_merchants_not_matched():
    """Two unrelated transactions with the same amount + window must NOT pair.
    This is the «700₽ POPLAVO» vs «700₽ Отмена KOFEMOLOKO» trap from the
    refund_matcher_service docstring — the matcher must reject it."""
    base = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    rows = [
        _row(1, amount="700.00", direction="expense", date=base,
             description="Оплата POPLAVO Москва",
             skeleton="оплата poplavo москва"),
        _row(2, amount="700.00", direction="income", date=base + timedelta(hours=4),
             description="Отмена операции оплаты KOFEMOLOKO",
             skeleton="отмена операции kofemoloko"),
    ]
    matches = RefundMatcherService().match(rows)
    # Different brands → keyword-only signal → 0.50 confidence → below MIN_CONFIDENCE.
    assert matches == [], f"expected no match, got {matches}"


def test_refund_pair_outside_window_not_matched():
    """A refund 20 days after the purchase falls outside the ±14d window."""
    base = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    rows = [
        _row(1, amount="700.00", direction="expense", date=base,
             description="Оплата POPLAVO",
             skeleton="оплата poplavo"),
        _row(2, amount="700.00", direction="income", date=base + timedelta(days=20),
             description="Отмена POPLAVO",
             skeleton="отмена poplavo"),
    ]
    matches = RefundMatcherService().match(rows)
    assert matches == []
