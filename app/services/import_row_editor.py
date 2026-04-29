"""Single-row editor for the import moderator (spec §5.2, §5.3, §10.3, §12.x).

Owns:
  • `update_row` — apply user edits to a single import row, set status
    transitions (confirm / restore / exclude / silent edit), enforce the
    rule-stat invariant (no rejection on intermediate edits — §10.3).
  • `_validate_manual_row` — full structural validation: required fields per
    operation_type, transfer integrity, credit-payment split, multi-part split
    items, regular-row category requirement, etc. Returns a (status, issues)
    tuple via monotonic escalation (ready < warning < error, §5.2).

Extracted from `import_service.py` 2026-04-29 as step 7 of the §1 backlog
god-object decomposition. Pure delegation: caller owns DB session + commit.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.repositories.import_repository import ImportRepository
from app.schemas.imports import ImportRowUpdateRequest


class ImportNotFoundError(Exception):
    pass


class ImportValidationError(Exception):
    pass


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        cleaned = value.strip().replace(" ", "").replace(",", ".")
        if not cleaned:
            raise ValueError("Пустое значение суммы.")
        return Decimal(cleaned)
    raise TypeError("Некорректный формат суммы.")


# Set of validation messages that act as commit blockers — surfacing any of
# them on a row prevents the resolution step from downgrading status to ready.
# Russian strings appear here as mojibake (cp1251-as-utf8) because the legacy
# inline code accumulated them that way; preserving exact byte sequences keeps
# the existing tests / UI strings working.
BLOCKING_MESSAGES: frozenset[str] = frozenset({
    "Не указан счёт.",
    "Не указан счёт поступления.",
    "Не указан счёт отправителя.",
    "Не выбран кредитный счёт.",
    "Не выбрана категория.",
    "Разбивка заполнена некорректно.",
    "Сумма разбивки должна совпадать с суммой транзакции.",
    "В разбивке каждая часть должна быть больше нуля.",
    "В разбивке для каждой части нужна категория.",
    "Для платежа по кредиту нужно указать основной долг.",
    "Для платежа по кредиту нужно указать проценты.",
    "Сумма основного долга и процентов должна совпадать с общей суммой платежа.",
    "Основной долг и проценты не могут быть отрицательными.",
    "Пустое описание операции.",
    "Не указана дата операции.",
    "Некорректная сумма.",
    "Счёт списания и счёт поступления не должны совпадать.",
})


class ImportRowEditor:
    def __init__(
        self,
        db: Session,
        *,
        import_repo: ImportRepository,
        recalculate_summary_fn: Callable[[int], dict[str, Any]],
        serialize_row_fn: Callable[[Any], dict[str, Any]],
    ) -> None:
        self.db = db
        self.import_repo = import_repo
        self._recalculate_summary = recalculate_summary_fn
        self._serialize_row = serialize_row_fn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_row(
        self, *, user_id: int, row_id: int, payload: ImportRowUpdateRequest,
    ) -> dict[str, Any]:
        session_row = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
        if session_row is None:
            raise ImportNotFoundError("Строка импорта не найдена.")

        session, row = session_row
        row_status = str(row.status or "").strip().lower()
        if row.created_transaction_id is not None or row_status == "committed":
            raise ImportValidationError("Импортированную строку нельзя изменить.")

        normalized = dict(getattr(row, "normalized_data", None) or (row.normalized_data_json or {}))

        # §10.3: rejections are counted ONLY on commit, not on intermediate
        # user edits ("поменял → вернул как было" must not leave a rejection
        # trace). Keep applied_rule_id + applied_rule_category_id intact here;
        # the commit path compares them against the final category_id and
        # routes to Case A/B (match → confirm) or Case C (diff → reject old +
        # create new). This reflects §10.2 Cases A/B/C.

        for field in (
            "account_id", "target_account_id", "credit_account_id", "category_id",
            "counterparty_id", "debt_partner_id", "amount", "type", "operation_type",
            "debt_direction", "description", "currency",
            "credit_principal_amount", "credit_interest_amount",
        ):
            value = getattr(payload, field)
            if value is not None:
                normalized[field] = value

        if payload.split_items is not None:
            normalized["split_items"] = [
                {
                    "operation_type": (item.operation_type or "regular"),
                    "category_id": item.category_id,
                    "target_account_id": item.target_account_id,
                    "debt_direction": item.debt_direction,
                    "counterparty_id": item.counterparty_id,
                    "debt_partner_id": item.debt_partner_id,
                    "amount": str(item.amount),
                    "description": item.description,
                }
                for item in payload.split_items
            ]

        if payload.transaction_date is not None:
            normalized["transaction_date"] = payload.transaction_date.isoformat()
            normalized["date"] = payload.transaction_date.isoformat()

        action = (payload.action or "").strip().lower()
        issues = [
            item for item in (getattr(row, "errors", None) or [])
            if item and item != "Исключено пользователем."
        ]
        status = row_status if row_status not in {"committed", "duplicate"} else row_status
        allow_ready_status = action == "confirm"

        if action == "exclude":
            status = "skipped"
            issues = list(dict.fromkeys([*issues, "Исключено пользователем."]))
        else:
            if action == "restore" and row_status == "skipped":
                status = "warning"
            elif action == "confirm":
                # §5.4 / §10.2 (v1.1): individual confirm is a full-touch
                # signal — the user read THIS row and vouched for it. Stamp
                # user_confirmed_at so commit can: (a) let the row through,
                # (b) apply Case A weight 1.0 (not 0.5).
                #
                # v1.8: stamp regardless of prior status. Auto-trust rows can
                # later flip back to attention on cluster recompute (§1.2
                # honesty gate); the user already explicitly confirmed once —
                # without the stamp the UI keeps demanding re-confirmation.
                normalized["user_confirmed_at"] = datetime.now(timezone.utc).isoformat()
                normalized.pop("cluster_bulk_acked_at", None)
                status = "ready"
                # If auto-detected as transfer but has no target, revert to
                # regular so the user can confirm without a validation blocker.
                if (
                    str(normalized.get("operation_type") or "") == "transfer"
                    and not normalized.get("target_account_id")
                ):
                    normalized["operation_type"] = "regular"
                    normalized.pop("transfer_match", None)
            elif row_status in {"ready", "warning"}:
                status = "warning"

            status, issues = self.validate_manual_row(
                normalized=normalized,
                current_status=status,
                issues=issues,
                allow_ready_status=allow_ready_status,
            )

        row = self.import_repo.update_row(
            row,
            normalized_data=normalized,
            status=status,
            errors=issues,
            review_required=status in {"warning", "error"},
        )

        summary = self._recalculate_summary(session.id)
        session.summary_json = summary
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        self.db.refresh(row)
        self.import_repo._hydrate_row_runtime_fields(row)

        return {
            "session_id": session.id,
            "row": self._serialize_row(row),
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # Validation helper
    # ------------------------------------------------------------------

    def validate_manual_row(
        self,
        *,
        normalized: dict[str, Any],
        current_status: str,
        issues: list[str],
        allow_ready_status: bool = True,
    ) -> tuple[str, list[str]]:
        status = current_status
        local_issues = [item for item in issues if item]

        # §5.2 (v1.1): status priority is ready < warning < error. Once a
        # data-integrity error fires, a subsequent quality warning must NOT
        # downgrade it. Use _escalate() instead of bare `status = "warning"`.
        priority = {"ready": 0, "skipped": 0, "warning": 1, "error": 2}

        def _escalate(new: str) -> str:
            nonlocal status
            if priority.get(new, 0) > priority.get(status, 0):
                status = new
            return status

        if status == "skipped":
            return status, list(dict.fromkeys(local_issues))

        local_issues = [item for item in local_issues if item not in BLOCKING_MESSAGES]

        account_id = normalized.get("account_id")
        operation_type = normalized.get("operation_type") or "regular"
        amount = normalized.get("amount")

        # §12.3: operation_type="credit_payment" is forbidden. If the moderator
        # UI submits it as a meta-signal ("user tapped split button"), fold it
        # into (operation_type=transfer + requires_credit_split=True) so the
        # stored normalized_data never carries the forbidden value.
        if operation_type == "credit_payment":
            normalized["requires_credit_split"] = True
            normalized["operation_type"] = "transfer"
            operation_type = "transfer"

        if account_id in (None, "", 0):
            local_issues.append("Не указан счёт.")
            status = "error"

        amount_decimal = None
        try:
            if amount not in (None, ""):
                amount_decimal = _to_decimal(amount)
        except (ValueError, TypeError, InvalidOperation):
            local_issues.append("Некорректная сумма.")
            status = "error"

        if operation_type == "transfer" and not normalized.get("requires_credit_split"):
            target_account_id = normalized.get("target_account_id")
            tx_type = str(normalized.get("type") or "expense")
            normalized["credit_account_id"] = None
            normalized["credit_principal_amount"] = None
            normalized["credit_interest_amount"] = None
            if target_account_id in (None, "", 0):
                # §12.1 / §5.2 (v1.1): transfer with only one known account is
                # forbidden — promoted from warning to error so bulk-ack can't
                # sneak it through.
                missing_msg = (
                    "Не указан счёт отправителя." if tx_type == "income"
                    else "Не указан счёт поступления."
                )
                local_issues.append(missing_msg)
                status = "error"
            elif str(target_account_id) == str(account_id):
                local_issues.append("Счёт списания и счёт поступления не должны совпадать.")
                status = "error"
            normalized["category_id"] = None
            normalized["split_items"] = []
        elif operation_type == "credit_disbursement":
            normalized["target_account_id"] = None
            normalized["credit_account_id"] = None
            normalized["credit_principal_amount"] = None
            normalized["credit_interest_amount"] = None
            normalized["category_id"] = None
            normalized["split_items"] = []
        elif operation_type == "credit_early_repayment":
            credit_account_id = (
                normalized.get("target_account_id")
                or normalized.get("credit_account_id")
            )
            normalized["target_account_id"] = credit_account_id
            normalized["credit_account_id"] = credit_account_id
            normalized["category_id"] = None
            normalized["split_items"] = []
            normalized["credit_principal_amount"] = None
            normalized["credit_interest_amount"] = None
            if credit_account_id in (None, "", 0):
                local_issues.append("Не выбран кредитный счёт.")
                _escalate("warning")
        elif operation_type == "transfer" and normalized.get("requires_credit_split"):
            # §9.3: split into interest + principal at commit time.
            credit_account_id = (
                normalized.get("credit_account_id")
                or normalized.get("target_account_id")
            )
            normalized["category_id"] = None
            normalized["split_items"] = []
            normalized["target_account_id"] = credit_account_id
            normalized["credit_account_id"] = credit_account_id
            if credit_account_id in (None, "", 0):
                local_issues.append("Не выбран кредитный счёт.")
                _escalate("warning")

            principal_raw = normalized.get("credit_principal_amount")
            interest_raw = normalized.get("credit_interest_amount")
            principal_amount = None
            interest_amount = None

            if principal_raw in (None, ""):
                local_issues.append("Для платежа по кредиту нужно указать основной долг.")
                _escalate("warning")
            else:
                try:
                    principal_amount = _to_decimal(principal_raw)
                except (ValueError, TypeError, InvalidOperation):
                    local_issues.append("Некорректная сумма.")
                    _escalate("error")

            if interest_raw in (None, ""):
                local_issues.append("Для платежа по кредиту нужно указать проценты.")
                _escalate("warning")
            else:
                try:
                    interest_amount = _to_decimal(interest_raw)
                except (ValueError, TypeError, InvalidOperation):
                    local_issues.append("Некорректная сумма.")
                    status = "error"

            if principal_amount is not None and interest_amount is not None:
                if principal_amount < 0 or interest_amount < 0:
                    local_issues.append("Основной долг и проценты не могут быть отрицательными.")
                    status = "error"
                elif amount_decimal is not None and principal_amount + interest_amount != amount_decimal:
                    # Banks sometimes round principal/interest by a few kopecks.
                    # Snap interest to match total when off by ≤1 RUB; larger
                    # gaps are real user errors.
                    diff = amount_decimal - (principal_amount + interest_amount)
                    if abs(diff) <= Decimal("1.00"):
                        interest_amount = interest_amount + diff
                    else:
                        local_issues.append(
                            "Sum of principal + interest does not match total (off by more than 1 RUB)"
                        )
                        status = "error"
                normalized["credit_principal_amount"] = str(principal_amount)
                normalized["credit_interest_amount"] = str(interest_amount)
        elif operation_type == "regular":
            split_items = normalized.get("split_items") or []
            normalized["target_account_id"] = None
            if split_items:
                # Multi-part split: each part has its own operation_type.
                ALLOWED_PART_TYPES = {
                    "regular", "transfer", "refund", "debt",
                    "investment_buy", "investment_sell",
                    "credit_disbursement", "credit_early_repayment",
                }
                ALLOWED_DEBT_DIRS = {"borrowed", "lent", "repaid", "collected"}
                valid_split = True
                split_total = Decimal("0")
                cleaned_split_items: list[dict[str, Any]] = []
                for item in split_items:
                    if not isinstance(item, dict):
                        valid_split = False
                        local_issues.append("Разбивка заполнена некорректно.")
                        break

                    part_op = str(item.get("operation_type") or "regular").lower()
                    if part_op not in ALLOWED_PART_TYPES:
                        valid_split = False
                        local_issues.append(f"Неизвестный тип операции в части разбивки: {part_op}.")
                        break

                    raw_amount = item.get("amount")
                    description = item.get("description")
                    try:
                        split_amount = _to_decimal(raw_amount)
                    except (ValueError, TypeError, InvalidOperation):
                        valid_split = False
                        local_issues.append("Разбивка заполнена некорректно.")
                        break
                    if split_amount <= 0:
                        valid_split = False
                        local_issues.append("В разбивке каждая часть должна быть больше нуля.")
                        break

                    category_id = item.get("category_id")
                    target_account_id = item.get("target_account_id")
                    debt_direction = item.get("debt_direction")
                    counterparty_id = item.get("counterparty_id")
                    debt_partner_id = item.get("debt_partner_id")

                    if part_op in ("regular", "refund"):
                        if category_id in (None, "", 0):
                            valid_split = False
                            local_issues.append("В разбивке для каждой части нужна категория.")
                            break
                    if part_op == "debt":
                        if not debt_direction or str(debt_direction).lower() not in ALLOWED_DEBT_DIRS:
                            valid_split = False
                            local_issues.append(
                                "В части-долге укажи направление: занял/одолжил/возврат/получил."
                            )
                            break
                        if debt_partner_id in (None, "", 0):
                            valid_split = False
                            local_issues.append("В части-долге укажи дебитора / кредитора.")
                            break
                    if part_op == "transfer":
                        if target_account_id in (None, "", 0):
                            valid_split = False
                            local_issues.append("В части-переводе укажи счёт назначения.")
                            break

                    cleaned_split_items.append({
                        "operation_type": part_op,
                        "category_id": int(category_id) if category_id not in (None, "", 0) else None,
                        "target_account_id": int(target_account_id) if target_account_id not in (None, "", 0) else None,
                        "debt_direction": str(debt_direction).lower() if debt_direction else None,
                        "counterparty_id": int(counterparty_id) if counterparty_id not in (None, "", 0) else None,
                        "debt_partner_id": int(debt_partner_id) if debt_partner_id not in (None, "", 0) else None,
                        "amount": str(split_amount),
                        "description": description,
                    })
                    split_total += split_amount

                if valid_split and amount_decimal is not None and split_total != amount_decimal:
                    valid_split = False
                    local_issues.append("Сумма разбивки должна совпадать с суммой транзакции.")

                if valid_split and len(cleaned_split_items) >= 2:
                    normalized["split_items"] = cleaned_split_items
                    normalized["category_id"] = None
                else:
                    _escalate("warning")
            else:
                normalized["split_items"] = []
                if normalized.get("category_id") in (None, "", 0):
                    local_issues.append("Не выбрана категория.")
                    _escalate("warning")
        elif operation_type == "refund":
            normalized["target_account_id"] = None
            normalized["split_items"] = []
            if normalized.get("category_id") in (None, "", 0):
                local_issues.append("Не выбрана категория.")
                _escalate("warning")
        else:
            normalized["target_account_id"] = None
            normalized["category_id"] = None
            normalized["split_items"] = []

        if not normalized.get("description"):
            local_issues.append("Пустое описание операции.")
            _escalate("warning")

        if not normalized.get("transaction_date") and not normalized.get("date"):
            local_issues.append("Не указана дата операции.")
            status = "error"

        unique_issues = list(dict.fromkeys(local_issues))

        # §5.2 (v1.1): error is sticky. Once any integrity check escalated
        # status to error, do NOT downgrade to ready/warning at resolution.
        if status != "duplicate" and status != "error":
            unresolved = [item for item in unique_issues if item in BLOCKING_MESSAGES]
            if unresolved:
                status = status if status in {"warning", "error", "skipped"} else "warning"
            elif allow_ready_status:
                status = "ready"
            elif status not in {"error", "skipped"}:
                status = "warning"

        return status, unique_issues
