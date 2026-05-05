"""Per-row preview processor (spec §3, §4, §6, §8, §10.1, §12.1).

Encapsulates Phase 1-4 of `build_preview` for a single raw row:

  1. Parse facts (ImportNormalizer) + derive skeleton/fingerprint/tokens (v2).
  2. Run enrichment to suggest account / category / operation_type.
  3. Look up the best matching category rule for the skeleton.
  4. Apply decisions and gate the row through:
       • §12.1 transfer-integrity (preview, not final)
       • §8.1 duplicate detection against committed transactions
       • §5.2 quality warnings (manual review, missing category)

Returns a `ProcessedRow` dataclass — the caller persists it via
`ImportRepository.create_row`. The processor itself does NO DB writes.

Extracted from `import_service.build_preview` 2026-04-29 as step 8 of the §1
backlog god-object decomposition. The remaining `build_preview` is a thin
session-level orchestrator: setup, loop over rows calling this processor,
persist, run async/post-processors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.repositories.transaction_category_rule_repository import TransactionCategoryRuleRepository
from app.schemas.import_normalized import NormalizedDataV2
from app.schemas.normalized_row import EnrichmentSuggestion as _EnrichmentSuggestion
from app.services.import_normalization import apply_decisions as _apply_import_decisions
from app.services.import_normalization import normalize as _normalize_import_row
from app.services.import_post_processor import ImportPostProcessor
from app.services.import_validator import ImportRowValidationError
from app.services.transaction_enrichment_service import TransactionEnrichmentService
from app.services.transaction_service import TransactionValidationError


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


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError("Некорректный формат даты транзакции.")


@dataclass
class ProcessedRow:
    """Result of processing a single raw row through Phase 1-4."""

    normalized: dict[str, Any] = field(default_factory=dict)
    status: str = "ready"
    issues: list[str] = field(default_factory=list)
    unresolved_fields: list[str] = field(default_factory=list)
    error_message: str | None = None
    duplicate: bool = False


class PreviewRowProcessor:
    def __init__(
        self,
        db: Session,
        *,
        category_rule_repo: TransactionCategoryRuleRepository,
        enrichment: TransactionEnrichmentService,
        find_duplicate_fn: Callable[..., bool],
        alias_service: Any,
    ) -> None:
        self.db = db
        self.category_rule_repo = category_rule_repo
        self.enrichment = enrichment
        self._find_duplicate = find_duplicate_fn
        self._alias_service = alias_service

    def process(
        self,
        *,
        raw_row: dict[str, Any],
        row_index: int,
        user_id: int,
        session_account_id: int,
        bank_code: str | None,
        bank_for_normalize: str,
        field_mapping: dict[str, Any],
        date_format: str | None,
        default_currency: str,
        skip_duplicates: bool,
        accounts_cache: list[Any],
        categories_cache: list[Any],
        history_sample_cache: list[Any],
    ) -> ProcessedRow:
        result = ProcessedRow()

        try:
            # Phase 1 — parse facts + derive skeleton/fingerprint.
            parsed, derived = _normalize_import_row(
                raw_row=raw_row,
                field_mapping=field_mapping,
                date_format=date_format,
                default_currency=default_currency,
                bank=bank_for_normalize,
                account_id=session_account_id,
                alias_service=self._alias_service,
                user_id=user_id,
                row_index=row_index,
            )

            # Build facts-only normalized dict (decisions follow in Phase 4).
            normalized: dict[str, Any] = {
                "date": parsed.date.isoformat(),
                "description": parsed.description,
                "import_original_description": parsed.description,
                "amount": str(parsed.amount),
                "currency": parsed.currency,
                "direction": parsed.direction,
                "raw_type": parsed.raw_type,
                "balance_after": str(parsed.balance_after) if parsed.balance_after else None,
                "source_reference": parsed.source_reference,
                "account_hint": parsed.account_hint,
                "counterparty": parsed.counterparty_raw,
            }
            v2_model = NormalizedDataV2.from_tokens(
                tokens=derived.tokens,
                skeleton=derived.skeleton,
                fingerprint=derived.fingerprint,
                is_refund=derived.is_refund_like,
                refund_brand=derived.refund_brand,
            )
            normalized = v2_model.merge_into(normalized)
            if bank_code:
                normalized["bank_code"] = bank_code

            # Phase 2 — enrichment (ephemeral, not persisted).
            enrichment_dict = self.enrichment.enrich_import_row(
                user_id=user_id,
                session_account_id=session_account_id,
                accounts_cache=accounts_cache,
                categories_cache=categories_cache,
                history_sample_cache=history_sample_cache,
                normalized_payload=normalized,
            )
            suggestion = _EnrichmentSuggestion(
                suggested_account_id=enrichment_dict.get("suggested_account_id"),
                suggested_target_account_id=enrichment_dict.get("suggested_target_account_id"),
                suggested_category_id=enrichment_dict.get("suggested_category_id"),
                suggested_operation_type=enrichment_dict.get("suggested_operation_type") or "regular",
                suggested_type=enrichment_dict.get("suggested_type") or parsed.direction or "expense",
                normalized_description=enrichment_dict.get("normalized_description"),
                assignment_confidence=float(enrichment_dict.get("assignment_confidence") or 0.0),
                assignment_reasons=list(enrichment_dict.get("assignment_reasons") or []),
                review_reasons=list(enrichment_dict.get("review_reasons") or []),
                needs_manual_review=bool(enrichment_dict.get("needs_manual_review")),
            )

            # Phase 3 — rule lookup.
            # Этап 2: `want_op_type=True` runs a two-pass search — rules
            # with explicit operation_type win over legacy NULL rules at
            # equal-or-lower confirms. The result drives BOTH the category
            # AND the operation_type decision in apply_decisions (single
            # repo round-trip per row).
            norm_desc = suggestion.normalized_description or ""
            cat_rule = (
                self.category_rule_repo.get_best_rule(
                    user_id=user_id,
                    normalized_description=norm_desc,
                    want_op_type=True,
                )
                if norm_desc
                else None
            )

            # Phase 4 — decisions: single source of truth for op_type / cat / accs.
            decision = _apply_import_decisions(
                parsed=parsed,
                derived=derived,
                suggestion=suggestion,
                category_rule=cat_rule,
                session_account_id=session_account_id,
            )

            normalized["account_id"] = decision.account_id
            normalized["target_account_id"] = decision.target_account_id
            normalized["category_id"] = decision.category_id
            normalized["operation_type"] = decision.operation_type
            normalized["type"] = decision.type
            normalized["requires_credit_split"] = decision.requires_credit_split
            if decision.applied_rule_id is not None:
                normalized["applied_rule_id"] = decision.applied_rule_id
                normalized["applied_rule_category_id"] = decision.applied_rule_category_id
            else:
                normalized.pop("applied_rule_id", None)
                normalized.pop("applied_rule_category_id", None)

            # §12.1 / §5.2 — transfer integrity gate (preview, final=False).
            if decision.operation_type == "transfer":
                result.status, result.issues = ImportPostProcessor.gate_transfer_integrity(
                    normalized=normalized,
                    current_status=result.status,
                    issues=result.issues,
                )

            amount_decimal = _to_decimal(normalized.get("amount"))
            transaction_dt = _to_datetime(normalized.get("date"))

            current_op_type = decision.operation_type
            raw_account_id = decision.account_id
            if raw_account_id in (None, 0):
                if current_op_type == "transfer":
                    # §12.1 + matcher window: keep as warning so the
                    # cross-session matcher (filters by ready/warning) can
                    # still see the row.
                    result.issues.append("Не удалось определить счёт из выписки — укажи вручную.")
                    if result.status not in ("error", "duplicate"):
                        result.status = "warning"
                current_account_id = 0
            else:
                current_account_id = int(raw_account_id)

            # §8.1 dedup against committed transactions only (transfer-side
            # duplicates are handled by transfer_matcher_service post-preview).
            duplicate = result.status != "duplicate" and self._find_duplicate(
                user_id=user_id,
                account_id=current_account_id,
                amount=amount_decimal,
                transaction_date=transaction_dt,
                skeleton=derived.skeleton,
                normalized_description=suggestion.normalized_description,
                transaction_type=decision.type,
                contract=derived.tokens.contract,
            )
            result.duplicate = duplicate
            if duplicate and skip_duplicates:
                result.status = "duplicate"
                result.issues.append("Похоже на уже существующую транзакцию.")
            elif duplicate:
                result.status = "warning"
                result.issues.append("Возможный дубликат, проверь перед импортом.")

            if suggestion.needs_manual_review and result.status == "ready":
                result.status = "warning"

            requires_category = decision.operation_type in ("regular", "refund")
            if requires_category and not decision.category_id:
                result.issues.append("Категория не определена — укажи вручную.")
                if result.status == "ready":
                    result.status = "warning"

            # §9.3 / §5.2: credit-split rows always need principal + interest
            # amounts which are user-supplied and never auto-filled at preview
            # time. Even when the credit account is already resolved, the row
            # cannot be "ready" without the amounts — flag it as warning so the
            # user is prompted to open the pencil editor and fill them in.
            if decision.requires_credit_split and result.status == "ready":
                has_principal = normalized.get("credit_principal_amount") not in (None, "", "0", "0.00")
                has_interest = normalized.get("credit_interest_amount") not in (None, "", "0", "0.00")
                if not has_principal or not has_interest:
                    result.issues.append("Укажи основной долг и проценты для кредитного платежа.")
                    result.status = "warning"

            result.issues.extend(suggestion.review_reasons)
            result.issues.extend(suggestion.assignment_reasons)
            # Этап 2: rule-based decisions (e.g. operation_type from a learned
            # rule) emit their own reasons in DecisionRow.assignment_reasons.
            # Surface them so the audit log and UI explain WHY the row was
            # classified that way.
            result.issues.extend(decision.assignment_reasons)
            result.normalized = normalized

        except (
            ImportRowValidationError, TransactionValidationError,
            ValueError, TypeError, InvalidOperation,
        ) as exc:
            result.status = "error"
            result.error_message = str(exc)
            result.issues.append(str(exc))

        result.issues = list(dict.fromkeys(item for item in result.issues if item))
        return result
