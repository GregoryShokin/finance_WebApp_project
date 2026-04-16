from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction

try:
    from app.models.installment_purchase import InstallmentPurchase
    _INSTALLMENT_AVAILABLE = True
except Exception:
    _INSTALLMENT_AVAILABLE = False


def _round2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))


class AnalyticsService:
    def __init__(self, db: Session):
        self.db = db

    def get_expense_analytics(self, user_id: int, year: int, month: int) -> dict:
        month_start = datetime(year, month, 1, tzinfo=timezone.utc)
        last_day = calendar.monthrange(year, month)[1]
        month_end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)

        # Fetch installment_card accounts (used for installment annotations below)
        ic_accounts = (
            self.db.query(Account)
            .filter(
                Account.user_id == user_id,
                Account.account_type == "installment_card",
                Account.is_active.is_(True),
            )
            .all()
        )
        ic_account_ids = [a.id for a in ic_accounts]

        # Fetch expense transactions (installment_card purchases are real expenses)
        q = (
            self.db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.type == "expense",
                Transaction.affects_analytics.is_(True),
                Transaction.transaction_date >= month_start,
                Transaction.transaction_date <= month_end,
                Transaction.operation_type.notin_(("transfer", "credit_early_repayment")),
            )
        )
        txns = q.all()

        # Build category map
        cat_ids = {tx.category_id for tx in txns if tx.category_id is not None}
        categories = {}
        if cat_ids:
            cats = self.db.query(Category).filter(Category.id.in_(cat_ids)).all()
            categories = {c.id: c for c in cats}

        # Group by category
        by_category: dict[int | None, Decimal] = defaultdict(Decimal)
        total = Decimal("0")
        regular_total = Decimal("0")
        irregular_total = Decimal("0")

        for tx in txns:
            amount = Decimal(str(tx.amount))
            by_category[tx.category_id] += amount
            total += amount
            if tx.is_regular:
                regular_total += amount
            else:
                irregular_total += amount

        # Build installment details per category
        installment_by_category: dict[int | None, list] = defaultdict(list)
        installment_annotations = []
        new_obligations = Decimal("0")

        if _INSTALLMENT_AVAILABLE:
            if ic_account_ids:
                purchases = (
                    self.db.query(InstallmentPurchase)
                    .filter(
                        InstallmentPurchase.account_id.in_(ic_account_ids),
                        InstallmentPurchase.status == "active",
                    )
                    .all()
                )

                month_start_date = date(year, month, 1)
                month_end_date = date(year, month, last_day)

                for p in purchases:
                    cat_name = None
                    if p.category_id and p.category_id in categories:
                        cat_name = categories[p.category_id].name

                    # Remaining months estimate
                    remaining_months = 0
                    if p.monthly_payment > 0:
                        remaining_months = int(
                            Decimal(str(p.remaining_amount)) / Decimal(str(p.monthly_payment))
                        )

                    started_this_month = (
                        month_start_date <= p.start_date <= month_end_date
                    )

                    installment_annotations.append({
                        "description": p.description,
                        "category_name": cat_name,
                        "monthly_payment": _round2(Decimal(str(p.monthly_payment))),
                        "original_amount": _round2(Decimal(str(p.original_amount))),
                        "remaining_amount": _round2(Decimal(str(p.remaining_amount))),
                        "started_this_month": started_this_month,
                    })

                    if started_this_month:
                        new_obligations += Decimal(str(p.original_amount))

                    if p.category_id is not None:
                        installment_by_category[p.category_id].append({
                            "description": p.description,
                            "monthly_payment": _round2(Decimal(str(p.monthly_payment))),
                            "remaining_months": remaining_months,
                        })

        # Build category expenses list
        category_expenses = []
        for cat_id, amount in sorted(by_category.items(), key=lambda x: x[1], reverse=True):
            cat = categories.get(cat_id) if cat_id else None
            cat_name = cat.name if cat else "Без категории"
            is_regular = cat.regularity == "regular" if cat else True

            details = installment_by_category.get(cat_id) if cat_id else None

            category_expenses.append({
                "category_id": cat_id,
                "category_name": cat_name,
                "amount": _round2(amount),
                "is_regular": is_regular,
                "installment_details": details if details else None,
            })

        # Account-level installment summary (shows even without purchase details)
        installment_accounts_summary = []
        if ic_accounts:
            for acc in ic_accounts:
                debt = abs(float(acc.balance)) if acc.balance and float(acc.balance) < 0 else float(acc.credit_current_amount or 0)
                if debt > 0:
                    payment = float(acc.monthly_payment) if acc.monthly_payment else None
                    installment_accounts_summary.append({
                        "account_name": acc.name,
                        "total_debt": _round2(Decimal(str(debt))),
                        "monthly_payment": _round2(Decimal(str(payment))) if payment else None,
                        "has_purchase_details": any(
                            a["description"] for a in installment_annotations
                        ) if installment_annotations else False,
                    })

        return {
            "total_expenses": _round2(total),
            "regular_expenses": _round2(regular_total),
            "irregular_expenses": _round2(irregular_total),
            "categories": category_expenses,
            "installment_annotations": installment_annotations,
            "new_installment_obligations": _round2(new_obligations),
            "installment_accounts_summary": installment_accounts_summary,
        }
