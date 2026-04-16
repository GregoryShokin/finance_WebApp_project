from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.account import Account
from app.services.metrics_service import MetricsService

try:
    from app.models.installment_purchase import InstallmentPurchase
    _INSTALLMENT_AVAILABLE = True
except Exception:
    _INSTALLMENT_AVAILABLE = False


def _fmt(value: Decimal | float | int) -> str:
    """Format number with thousands separator and ruble sign."""
    v = int(round(float(value)))
    formatted = f"{abs(v):,}".replace(",", " ")
    return f"{formatted} \u20BD"


def _dti_to_days(dti: float) -> str:
    """Convert DTI % to workdays out of 5."""
    days = round(dti / 20 * 2) / 2
    return f"{days:.1f}".rstrip("0").rstrip(".")


class SchoolMomentsService:
    def __init__(self, db: Session):
        self.db = db
        self.metrics_service = MetricsService(db)

    def get_school_moments(self, user_id: int) -> list[dict]:
        summary = self.metrics_service.calculate_metrics_summary(user_id)
        flow = summary["flow"]
        dti = summary["dti"]
        reserve = summary["reserve"]
        capital = summary["capital"]

        moments: list[dict] = []

        # -- Metric-based moments --

        li = flow.get("lifestyle_indicator")
        basic = flow.get("basic_flow", 0)

        if li is not None and li < 0:
            moments.append({
                "id": "flow_deficit",
                "category": "flow",
                "severity": "alert",
                "title": "Расходы превышают доход",
                "message": (
                    f"Регулярные расходы и платежи по кредитам бо��ьше стабильного дохода "
                    f"на {_fmt(abs(basic))}/мес. Три шага: (1) проверь топ-3 категории расходов, "
                    f"(2) если нагрузка > 30% — рассмотри рефинансирование, "
                    f"(3) направляй нерегулярный доход на закрытие дефицита."
                ),
                "requires_purchases": False,
            })
        elif li is not None and 0 <= li < 10:
            moments.append({
                "id": "flow_tight",
                "category": "flow",
                "severity": "warning",
                "title": "Тонкая подушка",
                "message": (
                    f"Остаётся {li:.0f}% дохода — одна непредвиденная трата может увести в минус."
                ),
                "requires_purchases": False,
            })

        reserve_months = reserve.get("months")
        if reserve_months is not None and 1 <= reserve_months < 3:
            moments.append({
                "id": "reserve_minimum",
                "category": "reserve",
                "severity": "info",
                "title": "Запас растёт",
                "message": f"Запас {reserve_months:.1f} мес. — хороший старт. Цель: 3–6 месяцев расходов.",
                "requires_purchases": False,
            })

        dti_pct = dti.get("dti_percent")
        if dti_pct is not None and dti_pct >= 60:
            days = _dti_to_days(dti_pct)
            moments.append({
                "id": "dti_critical",
                "category": "dti",
                "severity": "alert",
                "title": "Критическая нагрузка",
                "message": (
                    f"{dti_pct:.0f}% — опасная зона. Рефинансирование или "
                    f"реструктуризация могут снизить нагрузку."
                ),
                "requires_purchases": False,
            })
        elif dti_pct is not None and dti_pct >= 40:
            days = _dti_to_days(dti_pct)
            moments.append({
                "id": "dti_danger",
                "category": "dti",
                "severity": "warning",
                "title": "Высокая нагрузка",
                "message": (
                    f"{dti_pct:.0f}% дохода уходит на кредиты. "
                    f"Это {days} из 5 рабочих д��ей на банк. "
                    f"Рассмотри досрочное погашение самого дорогого кредита."
                ),
                "requires_purchases": False,
            })

        capital_trend = capital.get("trend")
        if capital_trend is not None and capital_trend < 0:
            moments.append({
                "id": "capital_declining",
                "category": "capital",
                "severity": "warning",
                "title": "Капитал уменьшается",
                "message": (
                    f"Капитал п��дает на {_fmt(abs(capital_trend))}/мес. "
                    f"Проверь: растут ли долги быстрее накоплений?"
                ),
                "requires_purchases": False,
            })

        # -- Installment-based moments (basic, no purchases required) --

        ic_accounts = (
            self.db.query(Account)
            .filter(
                Account.user_id == user_id,
                Account.account_type == "installment_card",
                Account.is_active.is_(True),
            )
            .all()
        )

        for acc in ic_accounts:
            if (
                acc.credit_current_amount is not None
                and acc.credit_limit_original is not None
                and acc.credit_limit_original > 0
            ):
                utilization = float(acc.credit_current_amount) / float(acc.credit_limit_original)
                if utilization > 0.7:
                    remaining = float(acc.credit_limit_original) - float(acc.credit_current_amount)
                    moments.append({
                        "id": "installment_utilization",
                        "category": "installment",
                        "severity": "warning",
                        "title": "Высокая утилизация рассрочки",
                        "message": (
                            f"Использовано {utilization * 100:.0f}% лимита карты «{acc.name}». "
                            f"Остаток лимита: {_fmt(remaining)}."
                        ),
                        "requires_purchases": False,
                    })

        total_installment_payment = sum(
            float(acc.monthly_payment) for acc in ic_accounts
            if acc.monthly_payment is not None and float(acc.credit_current_amount or 0) > 0
        )
        reg_income = float(dti.get("regular_income", 0))
        if reg_income > 0 and total_installment_payment > 0:
            pct = total_installment_payment / reg_income * 100
            if pct > 15:
                moments.append({
                    "id": "installment_heavy",
                    "category": "installment",
                    "severity": "warning",
                    "title": "Рассрочки съедают доход",
                    "message": (
                        f"На рассрочки уходит {pct:.0f}% дохода ({_fmt(total_installment_payment)}/мес)."
                    ),
                    "requires_purchases": False,
                })

        if dti_pct is not None and dti_pct >= 40 and total_installment_payment > 0:
            moments.append({
                "id": "installment_plus_dti",
                "category": "installment",
                "severity": "alert",
                "title": "Рассрочки при высокой нагрузке",
                "message": (
                    f"Нагрузка уже {dti_pct:.0f}%, а рассрочки добавляют ещё "
                    f"{_fmt(total_installment_payment)}/мес. Новые рассрочки — риск."
                ),
                "requires_purchases": False,
            })

        # -- Detailed installment moments (require InstallmentPurchase) --

        if _INSTALLMENT_AVAILABLE:
            ic_ids = [a.id for a in ic_accounts]
            if ic_ids:
                purchases = (
                    self.db.query(InstallmentPurchase)
                    .filter(
                        InstallmentPurchase.account_id.in_(ic_ids),
                        InstallmentPurchase.status == "active",
                    )
                    .all()
                )

                if len(purchases) >= 3:
                    total = sum(float(p.monthly_payment) for p in purchases)
                    moments.append({
                        "id": "many_active_purchases",
                        "category": "installment",
                        "severity": "info",
                        "title": "Много активных рассрочек",
                        "message": (
                            f"{len(purchases)} рассрочек одновременно. Каждая кажется маленькой, "
                            f"но вместе — {_fmt(total)}/мес."
                        ),
                        "requires_purchases": True,
                    })

                for p in purchases:
                    if p.interest_rate > 0:
                        total_cost = float(p.monthly_payment) * p.term_months
                        original = float(p.original_amount)
                        if total_cost > original * 1.33:
                            overpay = total_cost - original
                            overpay_pct = (overpay / original) * 100
                            moments.append({
                                "id": "expensive_installment",
                                "category": "installment",
                                "severity": "warning",
                                "title": "Дорогая рассрочка",
                                "message": (
                                    f"«{p.description}» обойдётся в {_fmt(total_cost)} вместо "
                                    f"{_fmt(original)}. Переплата {_fmt(overpay)} ({overpay_pct:.0f}%)."
                                ),
                                "requires_purchases": True,
                            })

        # Sort: alert first, then warning, then info. Max 5.
        severity_order = {"alert": 0, "warning": 1, "info": 2}
        moments.sort(key=lambda m: severity_order.get(m["severity"], 3))
        return moments[:5]
