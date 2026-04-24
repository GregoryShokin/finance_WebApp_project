"""Phase 3.8: refund matcher tests.

Covers: amount+direction+window guards, confidence bands (0.95 / 0.80 / 0.60),
greedy 1-to-1 assignment, and robustness to malformed input rows.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.services.refund_matcher_service import (
    MAX_DATE_DIFF_DAYS,
    RefundMatch,
    RefundMatcherService,
)


def _row(
    row_id: int,
    amount: str,
    direction: str,
    date: datetime,
    description: str = "",
    skeleton: str = "",
    tokens: dict | None = None,
) -> dict:
    return {
        "row_id": row_id,
        "amount": amount,
        "direction": direction,
        "transaction_date": date,
        "description": description,
        "skeleton": skeleton,
        "tokens": tokens or {},
    }


@pytest.fixture
def svc() -> RefundMatcherService:
    return RefundMatcherService()


# ---------------------------------------------------------------------------
# Boundary conditions
# ---------------------------------------------------------------------------

class TestBoundaries:
    def test_no_match_on_amount_mismatch(self, svc):
        now = datetime(2026, 4, 22)
        rows = [
            _row(1, "100.00", "expense", now),
            _row(2, "99.99", "income", now + timedelta(days=1)),
        ]
        assert svc.match(rows) == []

    def test_no_match_on_same_direction(self, svc):
        now = datetime(2026, 4, 22)
        rows = [
            _row(1, "100.00", "expense", now),
            _row(2, "100.00", "expense", now + timedelta(days=1)),
        ]
        assert svc.match(rows) == []

    def test_no_match_outside_14_day_window(self, svc):
        now = datetime(2026, 4, 22)
        rows = [
            _row(1, "100.00", "expense", now, skeleton="магазин"),
            _row(2, "100.00", "income", now + timedelta(days=MAX_DATE_DIFF_DAYS + 1), skeleton="магазин"),
        ]
        assert svc.match(rows) == []

    def test_match_at_exact_window_boundary(self, svc):
        now = datetime(2026, 4, 22)
        rows = [
            _row(1, "100.00", "expense", now, skeleton="магазин"),
            _row(2, "100.00", "income", now + timedelta(days=MAX_DATE_DIFF_DAYS), skeleton="магазин"),
        ]
        result = svc.match(rows)
        assert len(result) == 1
        assert result[0].confidence == pytest.approx(0.80)

    def test_skips_malformed_rows(self, svc):
        now = datetime(2026, 4, 22)
        rows = [
            _row(1, "100.00", "expense", now, skeleton="магазин"),
            {"row_id": 2, "amount": "100.00"},  # missing direction/date
            _row(3, "100.00", "income", now + timedelta(days=1), skeleton="магазин"),
        ]
        result = svc.match(rows)
        assert len(result) == 1
        assert {result[0].expense_row_id, result[0].income_row_id} == {1, 3}


# ---------------------------------------------------------------------------
# Confidence bands
# ---------------------------------------------------------------------------

class TestConfidenceBands:
    def test_strong_on_matching_contract(self, svc):
        now = datetime(2026, 4, 22)
        rows = [
            _row(1, "500", "expense", now, tokens={"contract": "ДГ-12345"}),
            _row(2, "500", "income", now + timedelta(days=2), tokens={"contract": "ДГ-12345"}),
        ]
        result = svc.match(rows)
        assert len(result) == 1
        assert result[0].confidence == pytest.approx(0.95)
        assert "same_contract" in result[0].reasons

    def test_strong_on_matching_person_hash(self, svc):
        now = datetime(2026, 4, 22)
        rows = [
            _row(1, "500", "expense", now, tokens={"person_hash": "abc123"}),
            _row(2, "500", "income", now + timedelta(days=1), tokens={"person_hash": "abc123"}),
        ]
        result = svc.match(rows)
        assert len(result) == 1
        assert result[0].confidence == pytest.approx(0.95)
        assert "same_person" in result[0].reasons

    def test_strong_on_matching_counterparty_org(self, svc):
        now = datetime(2026, 4, 22)
        rows = [
            _row(1, "500", "expense", now, tokens={"counterparty_org": "ООО Ромашка"}),
            _row(2, "500", "income", now + timedelta(days=3), tokens={"counterparty_org": "ООО Ромашка"}),
        ]
        result = svc.match(rows)
        assert len(result) == 1
        assert result[0].confidence == pytest.approx(0.95)

    def test_strong_on_refund_keyword_with_matching_brand(self, svc):
        """Refund keyword alone is not enough — needs same merchant/brand."""
        now = datetime(2026, 4, 22)
        rows = [
            _row(1, "500", "expense", now,
                 description="Оплата в Pyaterochka",
                 skeleton="оплата в pyaterochka"),
            _row(2, "500", "income", now + timedelta(days=2),
                 description="Возврат в Pyaterochka",
                 skeleton="возврат в pyaterochka"),
        ]
        result = svc.match(rows)
        assert len(result) == 1
        assert result[0].confidence == pytest.approx(0.95)
        assert "refund_keyword" in result[0].reasons
        assert "same_brand" in result[0].reasons

    def test_refund_keyword_without_brand_match_is_rejected(self, svc):
        """Regression: KOFEMOLOKO refund ↔ POPLAVO purchase must NOT pair up
        just because amounts align and one side contains 'отмена'."""
        now = datetime(2026, 4, 22)
        rows = [
            _row(1, "700", "expense", now,
                 description="Оплата в POPLAVO Volgodonsk RUS",
                 skeleton="оплата в poplavo volgodonsk rus"),
            _row(2, "700", "income", now,
                 description="Отмена операции оплаты KOFEMOLOKO Volgodonsk RUS",
                 skeleton="отмена операции оплаты kofemoloko volgodonsk rus"),
        ]
        result = svc.match(rows)
        assert len(result) == 0

    def test_medium_on_matching_skeleton(self, svc):
        now = datetime(2026, 4, 22)
        rows = [
            _row(1, "500", "expense", now, skeleton="магазин продукты"),
            _row(2, "500", "income", now + timedelta(days=1), skeleton="магазин продукты"),
        ]
        result = svc.match(rows)
        assert len(result) == 1
        assert result[0].confidence == pytest.approx(0.80)

    def test_weak_on_amount_and_window_only(self, svc):
        now = datetime(2026, 4, 22)
        rows = [
            _row(1, "500", "expense", now),
            _row(2, "500", "income", now + timedelta(days=1)),
        ]
        result = svc.match(rows)
        assert len(result) == 1
        assert result[0].confidence == pytest.approx(0.60)


# ---------------------------------------------------------------------------
# Greedy 1-to-1 assignment
# ---------------------------------------------------------------------------

class TestGreedyAssignment:
    def test_higher_confidence_pair_wins(self, svc):
        """If one expense could pair with two incomes, the higher-confidence pair wins."""
        now = datetime(2026, 4, 22)
        rows = [
            _row(1, "500", "expense", now, skeleton="магазин", tokens={"contract": "Д1"}),
            # Weak candidate — would pair with row 1 at 0.60 if alone
            _row(2, "500", "income", now + timedelta(days=1)),
            # Strong candidate — same contract, should win over row 2
            _row(3, "500", "income", now + timedelta(days=2), tokens={"contract": "Д1"}),
        ]
        result = svc.match(rows)
        assert len(result) == 1
        assert result[0].expense_row_id == 1
        assert result[0].income_row_id == 3
        assert result[0].confidence == pytest.approx(0.95)

    def test_each_row_appears_in_at_most_one_pair(self, svc):
        now = datetime(2026, 4, 22)
        rows = [
            _row(1, "500", "expense", now, skeleton="a"),
            _row(2, "500", "income", now + timedelta(days=1), skeleton="a"),
            # Third row — same amount+direction as row 2, but row 2 is already taken.
            _row(3, "500", "expense", now + timedelta(days=2), skeleton="a"),
        ]
        result = svc.match(rows)
        # Two expenses × one income → only one pair possible.
        assert len(result) == 1
        used_rows = {result[0].expense_row_id, result[0].income_row_id}
        # Whichever expense pairs with income=2, the other expense stays free.
        assert 2 in used_rows
