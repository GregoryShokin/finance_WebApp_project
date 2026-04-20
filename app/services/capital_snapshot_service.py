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
from app.models.counterparty import Counterparty
from app.models.real_asset import RealAsset
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

        liquid = Decimal("0")
        deposit = Decimal("0")
        broker = Decimal("0")
        credit_debt = Decimal("0")
        credit_card_debt = Decimal("0")
        for acc in accounts:
            if not acc.is_active:
                continue
            bal = balances.get(acc.id, Decimal("0"))
            at = acc.account_type
            if at in ("regular", "cash"):
                if bal > 0:
                    liquid += bal
            elif at == "deposit":
                if bal > 0:
                    deposit += bal
            elif at == "broker":
                if bal > 0:
                    broker += bal
            elif at == "credit":
                if bal < 0:
                    credit_debt += abs(bal)
            elif at in ("credit_card", "installment_card"):
                cc = credit_currents.get(acc.id, Decimal("0"))
                if cc > 0:
                    credit_card_debt += cc
                elif bal < 0:
                    credit_card_debt += abs(bal)

        real_assets_total = self._sum_real_assets(user_id)
        receivable, counterparty_debt = self._sum_counterparty_balances(user_id, as_of_end)

        return {
            "liquid_amount": _round2(liquid),
            "deposit_amount": _round2(deposit),
            "broker_amount": _round2(broker),
            "credit_debt": _round2(credit_debt + credit_card_debt),
            "real_assets_amount": _round2(real_assets_total),
            "receivable_amount": _round2(receivable),
            "counterparty_debt": _round2(counterparty_debt),
        }

    def _sum_counterparty_balances(
        self, user_id: int, as_of_end: datetime
    ) -> tuple[Decimal, Decimal]:
        counterparties = (
            self.db.query(Counterparty)
            .filter(Counterparty.user_id == user_id)
            .all()
        )
        if not counterparties:
            return Decimal("0"), Decimal("0")

        debt_txns = (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.operation_type == "debt",
                Transaction.counterparty_id.isnot(None),
                Transaction.transaction_date <= as_of_end,
            )
            .all()
        )
        tx_by_cp: dict[int, list[Transaction]] = {}
        for tx in debt_txns:
            tx_by_cp.setdefault(tx.counterparty_id, []).append(tx)

        receivable_total = Decimal("0")
        payable_total = Decimal("0")
        for cp in counterparties:
            receivable = Decimal(str(cp.opening_receivable_amount or 0))
            payable = Decimal(str(cp.opening_payable_amount or 0))
            for tx in tx_by_cp.get(cp.id, []):
                direction = getattr(tx, "debt_direction", None) or (
                    "borrowed" if tx.type == "income" else "lent"
                )
                amount = Decimal(str(tx.amount or 0))
                if direction == "lent":
                    receivable += amount
                elif direction == "collected":
                    receivable -= amount
                elif direction == "borrowed":
                    payable += amount
                elif direction == "repaid":
                    payable -= amount
            if receivable > 0:
                receivable_total += receivable
            if payable > 0:
                payable_total += payable
        return receivable_total, payable_total

    def _sum_real_assets(self, user_id: int) -> Decimal:
        rows = (
            self.db.query(RealAsset.estimated_value)
            .filter(RealAsset.user_id == user_id)
            .all()
        )
        total = Decimal("0")
        for (val,) in rows:
            if val is not None:
                total += Decimal(str(val))
        return total

    # ── 2. Create or update snapshot (UPSERT) ────────────────────────────────

    def create_snapshot_for_month(self, user_id: int, snapshot_month: date) -> CapitalSnapshot:
        """Idempotent: UPSERT snapshot for the given month.

        `snapshot_month` should be the 1st day of the target month.
        Balance computed at the end of the same month.
        """
        month_start = date(snapshot_month.year, snapshot_month.month, 1)
        month_end = _month_end(month_start)

        components = self.compute_components(user_id, month_end)
        liquid = components["liquid_amount"]
        deposit = components["deposit_amount"]
        broker = components["broker_amount"]
        debt = components["credit_debt"]
        real_assets = components["real_assets_amount"]
        receivable = components["receivable_amount"]
        counterparty_debt = components["counterparty_debt"]
        total_debt = debt + counterparty_debt
        capital = _round2(liquid + deposit + receivable - total_debt)
        net_capital = _round2(
            liquid + deposit + broker + real_assets + receivable - total_debt
        )

        existing = (
            self.db.query(CapitalSnapshot)
            .filter(
                CapitalSnapshot.user_id == user_id,
                CapitalSnapshot.snapshot_month == month_start,
            )
            .first()
        )
        if existing:
            existing.liquid_amount = liquid
            existing.deposit_amount = deposit
            existing.broker_amount = broker
            existing.credit_debt = debt
            existing.real_assets_amount = real_assets
            existing.receivable_amount = receivable
            existing.counterparty_debt = counterparty_debt
            existing.capital = capital
            existing.net_capital = net_capital
            self.db.add(existing)
            self.db.flush()
            return existing

        snap = CapitalSnapshot(
            user_id=user_id,
            snapshot_month=month_start,
            liquid_amount=liquid,
            deposit_amount=deposit,
            broker_amount=broker,
            credit_debt=debt,
            real_assets_amount=real_assets,
            receivable_amount=receivable,
            counterparty_debt=counterparty_debt,
            capital=capital,
            net_capital=net_capital,
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

    # ── 5. Capital history with lazy backfill ────────────────────────────────

    _RU_MONTH_LABELS = [
        "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
        "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
    ]

    def get_capital_history(self, user_id: int, months: int = 6) -> list[dict]:
        """Return capital history for last `months` + current month.

        History is clipped to the first transaction month — months before
        the user had any transactions are omitted. For past months we read
        (or lazy-create) a snapshot; for the current month we compute live
        and do NOT persist.
        """
        today = date.today()
        first_tx = (
            self.db.query(Transaction.transaction_date)
            .filter(Transaction.user_id == user_id)
            .order_by(Transaction.transaction_date.asc())
            .first()
        )
        if first_tx is None:
            return []
        first_tx_month = date(first_tx[0].year, first_tx[0].month, 1)

        total = today.year * 12 + (today.month - 1)
        past_months: list[date] = []
        for i in range(months, 0, -1):
            t = total - i
            y, m = divmod(t, 12)
            month_start = date(y, m + 1, 1)
            if month_start < first_tx_month:
                continue
            past_months.append(month_start)

        existing = {
            s.snapshot_month: s
            for s in (
                self.db.query(CapitalSnapshot)
                .filter(
                    CapitalSnapshot.user_id == user_id,
                    CapitalSnapshot.snapshot_month.in_(past_months),
                )
                .all()
            )
        } if past_months else {}

        points: list[dict] = []
        needs_commit = False
        for month_start in past_months:
            snap = existing.get(month_start)
            if snap is None:
                snap = self.create_snapshot_for_month(user_id, month_start)
                needs_commit = True
            points.append(self._snapshot_to_point(snap))

        if needs_commit:
            self.db.commit()

        current_month_start = date(today.year, today.month, 1)
        if current_month_start >= first_tx_month:
            live = self.compute_components(user_id, today)
            points.append(
                self._build_point(
                    current_month_start,
                    liquid=live["liquid_amount"],
                    deposit=live["deposit_amount"],
                    broker=live["broker_amount"],
                    credit_debt=live["credit_debt"],
                    real_assets=live["real_assets_amount"],
                    receivable=live["receivable_amount"],
                    counterparty_debt=live["counterparty_debt"],
                )
            )
        return points

    def _snapshot_to_point(self, snap: CapitalSnapshot) -> dict:
        return self._build_point(
            snap.snapshot_month,
            liquid=Decimal(str(snap.liquid_amount)),
            deposit=Decimal(str(snap.deposit_amount)),
            broker=Decimal(str(snap.broker_amount or 0)),
            credit_debt=Decimal(str(snap.credit_debt)),
            real_assets=Decimal(str(snap.real_assets_amount or 0)),
            receivable=Decimal(str(snap.receivable_amount or 0)),
            counterparty_debt=Decimal(str(snap.counterparty_debt or 0)),
        )

    def _build_point(
        self,
        month_start: date,
        *,
        liquid: Decimal,
        deposit: Decimal,
        broker: Decimal,
        credit_debt: Decimal,
        real_assets: Decimal,
        receivable: Decimal,
        counterparty_debt: Decimal,
    ) -> dict:
        total_debt = credit_debt + counterparty_debt
        liquid_capital = _round2(liquid + deposit + receivable - total_debt)
        net_capital = _round2(
            liquid + deposit + broker + real_assets + receivable - total_debt
        )
        return {
            "month": f"{month_start.year:04d}-{month_start.month:02d}",
            "label": self._RU_MONTH_LABELS[month_start.month - 1],
            "liquid": float(_round2(liquid)),
            "deposit": float(_round2(deposit)),
            "broker": float(_round2(broker)),
            "receivable": float(_round2(receivable)),
            "real_assets": float(_round2(real_assets)),
            "credit_debt": float(_round2(credit_debt)),
            "counterparty_debt": float(_round2(counterparty_debt)),
            "total_debt": float(_round2(total_debt)),
            "liquid_capital": float(liquid_capital),
            "net_capital": float(net_capital),
        }
