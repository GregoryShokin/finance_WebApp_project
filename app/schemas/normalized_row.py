"""Typed pipeline stages for the import normalization pipeline.

Four dataclasses represent four distinct stages of a single import row's
lifecycle. Keeping them separate makes the data flow explicit and prevents
accidental mutation of facts that should be immutable.

Stage order:
    ParsedRow   — raw facts extracted from the bank statement (immutable)
    DerivedRow  — deterministic derivations: skeleton, fingerprint, tokens
    EnrichmentSuggestion — ephemeral hints from TransactionEnrichmentService
                           (NOT persisted to DB — response DTO only)
    DecisionRow — final mutable decisions written by apply_decisions(),
                  transfer matcher, and dedup; used at commit time
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.services.import_normalizer_v2 import ExtractedTokens


@dataclass(frozen=True)
class ParsedRow:
    """Immutable facts from bank statement parsing.

    Fields here represent what the bank printed. They must not be edited
    by the user — if a bank error exists, the row should be excluded and
    a manual transaction created instead.
    """

    date: datetime
    amount: Decimal
    currency: str
    direction: str                   # "income" | "expense"
    description: str                 # original bank text — fingerprint always uses this
    raw_type: str | None             # bank's operation type if provided
    balance_after: Decimal | None
    source_reference: str | None     # bank transaction ID
    account_hint: str | None         # raw account hint from bank
    counterparty_raw: str | None     # raw counterparty name from bank


@dataclass(frozen=True)
class DerivedRow:
    """Deterministically computed from ParsedRow. Recomputable at any time.

    Fingerprint is always computed from ParsedRow.description (the original
    bank text), so user edits to the display description do not invalidate
    cluster matching across sessions.
    """

    skeleton: str                          # description with placeholders
    fingerprint: str                       # 16-char hex hash
    tokens: ExtractedTokens                # phone, contract, iban, card, org, …
    transfer_identifier: tuple[str, str] | None   # ("phone", "+7…") etc.
    is_transfer_like: bool
    is_refund_like: bool
    refund_brand: str | None               # merchant inferred from refund skeleton
    requires_credit_split_hint: bool       # from raw_type or description keyword
    normalizer_version: int                # = 2


@dataclass
class EnrichmentSuggestion:
    """Ephemeral hints from TransactionEnrichmentService.

    NOT persisted to DB. Lives only in the response DTO and is consumed by
    apply_decisions() to produce a DecisionRow.
    """

    suggested_account_id: int | None
    suggested_target_account_id: int | None
    suggested_category_id: int | None
    suggested_operation_type: str
    suggested_type: str              # "income" | "expense"
    normalized_description: str | None
    assignment_confidence: float
    assignment_reasons: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    needs_manual_review: bool = False


@dataclass
class DecisionRow:
    """Final mutable decisions for one import row.

    Written by apply_decisions() from (ParsedRow, DerivedRow, EnrichmentSuggestion,
    rules). Later phases (transfer matcher, dedup) may overwrite specific fields:
      - transfer_match / was_orphan_transfer — set by TransferMatcherService
      - duplicate_of_transaction_id          — set by dedup phase
    """

    account_id: int | None
    target_account_id: int | None
    category_id: int | None
    operation_type: str
    type: str                              # "income" | "expense"
    counterparty_id: int | None
    debt_partner_id: int | None
    requires_credit_split: bool
    credit_account_id: int | None
    credit_principal_amount: Decimal | None
    credit_interest_amount: Decimal | None
    split_items: list[dict] | None
    description_override: str | None       # user-edited description (display only)
    applied_rule_id: int | None            # for reject-tracking on commit
    applied_rule_category_id: int | None
    decision_source: str                   # "rule"|"enrichment"|"credit_split_hint"|"user_edit"|"bulk_apply"|"moderator"

    # Set by TransferMatcherService (collection phase — not per-row):
    transfer_match: dict | None = None
    was_orphan_transfer: bool = False

    # Set by dedup phase (collection phase):
    duplicate_of_transaction_id: int | None = None
