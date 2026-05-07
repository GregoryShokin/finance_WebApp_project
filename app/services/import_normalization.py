"""Three-stage normalization pipeline for import rows.

Replaces the scattered parse→enrich→v2 logic in build_preview() with an
explicit, typed pipeline:

    parsed, derived = normalize(raw_row=..., bank=..., account_id=...)
    suggestion      = enrich(parsed=parsed, derived=derived, ...)
    decision        = apply_decisions(parsed=parsed, derived=derived,
                                      suggestion=suggestion, ...)

Each function is a pure-ish transformation (no writes to DB) and can be
unit-tested in isolation.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from app.schemas.normalized_row import DecisionRow, DerivedRow, EnrichmentSuggestion, ParsedRow
from app.services.fingerprint_alias_service import FingerprintAliasService
from app.services.import_normalizer import ImportNormalizer
from app.services.import_normalizer_v2 import (
    ExtractedTokens,
    extract_tokens,
    fingerprint as compute_fingerprint,
    is_refund_like,
    is_transfer_like,
    normalize_skeleton,
    pick_refund_brand,
    pick_transfer_identifier,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (mirrored from import_service to avoid circular import)
# ---------------------------------------------------------------------------

RAW_TYPE_TO_OPERATION_TYPE: dict[str, str] = {
    "purchase": "regular",
    "transfer": "transfer",
    "investment_buy": "investment_buy",
    "investment_sell": "investment_sell",
    "credit_disbursement": "credit_disbursement",
    "credit_payment": "transfer",  # maps to transfer; requires_credit_split flag is set separately
    "credit_interest": "regular",
}

_RAW_TYPES_REQUIRING_CREDIT_SPLIT: frozenset[str] = frozenset({"credit_payment"})

_CREDIT_PAYMENT_KEYWORDS: frozenset[str] = frozenset({
    "погашение кредита",
    "оплата кредита",
    "оплата по кредиту",
    "платеж по кредиту",
    "платёж по кредиту",
    "ежемесячный платеж по кредиту",
    "ежемесячный платёж по кредиту",
    "погашение задолженности по кредиту",
    "loan payment",
    "loan repayment",
})

_ALLOWED_OPERATION_TYPES: frozenset[str] = frozenset({
    "regular",
    "transfer",
    "investment_buy",
    "investment_sell",
    "credit_disbursement",
    "debt",
    "refund",
    "adjustment",
})

# operation types that have no category and don't appear in income/expense metrics
_NON_ANALYTICS_OPERATION_TYPES: frozenset[str] = frozenset({
    "transfer",
    "investment_buy",
    "investment_sell",
    "credit_disbursement",
    "adjustment",
})

_normalizer = ImportNormalizer()


# ---------------------------------------------------------------------------
# normalize()
# ---------------------------------------------------------------------------


def normalize(
    *,
    raw_row: dict[str, str],
    field_mapping: dict[str, str | None],
    date_format: str,
    default_currency: str,
    bank: str,
    account_id: int,
    alias_service: FingerprintAliasService | None = None,
    brand_resolver: object | None = None,  # BrandResolverService — lazy type to avoid cycle
    user_id: int | None = None,
    row_index: int = 0,
) -> tuple[ParsedRow, DerivedRow]:
    """Parse a raw bank statement row and derive fingerprint / tokens.

    Phase order:
      1. parse  — call ImportNormalizer (may raise ImportRowValidationError)
      2. derive — compute skeleton, fingerprint, tokens (pure, no DB)

    The fingerprint always uses ParsedRow.description (the original bank text)
    so user edits to the display description never invalidate cluster matching.
    """
    # --- Phase 1.1: parse facts ---
    raw = _normalizer.normalize_row(
        raw_row=raw_row,
        field_mapping=field_mapping,
        date_format=date_format,
        default_currency=default_currency,
    )

    parsed = ParsedRow(
        date=datetime.fromisoformat(raw["date"]),
        amount=Decimal(raw["amount"]),
        currency=raw["currency"],
        direction=raw["direction"],
        description=raw["description"],
        raw_type=raw.get("raw_type") or None,
        balance_after=Decimal(raw["balance_after"]) if raw.get("balance_after") else None,
        source_reference=raw.get("source_reference") or None,
        account_hint=raw.get("account_hint") or None,
        counterparty_raw=raw.get("counterparty") or None,
    )

    # --- Phase 1.2: derive ---
    derived = _derive(
        parsed=parsed,
        bank=bank,
        account_id=account_id,
        alias_service=alias_service,
        brand_resolver=brand_resolver,
        user_id=user_id,
        row_index=row_index,
    )

    return parsed, derived


def _derive(
    *,
    parsed: ParsedRow,
    bank: str,
    account_id: int,
    alias_service: FingerprintAliasService | None = None,
    brand_resolver: object | None = None,
    user_id: int | None = None,
    row_index: int = 0,
) -> DerivedRow:
    """Compute DerivedRow from ParsedRow. Pure — no DB, no network."""
    description = parsed.description

    tokens = extract_tokens(description)
    skeleton = normalize_skeleton(description, tokens)

    # Transfer detection uses description keywords only (no enrichment yet).
    # This covers 95%+ of transfer rows; the 5% detected only via account
    # matching in description are handled by enrichment → apply_decisions.
    is_transfer = is_transfer_like(description)
    is_refund = is_refund_like(description)

    transfer_identifier = pick_transfer_identifier(tokens) if is_transfer else None

    fp = compute_fingerprint(
        bank,
        account_id,
        parsed.direction,
        skeleton,
        tokens.contract,
        transfer_identifier=transfer_identifier,
    )

    # Alias resolution (Level 3 cluster-merge): if the user previously attached
    # this fingerprint to another cluster, redirect it here.
    if alias_service is not None and user_id is not None:
        try:
            resolved_fp = alias_service.resolve(user_id=user_id, fingerprint=fp)
            if resolved_fp and resolved_fp != fp:
                fp = resolved_fp
        except Exception as exc:  # noqa: BLE001 — never block import
            logger.warning("fingerprint alias resolve failed row=%s: %s", row_index, exc)

    refund_brand = pick_refund_brand(description, tokens) if is_refund else None

    requires_credit_split_hint = (parsed.raw_type or "").strip().lower() in _RAW_TYPES_REQUIRING_CREDIT_SPLIT

    brand_match = None
    if brand_resolver is not None and user_id is not None:
        try:
            brand_match = brand_resolver.resolve(
                skeleton=skeleton, tokens=tokens, user_id=user_id,
            )
        except Exception as exc:  # noqa: BLE001 — never block import on resolver
            logger.warning("brand resolver failed row=%s: %s", row_index, exc)

    return DerivedRow(
        skeleton=skeleton,
        fingerprint=fp,
        tokens=tokens,
        transfer_identifier=transfer_identifier,
        is_transfer_like=is_transfer,
        is_refund_like=is_refund,
        refund_brand=refund_brand,
        requires_credit_split_hint=requires_credit_split_hint,
        normalizer_version=2,
        brand_match=brand_match,
    )


# ---------------------------------------------------------------------------
# enrich()
# ---------------------------------------------------------------------------


def enrich(
    *,
    parsed: ParsedRow,
    derived: DerivedRow,
    enrichment_service: object,  # TransactionEnrichmentService — avoid circular import
    user_id: int,
    session_account_id: int | None,
    accounts_cache: list | None = None,
    categories_cache: list | None = None,
    history_sample_cache: list | None = None,
) -> EnrichmentSuggestion:
    """Thin wrapper: converts ParsedRow → dict payload → calls enrichment service → EnrichmentSuggestion.

    EnrichmentSuggestion is ephemeral — it must NOT be persisted to DB.
    """
    payload = {
        "description": parsed.description,
        "operation_type": parsed.raw_type or "",
        "type": parsed.raw_type or "",
        "counterparty": parsed.counterparty_raw or "",
        "account_hint": parsed.account_hint or "",
        "direction": parsed.direction,
        "amount": str(parsed.amount),
        "currency": parsed.currency,
    }

    result: dict = enrichment_service.enrich_import_row(  # type: ignore[union-attr]
        user_id=user_id,
        session_account_id=session_account_id,
        normalized_payload=payload,
        accounts_cache=accounts_cache,
        categories_cache=categories_cache,
        history_sample_cache=history_sample_cache,
    )

    return EnrichmentSuggestion(
        suggested_account_id=result.get("suggested_account_id"),
        suggested_target_account_id=result.get("suggested_target_account_id"),
        suggested_category_id=result.get("suggested_category_id"),
        suggested_operation_type=result.get("suggested_operation_type") or "regular",
        suggested_type=result.get("suggested_type") or parsed.direction or "expense",
        normalized_description=result.get("normalized_description"),
        assignment_confidence=float(result.get("assignment_confidence") or 0.0),
        assignment_reasons=list(result.get("assignment_reasons") or []),
        review_reasons=list(result.get("review_reasons") or []),
        needs_manual_review=bool(result.get("needs_manual_review")),
    )


# ---------------------------------------------------------------------------
# apply_decisions()
# ---------------------------------------------------------------------------


def apply_decisions(
    *,
    parsed: ParsedRow,
    derived: DerivedRow,
    suggestion: EnrichmentSuggestion,
    category_rule: object | None,  # TransactionCategoryRule | None
    session_account_id: int,
) -> DecisionRow:
    """Produce DecisionRow from parsed facts + derived signals + enrichment hints.

    operation_type priority ladder (highest → lowest):
      1. Rule.operation_type — learned via Этап 2 once `confirms >=
         RULE_ACTIVATE_CONFIRMS` AND `rejections == 0`. The rule is a
         direct statement of user intent ("каждый раз помечал debt") and
         outranks every keyword/raw_type signal below.
      2. derived.requires_credit_split_hint → "transfer" (raw_type-based)
      3. parsed.raw_type in RAW_TYPE_TO_OPERATION_TYPE → mapped value
      4. derived.is_refund_like → "refund"
      5. derived.is_transfer_like → "transfer"
      6. suggestion.suggested_operation_type (enrichment, weakest)
    Post-ladder:
      7. Description/skeleton keyword credit-split detection (only when op=transfer)
    """

    # --- (1) Rule-learned operation_type (Этап 2) ---
    decision_reasons: list[str] = []
    rule_op_type: str | None = None
    rule_id_for_audit: int | None = None
    if category_rule is not None:
        rule_op_type_raw = getattr(category_rule, "operation_type", None)
        rule_confirms = getattr(category_rule, "confirms", None)
        rule_is_active = getattr(category_rule, "is_active", False)
        if rule_op_type_raw and rule_is_active:
            # Local import keeps test-time mocking + circular-import-free.
            from app.core.config import settings as _settings
            try:
                threshold = Decimal(str(_settings.RULE_ACTIVATE_CONFIRMS))
            except Exception:  # noqa: BLE001 — settings shape oddity, fail open
                threshold = Decimal("3")
            try:
                confirms_decimal = (
                    rule_confirms if isinstance(rule_confirms, Decimal)
                    else Decimal(str(rule_confirms or 0))
                )
            except Exception:  # noqa: BLE001 — non-numeric mock or stub; rule never wins
                confirms_decimal = Decimal("0")
            if confirms_decimal >= threshold:
                rule_op_type = str(rule_op_type_raw).strip()
                rule_id_for_audit = getattr(category_rule, "id", None)

    requires_credit_split = derived.requires_credit_split_hint
    operation_type: str

    if rule_op_type:
        operation_type = rule_op_type
        decision_reasons.append(
            f"operation_type из обученного правила #{rule_id_for_audit}"
            if rule_id_for_audit is not None
            else "operation_type из обученного правила"
        )
        # Diagnostic: if a keyword signal points the other way, log so we can
        # spot rules that learned the wrong thing (e.g. "Возврат от Иван"
        # was 5× confirmed as debt — rule wins, but the conflict deserves
        # eyeballs in logs). Not user-facing.
        keyword_signal: str | None = None
        if derived.is_refund_like and rule_op_type != "refund":
            keyword_signal = "refund"
        elif derived.is_transfer_like and rule_op_type != "transfer":
            keyword_signal = "transfer"
        if keyword_signal is not None:
            logger.debug(
                "rule-keyword op_type conflict",
                extra={
                    "rule_id": rule_id_for_audit,
                    "rule_op_type": rule_op_type,
                    "keyword_signal": keyword_signal,
                    "skeleton": derived.skeleton[:80],
                },
            )

    # --- (2) Credit split from raw_type ---
    elif requires_credit_split:
        operation_type = "transfer"

    # --- (3) raw_type mapping ---
    elif (parsed.raw_type or "").strip().lower() in RAW_TYPE_TO_OPERATION_TYPE:
        operation_type = RAW_TYPE_TO_OPERATION_TYPE[(parsed.raw_type or "").strip().lower()]

    # --- (4) refund signal ---
    elif derived.is_refund_like:
        operation_type = "refund"

    # --- (5) transfer signal ---
    elif derived.is_transfer_like:
        operation_type = "transfer"

    # --- (6) enrichment suggestion ---
    else:
        operation_type = suggestion.suggested_operation_type or "regular"

    if operation_type not in _ALLOWED_OPERATION_TYPES:
        operation_type = "regular"

    # --- (7) Description-keyword credit-split detection (only when op=transfer) ---
    if not requires_credit_split and operation_type == "transfer":
        desc_lc = parsed.description.lower()
        skel_lc = derived.skeleton.lower()
        if any(kw in desc_lc or kw in skel_lc for kw in _CREDIT_PAYMENT_KEYWORDS):
            requires_credit_split = True

    # --- Category from rule or enrichment ---
    if category_rule is not None:
        category_id: int | None = getattr(category_rule, "category_id", None)
        applied_rule_id: int | None = getattr(category_rule, "id", None)
        applied_rule_category_id: int | None = category_id
        decision_source = "rule"
    else:
        category_id = suggestion.suggested_category_id
        applied_rule_id = None
        applied_rule_category_id = None
        decision_source = "enrichment"

    # Transfers and non-analytics types have no category.
    if operation_type in _NON_ANALYTICS_OPERATION_TYPES:
        category_id = None

    # --- Transaction type (income / expense) ---
    transaction_type = suggestion.suggested_type or parsed.direction or "expense"

    # --- Account routing ---
    if operation_type == "transfer":
        # account_id always = session account ("счёт из выписки"), regardless of direction.
        account_id: int | None = session_account_id
        if transaction_type == "income":
            # Income transfer: session account received money.
            # target_account_id = the source (where money came from).
            target: int | None = suggestion.suggested_account_id
            if target == session_account_id:
                target = None
            target_account_id: int | None = target
        else:
            # Expense transfer: session account sent money.
            # target_account_id = the destination.
            target_account_id = suggestion.suggested_target_account_id
    else:
        account_id = suggestion.suggested_account_id or session_account_id
        target_account_id = suggestion.suggested_target_account_id

    return DecisionRow(
        account_id=account_id,
        target_account_id=target_account_id,
        category_id=category_id,
        operation_type=operation_type,
        type=transaction_type,
        counterparty_id=None,
        debt_partner_id=None,
        requires_credit_split=requires_credit_split,
        credit_account_id=None,
        credit_principal_amount=None,
        credit_interest_amount=None,
        split_items=None,
        description_override=None,
        applied_rule_id=applied_rule_id,
        applied_rule_category_id=applied_rule_category_id,
        decision_source=decision_source,
        assignment_reasons=decision_reasons,
    )
