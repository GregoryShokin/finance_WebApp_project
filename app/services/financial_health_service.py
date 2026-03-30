from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.real_asset import RealAsset
from app.models.transaction import Transaction


def _status(value: float, thresholds: tuple[float, float]) -> str:
    """Returns 'normal' / 'warning' / 'danger' based on two ascending thresholds."""
    warn, danger = thresholds
    if value >= danger:
        return "danger"
    if value >= warn:
        return "warning"
    return "normal"


# ── DTI ──────────────────────────────────────────────────────────────────────

@dataclass
class DTIResult:
    avg_monthly_payments: Decimal
    avg_monthly_income: Decimal
    dti_percent: float          # 0–100+
    status: str                 # normal / warning / danger


# ── Debt Ratio ────────────────────────────────────────────────────────────────

@dataclass
class DebtRatioResult:
    total_debt: Decimal
    total_assets: Decimal
    debt_ratio_percent: float   # 0–100+
    status: str                 # normal / warning / danger
    real_assets_included: bool


# ─────────────────────────────────────────────────────────────────────────────

class FinancialHealthService:
    # DTI thresholds  (warn at 20 %, danger at 40 %)
    DTI_WARN = 20.0
    DTI_DANGER = 40.0

    # Debt-ratio thresholds  (warn at 30 %, danger at 60 %)
    DR_WARN = 30.0
    DR_DANGER = 60.0

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── helpers ──────────────────────────────────────────────────────────────

    def _period_start(self, months: int = 3) -> datetime:
        """Inclusive start of the last `months` calendar months (UTC midnight)."""
        today = date.today()
        # Roll back `months` months from the first day of current month
        month = today.month - months
        year = today.year + month // 12
        month = month % 12
        if month <= 0:
            month += 12
            year -= 1
        return datetime(year, month, 1, tzinfo=timezone.utc)

    def _transactions_in_period(
        self,
        *,
        user_id: int,
        date_from: datetime,
        operation_types: list[str] | None = None,
        tx_type: str | None = None,
    ) -> list[Transaction]:
        q = self.db.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.transaction_date >= date_from,
        )
        if operation_types:
            q = q.filter(Transaction.operation_type.in_(operation_types))
        if tx_type:
            q = q.filter(Transaction.type == tx_type)
        return q.all()

    # ── 1. DTI ────────────────────────────────────────────────────────────────

    def get_dti(self, user_id: int) -> DTIResult:
        """
        Debt-to-Income ratio based on the last 3 calendar months.

        Payments  = credit_payment expenses (money leaving the account).
        Income    = all income transactions that affect analytics.
        DTI %     = avg_monthly_payments / avg_monthly_income × 100
        """
        period_start = self._period_start(months=3)
        months = 3

        # Credit payments (outgoing)
        payments = self._transactions_in_period(
            user_id=user_id,
            date_from=period_start,
            operation_types=["credit_payment"],
            tx_type="expense",
        )
        total_payments = sum(Decimal(str(tx.amount)) for tx in payments)

        # Income with analytics
        incomes = self.db.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.transaction_date >= period_start,
            Transaction.type == "income",
            Transaction.affects_analytics.is_(True),
        ).all()
        total_income = sum(Decimal(str(tx.amount)) for tx in incomes)

        avg_payments = total_payments / months
        avg_income = total_income / months

        if avg_income > 0:
            dti_pct = float(avg_payments / avg_income * 100)
        else:
            # No income data → treat as worst case if there are payments
            dti_pct = 100.0 if avg_payments > 0 else 0.0

        return DTIResult(
            avg_monthly_payments=avg_payments.quantize(Decimal("0.01")),
            avg_monthly_income=avg_income.quantize(Decimal("0.01")),
            dti_percent=round(dti_pct, 2),
            status=_status(dti_pct, (self.DTI_WARN, self.DTI_DANGER)),
        )

    # ── 2. Debt Ratio ─────────────────────────────────────────────────────────

    def get_debt_ratio(
        self,
        user_id: int,
        include_real_assets: bool = False,
    ) -> DebtRatioResult:
        """
        Debt-to-Assets ratio based on current account balances.

        Debt:
          credit_card  → max(0, credit_limit_original - balance)
          credit       → max(0, -balance)

        Assets:
          regular/other accounts with balance > 0
          investment accounts with balance > 0 (account_type not in credit set)
          RealAsset.estimated_value  (optional)
        """
        accounts = (
            self.db.query(Account)
            .filter(Account.user_id == user_id, Account.is_active.is_(True))
            .all()
        )

        total_debt = Decimal("0")
        total_assets = Decimal("0")

        for account in accounts:
            balance = Decimal(str(account.balance))
            atype = account.account_type or "regular"

            if atype == "credit_card":
                limit = Decimal(str(account.credit_limit_original or 0))
                debt = max(Decimal("0"), limit - balance)
                own = max(Decimal("0"), balance - limit)
                total_debt += debt
                total_assets += own

            elif atype == "credit":
                # balance is stored as negative when in debt
                debt = max(Decimal("0"), -balance)
                total_debt += debt

            else:
                # regular, investment, savings, etc.
                if balance > 0:
                    total_assets += balance

        if include_real_assets:
            real_assets = (
                self.db.query(RealAsset)
                .filter(RealAsset.user_id == user_id)
                .all()
            )
            for ra in real_assets:
                total_assets += Decimal(str(ra.estimated_value))

        if total_assets > 0:
            ratio_pct = float(total_debt / total_assets * 100)
        else:
            ratio_pct = 100.0 if total_debt > 0 else 0.0

        return DebtRatioResult(
            total_debt=total_debt.quantize(Decimal("0.01")),
            total_assets=total_assets.quantize(Decimal("0.01")),
            debt_ratio_percent=round(ratio_pct, 2),
            status=_status(ratio_pct, (self.DR_WARN, self.DR_DANGER)),
            real_assets_included=include_real_assets,
        )
