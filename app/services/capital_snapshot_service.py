"""CapitalSnapshotService — creates and reads monthly snapshots of user capital.

Ref: financeapp-vault/14-Specifications/Спецификация — Целевое состояние системы.md §2.3
Phase 3 Block A (2026-04-19).
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.capital_snapshot import CapitalSnapshot
from app.models.transaction import Transaction


def _round2(v: Decimal) -> Decimal:
    return Decimal(v).quantize(Decimal("0.01"))


def _next_day_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(days=1)


def _month_end(d: date) -> date:
    last_day = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last_day)


class CapitalSnapshotService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── 1. Compute components at a given date ────────────────────────────────

    def compute_components(self, user_id: int, as_of: date) -> dict:
        """Compute liquid, deposit, credit_debt at end of `as_of` date.

        Strategy: start from current account.balance, then roll back transactions
        that happened AFTER `as_of` end-of-day.
        """
        as_of_end = datetime(as_of.year, as_of.month, as_of.day, 23, 59, 59, tzinfo=timezone.utc)

        accounts = (
            self.db.query(Account)
            .filter(Account.user_id == user_id)
            .all()
        )

        # Fetch transactions after as_of
        after_txns = (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_date > as_of_end,
            )
            .all()
        )

        # Bucket reversal by account_id (source) and target_account_id
        balances: dict[int, Decimal] = {
            a.id: Decimal(str(a.balance or 0)) for a in accounts
        }
        credit_currents: dict[int, Decimal] = {
            a.id: Decimal(str(a.credit_current_amount or 0)) for a in accounts
        }
        acc_by_id = {a.id: a for a in accounts}

        for tx in after_txns:
            amount = Decimal(str(tx.amount))
            op = tx.operation_type
            src = tx.account_id
            tgt = tx.target_account_id
            ttype = tx.type

            # Revert source account effect
            if src in balances:
                if op in ("transfer", "credit_early_repayment"):
                    # These reduce source balance — revert = add
                    balances[src] += amount
                elif ttype == "expense":
                    balances[src] += amount
                elif ttype == "income":
                    balances[src] -= amount

            # Revert target account effect
            if tgt is not None and tgt in balances:
                tgt_acc = acc_by_id.get(tgt)
                if op in ("transfer", "credit_early_repayment"):
                    if tgt_acc and tgt_acc.account_type == "credit_card":
                        balances[tgt] -= amount
                    elif tgt_acc and tgt_acc.account_type in ("credit", "installment_card"):
                        principal = tx.credit_principal_amount or amount
                        credit_currents[tgt] += Decimal(str(principal))
                        balances[tgt] = -credit_currents[tgt]
                    else:
                        balances[tgt] -= amount

        # Sum by category
        liquid = Decimal("0")
        deposit = Decimal("0")
        credit_debt = Decimal("0")
        for acc in accounts:
            if not acc.is_active:
                continue
            bal = balances.get(acc.id, Decimal("0"))
            if acc.account_type in ("regular", "cash"):
                liquid += bal
            elif acc.account_type == "deposit":
                deposit += bal
            elif acc.account_type in ("credit", "credit_card", "installment_card"):
                cc = credit_currents.get(acc.id, Decimal("0"))
                if cc > 0:
                    credit_debt += cc
                elif acc.account_type == "credit_card" and bal < 0:
                    credit_debt += abs(bal)

        return {
            "liquid_amount": _round2(liquid),
            "deposit_amount": _round2(deposit),
            "credit_debt": _round2(credit_debt),
        }

    # ── 2. Create or update snapshot (UPSERT) ────────────────────────────────

    def create_snapshot_for_month(self, user_id: int, snapshot_month: date) -> CapitalSnapshot:
        """Idempotent: UPSERT snapshot for the given month.

        `snapshot_month` should be the 1st day of the target month.
        Balance computed at the end of the same month.
        """
        month_start = date(snapshot_month.year, snapshot_month.month, 1)
        month_end = _month_end(month_start)

        components = self.compute_components(user_id, month_end)
        capital = _round2(
            components["liquid_amount"] + components["deposit_amount"] - components["credit_debt"]
        )

        # Try find existing
        existing = (
            self.db.query(CapitalSnapshot)
            .filter(
                CapitalSnapshot.user_id == user_id,
                CapitalSnapshot.snapshot_month == month_start,
            )
            .first()
        )
        if existing:
            existing.liquid_amount = components["liquid_amount"]
            existing.deposit_amount = components["deposit_amount"]
            existing.credit_debt = components["credit_debt"]
            existing.capital = capital
            self.db.add(existing)
            self.db.flush()
            return existing

        snap = CapitalSnapshot(
            user_id=user_id,
            snapshot_month=month_start,
            liquid_amount=components["liquid_amount"],
            deposit_amount=components["deposit_amount"],
            credit_debt=components["credit_debt"],
            capital=capital,
            net_capital=None,
        )
        self.db.add(snap)
        self.db.flush()
        return snap

    # ── 3. Trend calculation ─────────────────────────────────────────────────

    def get_trend(self, user_id: int, window_months: int = 12) -> dict:
        """Return current capital + Δ over 3/6/12 month windows.

        current_capital is derived from live account balances (not snapshots).
        Δ uses the most recent snapshot minus snapshot N months back.
        """
        # Compute current capital from live balances
        accounts = (
            self.db.query(Account)
            .filter(Account.user_id == user_id, Account.is_active.is_(True))
            .all()
        )
        liquid = Decimal("0")
        deposit = Decimal("0")
        debt = Decimal("0")
        for acc in accounts:
            bal = Decimal(str(acc.balance or 0))
            if acc.account_type in ("regular", "cash"):
                liquid += bal
            elif acc.account_type == "deposit":
                deposit += bal
            elif acc.account_type in ("credit", "credit_card", "installment_card"):
                if acc.credit_current_amount is not None:
                    debt += Decimal(str(acc.credit_current_amount))
                elif acc.account_type == "credit_card" and bal < 0:
                    debt += abs(bal)
        current_capital = _round2(liquid + deposit - debt)

        # Fetch all snapshots for this user, newest first
        snapshots = (
            self.db.query(CapitalSnapshot)
            .filter(CapitalSnapshot.user_id == user_id)
            .order_by(CapitalSnapshot.snapshot_month.desc())
            .all()
        )
        snapshots_by_month: dict[date, CapitalSnapshot] = {
            s.snapshot_month: s for s in snapshots
        }

        latest_snap = snapshots[0] if snapshots else None
        latest_capital = latest_snap.capital if latest_snap else None

        def _delta_n_back(n: int) -> Decimal | None:
            if not snapshots:
                return None
            # Compare latest snapshot vs n months before it
            base = latest_snap.snapshot_month
            total = base.year * 12 + (base.month - 1) - n
            y, m = divmod(total, 12)
            target = date(y, m + 1, 1)
            ref = snapshots_by_month.get(target)
            if ref is None:
                return None
            return _round2(Decimal(str(latest_snap.capital)) - Decimal(str(ref.capital)))

        return {
            "current_capital": current_capital,
            "snapshot_capital": Decimal(str(latest_capital)) if latest_capital is not None else None,
            "trend_3m": _delta_n_back(3),
            "trend_6m": _delta_n_back(6),
            "trend_12m": _delta_n_back(12),
            "snapshots_count": len(snapshots),
        }

    # ── 4. List user months needing snapshots ────────────────────────────────

    def months_needing_snapshots(self, user_id: int) -> list[date]:
        """List of 1st-of-month dates from user's first transaction month
        up to previous completed month."""
        first_tx = (
            self.db.query(Transaction.transaction_date)
            .filter(Transaction.user_id == user_id)
            .order_by(Transaction.transaction_date.asc())
            .first()
        )
        if not first_tx:
            return []
        first_dt = first_tx[0]
        start = date(first_dt.year, first_dt.month, 1)

        today = date.today()
        # previous completed month end
        total = today.year * 12 + (today.month - 1) - 1
        y, m = divmod(total, 12)
        end = date(y, m + 1, 1)

        months: list[date] = []
        cur = start
        while cur <= end:
            months.append(cur)
            total = cur.year * 12 + (cur.month - 1) + 1
            y, m = divmod(total, 12)
            cur = date(y, m + 1, 1)
        return months
