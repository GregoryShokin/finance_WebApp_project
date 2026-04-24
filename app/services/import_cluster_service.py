"""Runtime clustering of import rows by fingerprint (Phase 3 of И-08).

A cluster is a set of `ImportRow`s that share the same Phase-1 fingerprint —
meaning they came from the same bank/account, go in the same direction, and
share a normalized description skeleton (and optionally a contract number).

Clusters are not persisted in the database — they are rebuilt on demand from
the rows of a session. If Phase 4 (async LLM moderation with per-cluster
status) requires persistence, we'll add a table; until then, runtime is the
simpler shape.

Per-cluster outputs:
  - `candidate_rule_id` / `candidate_category_id` — best active rule the
    clusterer could find (exact-identifier rule wins over bank-scope rule).
  - `rule_source` — where the candidate came from: `identifier` / `bank` /
    `normalized_description` (legacy) / `none`.
  - `confidence` — scalar in [0, 1] based on rule strength, confirms, and
    cluster size. Bands documented in `_compute_confidence` docstring.

This service is read-only: it never mutates rules or rows. Writes happen
elsewhere (rule_strength_service for counter updates; commit_import for
Transactions).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.counterparty import Counterparty
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.transaction import Transaction
from app.repositories.account_repository import AccountRepository
from app.repositories.category_repository import CategoryRepository
from app.repositories.import_repository import ImportRepository
from app.repositories.transaction_category_rule_repository import (
    TransactionCategoryRuleRepository,
)
from app.services.bank_mechanics_service import BankMechanicsResult, BankMechanicsService
from app.services.brand_extractor_service import extract_brand
from app.services.counterparty_fingerprint_service import CounterpartyFingerprintService
from app.services.counterparty_identifier_service import CounterpartyIdentifierService
from app.services.global_pattern_service import GlobalPatternService
from app.services.import_normalizer_v2 import (
    is_refund_like as v2_is_refund_like,
    is_transfer_like as v2_is_transfer_like,
    pick_refund_brand as v2_pick_refund_brand,
)

# Confidence bands — aligned with the moderator gate thresholds.
# Two tiers for exact-identifier rules: "proven" = confirmed enough to earn
# auto-trust, "active" = trusted but still one-click. Bank/legacy rules
# never reach proven tier because identifier-level evidence is the only
# thing we consider proof of pattern stability.
_CONF_EXACT_RULE_PROVEN = 0.99  # exact + matched + confirms >= 5 + 0 rejections
_CONF_EXACT_RULE_ACTIVE = 0.92  # exact + matched, not yet enough history
_CONF_BANK_RULE_ACTIVE = 0.85   # bank-scope rule
_CONF_LEGACY_RULE_ACTIVE = 0.78  # legacy_pattern rule
_CONF_SINGLE_ROW_DRAG = 0.05    # singleton clusters lose a little — less evidence
_CONF_FLOOR = 0.0

# Identifier-match factor (Phase 7 trust fix).
# When a cluster carries an identifier value (contract/phone/card/iban/person),
# we check whether it matches what the rule was originally trained on.
#   MATCHED  — same identifier_value the rule has seen confirmed → full trust.
#   ABSENT   — neither cluster nor rule carries an identifier → neutral, rule
#              was always a skeleton match.
#   UNMATCHED — cluster has an identifier the rule has NEVER seen → big drag.
#              This prevents the "внутренний перевод по договору ДГ-99999"
#              from inheriting a green-zone status granted to ДГ-12345.
_ID_MATCH_MATCHED = "matched"
_ID_MATCH_ABSENT = "absent"
_ID_MATCH_UNMATCHED = "unmatched"

_ID_MATCH_FACTORS = {
    _ID_MATCH_MATCHED: 1.0,
    _ID_MATCH_ABSENT: 1.0,
    _ID_MATCH_UNMATCHED: 0.60,  # drags 0.92 → 0.55 → out of green AND yellow
}

# Trust zones — user-facing confidence classification.
# These thresholds are the contract between the backend and the wizard UI.
#   green  — "можно не смотреть, AI точно знает"
#   yellow — "подтверди одним кликом — похоже, но не 100%"
#   red    — "требует выбора категории или ответа AI"
ZONE_GREEN = "green"
ZONE_YELLOW = "yellow"
ZONE_RED = "red"

# Two-bucket UX model (Phase 7+):
#   AUTO_TRUST: cluster can be imported without a single click — user just
#   glances at the list and hits «Import». This bucket grows as the user
#   accumulates confirmed identifier-bound rules.
#   ATTENTION:  everything else — user must pick category or answer a question.
# The 0.99 threshold is intentionally strict. Under the current multiplier
# math, ONLY an exact-identifier match with perfect history can cross it:
#   0.92 (base) × 1.0 (error) × 1.0 (multi-row) × 1.0 (matched) = 0.92 — too low.
# So we special-case it: auto-trust requires (exact rule) AND (confirms ≥ 5)
# AND (error_ratio = 0) AND (identifier_match = "matched"). See
# `is_auto_trust_cluster` below.
AUTO_TRUST_THRESHOLD = 0.99
AUTO_TRUST_MIN_CONFIRMS = 5  # rule must have been confirmed at least this many times

CONFIDENCE_GREEN_THRESHOLD = 0.85  # legacy zone indicator (informational)
CONFIDENCE_YELLOW_THRESHOLD = 0.65  # legacy zone indicator


def classify_trust_zone(confidence: float) -> str:
    """Legacy three-zone classification — still used in API for UI chrome,
    but the authoritative bucketing is binary (auto-trust / attention)."""
    if confidence >= CONFIDENCE_GREEN_THRESHOLD:
        return ZONE_GREEN
    if confidence >= CONFIDENCE_YELLOW_THRESHOLD:
        return ZONE_YELLOW
    return ZONE_RED


def is_auto_trust(
    *,
    confidence: float,
    rule_source: str,
    identifier_match: str,
    rule_confirms: int,
    rule_rejections: int,
) -> bool:
    """Gate for the auto-trust bucket ("Готово к импорту").

    A cluster qualifies ONLY when all of the following hold:
      - rule source is exact-identifier match
      - cluster identifier matched the rule identifier
      - rule has ≥ AUTO_TRUST_MIN_CONFIRMS confirmations
      - rule has zero rejections (any rejection introduces doubt)
      - resulting confidence ≥ AUTO_TRUST_THRESHOLD
    Bank-scope and legacy-scope rules never qualify — even if confident, they
    don't prove identifier-level trust. Moving the needle into auto-trust
    requires the user to teach the system by confirming THAT specific
    identifier repeatedly.
    """
    if rule_source != "identifier":
        return False
    if identifier_match != _ID_MATCH_MATCHED:
        return False
    if rule_confirms < AUTO_TRUST_MIN_CONFIRMS:
        return False
    if rule_rejections != 0:
        return False
    return confidence >= AUTO_TRUST_THRESHOLD


@dataclass(frozen=True)
class Cluster:
    """Read-only view of a group of import rows sharing a fingerprint."""

    fingerprint: str
    row_ids: tuple[int, ...]
    count: int
    total_amount: Decimal
    direction: str  # income / expense / unknown
    skeleton: str
    identifier_key: str | None
    identifier_value: str | None
    bank_code: str | None
    example_row_ids: tuple[int, ...]

    # Rule application outcome
    candidate_rule_id: int | None
    candidate_category_id: int | None
    rule_source: str  # identifier / bank / normalized_description / none / account_context
    confidence: float
    identifier_match: str = _ID_MATCH_ABSENT  # matched / absent / unmatched
    # Rule history (for trust signals in UI — "подтверждений / отказов").
    rule_confirms: int = 0
    rule_rejections: int = 0

    # Account-context hint (Layer 1: deterministic, account-type-aware).
    account_context_operation_type: str | None = None
    account_context_category_id: int | None = None
    account_context_label: str | None = None

    # Bank-mechanics hint (Layer 2: bank-specific patterns + cross-session risk).
    bank_mechanics_operation_type: str | None = None
    bank_mechanics_category_id: int | None = None
    bank_mechanics_label: str | None = None
    bank_mechanics_cross_session_warning: str | None = None

    # Global pattern (Layer 3: cross-user collective learning).
    global_pattern_category_id: int | None = None
    global_pattern_category_name: str | None = None
    global_pattern_user_count: int = 0
    global_pattern_total_confirms: int = 0

    # Refund marker — True when every row in the cluster reads as a reversal
    # of a prior purchase ("Отмена операции оплаты KOFEMOLOKO"). Set from
    # `normalized_data.is_refund` during cluster assembly. A refund cluster's
    # category and counterparty are resolved from the history of the brand
    # (`refund_brand`), not from the cluster's own income direction — so at
    # commit time the transaction lands in the same category as the user's
    # purchases at that merchant, acting as an expense compensator.
    is_refund: bool = False
    refund_brand: str | None = None
    refund_resolved_counterparty_id: int | None = None
    refund_resolved_counterparty_name: str | None = None

    @property
    def trust_zone(self) -> str:
        """User-facing zone classification — consumed by the frontend."""
        return classify_trust_zone(self.confidence)

    @property
    def auto_trust(self) -> bool:
        """True when the cluster qualifies for the auto-trust bucket — user
        can import it without a click. See `is_auto_trust()` for the gate."""
        return is_auto_trust(
            confidence=self.confidence,
            rule_source=self.rule_source,
            identifier_match=self.identifier_match,
            rule_confirms=self.rule_confirms,
            rule_rejections=self.rule_rejections,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "row_ids": list(self.row_ids),
            "count": self.count,
            "total_amount": str(self.total_amount),
            "direction": self.direction,
            "skeleton": self.skeleton,
            "identifier_key": self.identifier_key,
            "identifier_value": self.identifier_value,
            "bank_code": self.bank_code,
            "example_row_ids": list(self.example_row_ids),
            "candidate_rule_id": self.candidate_rule_id,
            "candidate_category_id": self.candidate_category_id,
            "rule_source": self.rule_source,
            "confidence": self.confidence,
            "identifier_match": self.identifier_match,
            "rule_confirms": self.rule_confirms,
            "rule_rejections": self.rule_rejections,
            "trust_zone": self.trust_zone,
            "auto_trust": self.auto_trust,
            "account_context_operation_type": self.account_context_operation_type,
            "account_context_category_id": self.account_context_category_id,
            "account_context_label": self.account_context_label,
            "bank_mechanics_operation_type": self.bank_mechanics_operation_type,
            "bank_mechanics_category_id": self.bank_mechanics_category_id,
            "bank_mechanics_label": self.bank_mechanics_label,
            "bank_mechanics_cross_session_warning": self.bank_mechanics_cross_session_warning,
            "global_pattern_category_id": self.global_pattern_category_id,
            "global_pattern_category_name": self.global_pattern_category_name,
            "global_pattern_user_count": self.global_pattern_user_count,
            "global_pattern_total_confirms": self.global_pattern_total_confirms,
            "is_refund": self.is_refund,
            "refund_brand": self.refund_brand,
            "refund_resolved_counterparty_id": self.refund_resolved_counterparty_id,
            "refund_resolved_counterparty_name": self.refund_resolved_counterparty_name,
        }


@dataclass(frozen=True)
class CounterpartyGroup:
    """Phase 3 — counterparty-centric grouping over fingerprint clusters.

    Emitted when two or more fingerprint clusters are bound to the same
    counterparty via `CounterpartyFingerprint`. The UI renders one card per
    counterparty, collapsing all member fingerprints so the user sees
    "Вкусная точка" once instead of three sub-clusters (different
    skeletons: "vkusnaya_tochka", "vkusnoitochka", "Вкусная Точка").

    Single-member groups are also emitted so the UI can replace the
    fingerprint card with a counterparty card (clearer label, history). A
    counterparty binding is always authoritative — it overrides brand
    grouping.
    """

    counterparty_id: int
    counterparty_name: str
    direction: str
    count: int
    total_amount: Decimal
    fingerprint_cluster_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "counterparty_id": self.counterparty_id,
            "counterparty_name": self.counterparty_name,
            "direction": self.direction,
            "count": self.count,
            "total_amount": str(self.total_amount),
            "fingerprint_cluster_ids": list(self.fingerprint_cluster_ids),
        }


@dataclass(frozen=True)
class BrandCluster:
    """Bulk-confirm group: several fingerprint clusters sharing a brand key.

    Brand grouping exists at the UI layer only (see project_bulk_clusters.md):
    rules are still written per fingerprint. A BrandCluster is emitted when
    ≥2 fingerprint clusters share a non-None brand key AND the combined row
    count reaches `MIN_BRAND_CLUSTER_SIZE`. Otherwise the contributing
    fingerprint clusters are returned standalone.

    `direction` is carried here because we never merge expense and income
    clusters under one brand — "Оплата в OZON" and "Возврат OZON" stay
    separate (different operation types, different user intent).
    """

    brand: str
    direction: str
    count: int
    total_amount: Decimal
    fingerprint_cluster_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "brand": self.brand,
            "direction": self.direction,
            "count": self.count,
            "total_amount": str(self.total_amount),
            "fingerprint_cluster_ids": list(self.fingerprint_cluster_ids),
        }


# Bulk-confirm thresholds — the contract between backend and wizard UI.
# Aligned with project_bulk_clusters.md.
MIN_BULK_CLUSTER_SIZE = 5
MIN_BRAND_CLUSTER_SIZE = 5
MIN_FINGERPRINT_COUNT_FOR_BRAND = 2
# Transfers clustered by a concrete identifier (phone / contract / card / iban)
# are a stronger signal than a skeleton brand: the identifier already uniquely
# names the counterparty. Two rows to the same phone is a real pattern worth
# one-click bulk confirm.
MIN_TRANSFER_IDENTIFIER_CLUSTER_SIZE = 2


@dataclass
class _ClusterAccumulator:
    """Mutable bucket used while walking the row list — frozen into a Cluster at the end."""
    fingerprint: str
    direction: str = "unknown"
    skeleton: str = ""
    identifier_key: str | None = None
    identifier_value: str | None = None
    bank_code: str | None = None
    row_ids: list[int] = field(default_factory=list)
    total_amount: Decimal = field(default_factory=lambda: Decimal("0"))
    is_refund: bool = False
    refund_brand: str | None = None


class ImportClusterService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.import_repo = ImportRepository(db)
        self.rule_repo = TransactionCategoryRuleRepository(db)
        self.account_repo = AccountRepository(db)
        self.category_repo = CategoryRepository(db)
        self.bank_mechanics = BankMechanicsService(db)
        self.global_patterns = GlobalPatternService(db)
        self.counterparty_fp_service = CounterpartyFingerprintService(db)
        self.counterparty_id_service = CounterpartyIdentifierService(db)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_clusters(self, session: ImportSession) -> list[Cluster]:
        """Group all rows of `session` by fingerprint and return clusters.

        Rows without a fingerprint (e.g., v2 normalization failed, or row is in
        an error state before normalization ran) are each returned as their own
        singleton cluster keyed by `f"no-fp:{row.id}"`. This keeps them visible
        to the moderator UI instead of silently disappearing.
        """
        rows = self.import_repo.get_rows(session_id=session.id)

        # Fetch account for context hints (Layer 1).
        mapping = session.mapping_json or {}
        # Prefer session.account_id (set by build_preview via update_session).
        # Fall back to mapping_json for backwards compat with old sessions.
        account_id = session.account_id or mapping.get("account_id") or mapping.get("selected_account_id")
        account = (
            self.account_repo.get_by_id_and_user(int(account_id), session.user_id)
            if account_id else None
        )
        # Build name→id map of user's categories (needed for system-category hints).
        categories = self.category_repo.list(user_id=session.user_id)
        category_by_name: dict[str, int] = {c.name: c.id for c in categories}

        buckets: dict[str, _ClusterAccumulator] = {}

        for row in rows:
            normalized = getattr(row, "normalized_data", None) or (row.normalized_data_json or {})
            fp = normalized.get("fingerprint")
            if not fp:
                fp = f"no-fp:{row.id}"

            bucket = buckets.get(fp)
            if bucket is None:
                tokens = normalized.get("tokens") or {}
                bucket = _ClusterAccumulator(
                    fingerprint=fp,
                    direction=str(normalized.get("direction") or "unknown"),
                    skeleton=str(normalized.get("skeleton") or ""),
                    bank_code=normalized.get("bank_code"),
                    identifier_key=_pick_identifier_key(tokens),
                    identifier_value=_pick_identifier_value(tokens),
                    is_refund=bool(normalized.get("is_refund")),
                    refund_brand=(normalized.get("refund_brand") or None),
                )
                buckets[fp] = bucket

            bucket.row_ids.append(row.id)
            try:
                amount = Decimal(str(normalized.get("amount") or "0"))
            except (ValueError, TypeError, ArithmeticError):
                amount = Decimal("0")
            bucket.total_amount += amount
            # Every row sharing a fingerprint went through the same v2 pass;
            # still, guard against stale rows (v1-only) by keeping the bucket
            # flag set as soon as any member row carries it.
            if normalized.get("is_refund"):
                bucket.is_refund = True
                if not bucket.refund_brand and normalized.get("refund_brand"):
                    bucket.refund_brand = str(normalized.get("refund_brand"))
            # Also honor legacy signals — rows where an earlier attach stamped
            # operation_type='refund' but no is_refund flag, OR rows whose
            # original description carries a refund keyword but the flag was
            # never written to normalized_data (pre-refund-feature imports).
            if not bucket.is_refund:
                row_op = str(normalized.get("operation_type") or "").lower()
                if row_op == "refund":
                    bucket.is_refund = True

        # Fallback refund detection at the cluster level — runs once per
        # bucket, after all rows are accumulated. Purpose: catch legacy
        # sessions where rows were normalized before the refund feature
        # existed, so `is_refund` is NULL in persisted normalized_data.
        # For income-direction buckets, we re-check the skeleton with the
        # current refund-keyword list; if it matches, flag the bucket as
        # refund and try to extract the brand on the fly. This is idempotent
        # and cheap (string scan over ~dozen keywords).
        for bucket in buckets.values():
            if bucket.is_refund:
                continue
            if bucket.direction != "income":
                continue
            if not bucket.skeleton:
                continue
            if v2_is_refund_like(bucket.skeleton, None):
                bucket.is_refund = True
                if not bucket.refund_brand:
                    # Use the skeleton directly — placeholders are already
                    # substituted, so we can't call pick_refund_brand (which
                    # expects raw description). extract_brand on a skeleton
                    # with refund keywords in the filler list returns the
                    # merchant token — that's the refund_brand we want.
                    bucket.refund_brand = extract_brand(bucket.skeleton)

        clusters: list[Cluster] = []
        for bucket in buckets.values():
            (
                rule_id,
                cat_id,
                rule_source,
                confidence,
                identifier_match,
                rule_confirms,
                rule_rejections,
            ) = self._apply_rule(user_id=session.user_id, bucket=bucket)

            # Layer 1: account-type context hints.
            ctx_op, ctx_cat, ctx_label = self._apply_account_context_hints(
                bucket=bucket,
                account=account,
                category_by_name=category_by_name,
            )

            # Layer 3: global cross-user pattern (checked before LLM call).
            global_match = None
            global_cat_id: int | None = None
            if bucket.bank_code and bucket.skeleton:
                global_match = self.global_patterns.get_matching_pattern(
                    bank_code=bucket.bank_code,
                    skeleton=bucket.skeleton,
                )
                if global_match:
                    global_cat_id = category_by_name.get(global_match.suggested_category_name)

            # Layer 2: bank-specific mechanics + cross-session risk.
            mech: BankMechanicsResult = self.bank_mechanics.apply(
                skeleton=bucket.skeleton,
                direction=bucket.direction,
                bank_code=bucket.bank_code,
                account=account,
                session=session,
                total_amount=bucket.total_amount,
            )
            mech_cat_id = (
                category_by_name.get(mech.category_name)
                if mech.category_name else None
            )
            # Layer 2 boosts confidence when a bank-specific rule fires.
            # Layer 3 adds a small boost when a global pattern is available —
            # it means many users agreed, so there's collective evidence.
            global_boost = 0.04 * min(global_match.user_count, 5) if global_match else 0.0
            boosted_confidence = min(1.0, confidence + mech.confidence_boost + global_boost) if (mech.label or global_match) else confidence

            # Refund override (И-09). When the cluster reads as a reversal, we
            # look up the counterparty + dominant category from the user's
            # purchase history for the same brand and use that instead of the
            # rule/bank/global chain. Rationale: a refund's income-direction
            # fingerprint will almost never match any existing rule (rules are
            # trained on expense rows), so without this override refund
            # clusters land in red zone with no category — forcing the user to
            # classify every single one manually. We want a refund of a known
            # merchant to flow through automatically into the same category
            # bucket as its purchases, acting as an expense compensator.
            refund_cp_id: int | None = None
            refund_cp_name: str | None = None
            if bucket.is_refund and bucket.refund_brand:
                refund_cp_id, refund_cp_name, refund_cat_id = (
                    self._resolve_refund_counterparty(
                        user_id=session.user_id, brand=bucket.refund_brand,
                    )
                )
                # Category inherited from purchase history overrides whatever
                # the rule chain picked — rules on income side are almost
                # certainly noise here.
                if refund_cat_id is not None:
                    cat_id = refund_cat_id
                    # 0.95 puts the cluster in green/auto-trust territory
                    # without hitting the 0.99 gate (which requires an exact
                    # identifier rule with ≥5 confirmations — criteria a
                    # refund cluster cannot meet by definition).
                    boosted_confidence = max(boosted_confidence, 0.95)

            clusters.append(
                Cluster(
                    fingerprint=bucket.fingerprint,
                    row_ids=tuple(bucket.row_ids),
                    count=len(bucket.row_ids),
                    total_amount=bucket.total_amount,
                    direction=bucket.direction,
                    skeleton=bucket.skeleton,
                    identifier_key=bucket.identifier_key,
                    identifier_value=bucket.identifier_value,
                    bank_code=bucket.bank_code,
                    example_row_ids=tuple(bucket.row_ids[:3]),
                    candidate_rule_id=rule_id,
                    candidate_category_id=cat_id,
                    rule_source=rule_source,
                    confidence=boosted_confidence,
                    identifier_match=identifier_match,
                    rule_confirms=rule_confirms,
                    rule_rejections=rule_rejections,
                    account_context_operation_type=ctx_op,
                    account_context_category_id=ctx_cat,
                    account_context_label=ctx_label,
                    bank_mechanics_operation_type=mech.operation_type,
                    bank_mechanics_category_id=mech_cat_id,
                    bank_mechanics_label=mech.label,
                    bank_mechanics_cross_session_warning=mech.cross_session_warning,
                    global_pattern_category_id=global_cat_id,
                    global_pattern_category_name=global_match.suggested_category_name if global_match else None,
                    global_pattern_user_count=global_match.user_count if global_match else 0,
                    global_pattern_total_confirms=global_match.total_confirms if global_match else 0,
                    is_refund=bucket.is_refund,
                    refund_brand=bucket.refund_brand,
                    refund_resolved_counterparty_id=refund_cp_id,
                    refund_resolved_counterparty_name=refund_cp_name,
                )
            )

        # Sort: most confident first, then by count descending — the moderator
        # UI will consume the list top-down.
        clusters.sort(key=lambda c: (-c.confidence, -c.count, c.fingerprint))
        return clusters

    def build_bulk_clusters(
        self, session: ImportSession,
    ) -> tuple[list[Cluster], list[BrandCluster], list[CounterpartyGroup]]:
        """Return clusters eligible for bulk-confirm, plus brand-level groups.

        Filter pipeline — applied to rows BEFORE size threshold:
          1. Drop committed rows (they already have a Transaction — bulk-apply
             would skip them anyway, and keeping them inflates cluster sizes
             so uncommitted-only counts don't cross MIN_BULK_CLUSTER_SIZE).
          2. Drop secondary-transfer rows (the other side of a confirmed
             transfer pair — auto-created on commit, irrelevant to bulk).
          3. Drop entire clusters where the skeleton reads as transfer-like
             (contains "перевод" / "transfer" etc.). Transfers get their own
             per-recipient treatment via the transfer matcher + transfer-aware
             fingerprint; they should never land in bulk-categorize UI.
          4. Keep only surviving clusters with ≥ MIN_BULK_CLUSTER_SIZE rows.
          5. Aggregate by (brand, direction) for brand-level groups.
        """
        rows = self.import_repo.get_rows(session_id=session.id)
        # Compute per-row exclusion sets in one pass. Using sets because
        # Cluster.row_ids is a tuple and we filter downstream.
        excluded_row_ids: set[int] = set()
        for row in rows:
            normalized = getattr(row, "normalized_data", None) or (row.normalized_data_json or {})
            status = str(getattr(row, "status", "") or "").strip().lower()
            created_tx = getattr(row, "created_transaction_id", None)
            if status == "committed" or created_tx is not None:
                excluded_row_ids.add(row.id)
                continue
            # Any row with a transfer_match is already classified as transfer
            # by the cross-session matcher — both the primary side (this
            # statement's row) and the secondary side (auto-created partner).
            # Neither should show up in bulk-categorize UI: the user already
            # has a proper counterparty-level decision (two-sided transfer),
            # so pulling the primary into a "one category for all" flow would
            # override that and break the pair. See project_bulk_clusters.md.
            if normalized.get("transfer_match"):
                excluded_row_ids.add(row.id)
            # User-requested detach: a row explicitly unchecked in the
            # cluster-card UI should leave the bulk/brand/counterparty
            # aggregations and land standalone in the attention bucket.
            if normalized.get("detached_from_cluster"):
                excluded_row_ids.add(row.id)

        all_clusters = self.build_clusters(session)

        # First pass: drop committed/transfer-matched rows from every cluster
        # and skip transfer-like skeletons without an identifier. The result is
        # every "live" fingerprint cluster regardless of its size — brand-level
        # aggregation needs these, otherwise small per-TT groups (e.g.
        # "Wave coffee", "Wave coffee 1", "Wave coffee 4" with 3/3/2 rows)
        # never roll up into a single «wave» brand even though they obviously
        # should.
        live_clusters: list[Cluster] = []
        for cluster in all_clusters:
            is_transfer_skeleton = v2_is_transfer_like(cluster.skeleton, None)
            # Transfer-like clusters MUST be backed by an identifier. Without a
            # phone/contract/card/iban the skeleton placeholder alone would
            # collapse every unrelated recipient into one giant group, which
            # is exactly what we're trying to prevent. Drop them.
            if is_transfer_skeleton and cluster.identifier_key is None:
                continue
            remaining_ids = tuple(
                rid for rid in cluster.row_ids if rid not in excluded_row_ids
            )
            if not remaining_ids:
                continue
            if len(remaining_ids) == len(cluster.row_ids):
                live_clusters.append(cluster)
            else:
                live_clusters.append(replace(
                    cluster,
                    row_ids=remaining_ids,
                    count=len(remaining_ids),
                    example_row_ids=remaining_ids[:3],
                ))

        # Second pass: apply the size threshold. Identifier-based transfer
        # clusters pass at a much lower threshold: a single phone/contract
        # repeated twice is already a real pattern ("перевод маме"), whereas a
        # fresh skeleton needs at least MIN_BULK_CLUSTER_SIZE rows of evidence
        # before bulk-categorize becomes worth the UI slot.
        eligible: list[Cluster] = []
        for cluster in live_clusters:
            is_transfer_skeleton = v2_is_transfer_like(cluster.skeleton, None)
            min_size = (
                MIN_TRANSFER_IDENTIFIER_CLUSTER_SIZE
                if is_transfer_skeleton and cluster.identifier_key is not None
                else MIN_BULK_CLUSTER_SIZE
            )
            if cluster.count < min_size:
                continue
            eligible.append(cluster)

        # Brand aggregation is computed over live_clusters (NOT eligible) so a
        # brand whose rows are spread across many small per-TT fingerprints
        # still surfaces as a single brand card. Members contributing to a
        # brand that are below MIN_BULK_CLUSTER_SIZE individually are tracked
        # so the UI can materialize them on demand (see `aux_clusters`).
        brand_clusters = self._group_by_brand(live_clusters)

        # fingerprint_clusters returned to the caller = union of:
        #   * `eligible`  — clusters big enough to stand on their own.
        #   * brand members that don't qualify individually (small per-TT
        #     groups) — so the frontend can look them up by fingerprint when
        #     expanding a brand card. Without this, the brand card would list
        #     row_ids the frontend can't resolve to a cluster.
        # Phase 3 — third aggregation layer: counterparty groups. A fingerprint
        # bound to a counterparty is always rendered under that counterparty
        # in the UI, regardless of brand. Counterparty wins over brand.
        counterparty_groups = self._group_by_counterparty(
            live_clusters, user_id=session.user_id,
        )
        counterparty_bound_fps: set[str] = {
            fp for g in counterparty_groups for fp in g.fingerprint_cluster_ids
        }

        eligible_fps = {c.fingerprint for c in eligible}
        aux_fps: set[str] = set()
        # Aux from brand clusters — but skip fingerprints already owned by a
        # counterparty (the counterparty view will render them, so the brand
        # view shouldn't double-count them).
        for b in brand_clusters:
            for fp in b.fingerprint_cluster_ids:
                if fp in counterparty_bound_fps:
                    continue
                if fp not in eligible_fps:
                    aux_fps.add(fp)
        # Aux from counterparty groups — same reason the brand layer needs
        # them: UI must be able to resolve each member fingerprint's rows.
        for g in counterparty_groups:
            for fp in g.fingerprint_cluster_ids:
                if fp not in eligible_fps:
                    aux_fps.add(fp)
        aux_clusters = [c for c in live_clusters if c.fingerprint in aux_fps]

        # Drop brand clusters that are fully subsumed by counterparty groups —
        # otherwise the user sees the same rows under both "Pyaterochka" brand
        # and "Пятёрочка" counterparty cards. Partial overlap (some members
        # belong to counterparty, others don't) keeps the brand card with its
        # still-unbound members.
        filtered_brand_clusters: list[BrandCluster] = []
        for b in brand_clusters:
            remaining_fps = tuple(
                fp for fp in b.fingerprint_cluster_ids
                if fp not in counterparty_bound_fps
            )
            if not remaining_fps:
                continue
            if len(remaining_fps) == len(b.fingerprint_cluster_ids):
                filtered_brand_clusters.append(b)
                continue
            # Recompute count/total_amount for the reduced membership.
            fp_lookup = {c.fingerprint: c for c in live_clusters}
            members = [fp_lookup[fp] for fp in remaining_fps if fp in fp_lookup]
            if len(members) < MIN_FINGERPRINT_COUNT_FOR_BRAND:
                continue
            total_count = sum(m.count for m in members)
            if total_count < MIN_BRAND_CLUSTER_SIZE:
                continue
            total_amount = sum((m.total_amount for m in members), Decimal("0"))
            filtered_brand_clusters.append(BrandCluster(
                brand=b.brand,
                direction=b.direction,
                count=total_count,
                total_amount=total_amount,
                fingerprint_cluster_ids=remaining_fps,
            ))

        return eligible + aux_clusters, filtered_brand_clusters, counterparty_groups

    @staticmethod
    def _group_by_brand(clusters: list[Cluster]) -> list[BrandCluster]:
        """Aggregate fingerprint clusters into brand-level groups.

        Pure function — kept as a staticmethod so it can be unit-tested
        without mocking every repository the parent service depends on.
        """
        brand_groups: dict[tuple[str, str], list[Cluster]] = {}
        for cluster in clusters:
            # Transfer-like clusters never enter brand grouping. They already
            # stand on their identifier (phone/contract/…), and rolling
            # "переводов на +79…" plus "переводов на +79…" under one brand
            # would destroy exactly the per-recipient distinction we worked
            # to keep in the fingerprint. `extract_brand` also rejects
            # transfer skeletons, but this is a defense-in-depth guard.
            if v2_is_transfer_like(cluster.skeleton, None):
                continue
            brand = extract_brand(cluster.skeleton)
            if brand is None:
                continue
            key = (brand, cluster.direction)
            brand_groups.setdefault(key, []).append(cluster)

        brand_clusters: list[BrandCluster] = []
        for (brand, direction), members in brand_groups.items():
            if len(members) < MIN_FINGERPRINT_COUNT_FOR_BRAND:
                continue
            total_rows = sum(m.count for m in members)
            if total_rows < MIN_BRAND_CLUSTER_SIZE:
                continue
            total_amount = sum((m.total_amount for m in members), Decimal("0"))
            brand_clusters.append(BrandCluster(
                brand=brand,
                direction=direction,
                count=total_rows,
                total_amount=total_amount,
                fingerprint_cluster_ids=tuple(m.fingerprint for m in members),
            ))

        brand_clusters.sort(key=lambda b: (-b.count, b.brand))
        return brand_clusters

    def _group_by_counterparty(
        self, clusters: list[Cluster], *, user_id: int,
    ) -> list[CounterpartyGroup]:
        """Aggregate fingerprint clusters by their bound counterparty.

        Each fingerprint is resolved through `CounterpartyFingerprintService`;
        only those bound to a counterparty participate. The resulting groups
        collapse all fingerprints sharing one counterparty under a single
        card in the UI.

        Single-member groups are still emitted — the counterparty label ("Вкусная
        точка") beats the raw skeleton in the UI even when only one
        fingerprint is bound so far.
        """
        if not clusters:
            return []
        # Identifier binding takes precedence — it's cross-account and
        # cross-bank, so a phone/contract/IBAN bound on one statement resolves
        # on the next. Fingerprint binding is the fallback for skeleton/brand
        # clusters without an identifier (or with an unsupported one).
        id_pairs: list[tuple[str, str]] = [
            (c.identifier_key, c.identifier_value)
            for c in clusters
            if c.identifier_key and c.identifier_value
        ]
        id_map = self.counterparty_id_service.resolve_many(
            user_id=user_id, pairs=id_pairs,
        )
        fp_map = self.counterparty_fp_service.resolve_many(
            user_id=user_id,
            fingerprints=[c.fingerprint for c in clusters],
        )
        # Per-cluster resolved counterparty_id: identifier wins when present.
        cluster_cp: dict[str, int] = {}
        for c in clusters:
            if c.identifier_key and c.identifier_value:
                cp = id_map.get((c.identifier_key, c.identifier_value))
                if cp is not None:
                    cluster_cp[c.fingerprint] = cp
                    continue
            cp = fp_map.get(c.fingerprint)
            if cp is not None:
                cluster_cp[c.fingerprint] = cp
        if not cluster_cp:
            return []
        # Name lookup for each counterparty_id referenced.
        cp_ids = set(cluster_cp.values())
        cp_rows = (
            self.db.query(Counterparty)
            .filter(Counterparty.id.in_(cp_ids), Counterparty.user_id == user_id)
            .all()
        )
        cp_by_id = {cp.id: cp for cp in cp_rows}

        # Bucket clusters by (counterparty_id, direction). We keep income and
        # expense separate as a rule — a counterparty might be both a payroll
        # source (income) and a service you pay (expense), and conflating
        # those is misleading.
        #
        # EXCEPTION — refunds. A refund is income by direction but semantically
        # an expense compensator: "Отмена операции оплаты KOFEMOLOKO" belongs
        # under the same "Кофе Молоко" card as the purchases it reverses, not
        # as a separate income card next door. We detect refund-only income
        # groups (all member clusters have is_refund=True) and fold them into
        # the counterparty's expense group. The card's display direction stays
        # "expense" (so the UI shows expense-kind categories); per-row
        # operation_type stays "refund" so analytics still net them out.
        buckets: dict[tuple[int, str], list[Cluster]] = {}
        for cluster in clusters:
            cp_id = cluster_cp.get(cluster.fingerprint)
            if cp_id is None:
                continue
            if cp_id not in cp_by_id:
                continue  # counterparty deleted; ignore binding
            key = (cp_id, cluster.direction)
            buckets.setdefault(key, []).append(cluster)

        # Fold refund-only income groups into the matching expense group.
        for key in list(buckets.keys()):
            cp_id, direction = key
            if direction != "income":
                continue
            members = buckets[key]
            if not members or not all(getattr(m, "is_refund", False) for m in members):
                continue
            expense_key = (cp_id, "expense")
            if expense_key not in buckets:
                # No matching expense group — keep the refund income card
                # standalone rather than hiding it entirely.
                continue
            buckets[expense_key].extend(members)
            del buckets[key]

        groups: list[CounterpartyGroup] = []
        for (cp_id, direction), members in buckets.items():
            total_count = sum(m.count for m in members)
            # Net spend for mixed cards: subtract refund member amounts so the
            # subtitle ("64 операций · 34 275 ₽") reflects what the user
            # effectively paid, not the gross sum of purchases + refund.
            refund_amount = sum(
                (m.total_amount for m in members if getattr(m, "is_refund", False)),
                Decimal("0"),
            )
            gross_amount = sum(
                (m.total_amount for m in members if not getattr(m, "is_refund", False)),
                Decimal("0"),
            )
            total_amount = gross_amount - refund_amount
            groups.append(CounterpartyGroup(
                counterparty_id=cp_id,
                counterparty_name=cp_by_id[cp_id].name,
                direction=direction,
                count=total_count,
                total_amount=total_amount,
                fingerprint_cluster_ids=tuple(m.fingerprint for m in members),
            ))
        groups.sort(key=lambda g: (-g.count, g.counterparty_name))
        return groups

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_account_context_hints(
        *,
        bucket: "_ClusterAccumulator",
        account: Any,
        category_by_name: dict[str, int],
    ) -> tuple[str | None, int | None, str | None]:
        """Layer 1: deterministic account-type-aware classification hints.

        Returns (operation_type, category_id, human_readable_label) or
        (None, None, None) when no hint applies.

        These hints are additive — they never override the user's confirmed
        rules (rule layer wins). They give the moderator UI and LLM pre-filled
        suggestions when the rule layer returns nothing useful.

        Keyword matching is done against the *skeleton* (already lowercased,
        punctuation stripped, identifiers replaced with placeholders).
        """
        if account is None:
            return None, None, None

        account_type: str = str(getattr(account, "account_type", "") or "")
        is_credit: bool = bool(getattr(account, "is_credit", False))
        direction = bucket.direction
        sk = bucket.skeleton.lower()

        # ── Credit card / installment card ─────────────────────────────────
        if account_type == "credit_card":
            if direction == "income":
                if any(w in sk for w in ("погашение", "пополнение", "внесение")):
                    return "transfer", None, "Пополнение кредитной карты"
                if any(w in sk for w in ("отмена", "возврат", "refund", "chargeback")):
                    return "refund", None, "Возврат на кредитную карту"
            # expense — regular purchase, no hint needed (default)
            return None, None, None

        # ── Credit account (e.g., loan / Яндекс Сплит) ────────────────────
        if is_credit or account_type in ("credit", "installment_card", "credit_card"):
            interest_cat = category_by_name.get("Проценты по кредитам")
            if direction == "expense":
                if any(w in sk for w in ("погашение процентов", "проценты пользование", "проценты договору")):
                    return "regular", interest_cat, "Проценты по кредиту"
                if any(w in sk for w in ("погашение основного долга", "погашение просроченной", "погашение тела", "основного долга")):
                    return "transfer", None, "Погашение тела кредита"
            if direction == "income":
                if any(w in sk for w in ("отмена по операции", "возврат по операции", "отмена операции")):
                    return "refund", None, "Возврат по кредитной операции"
            return None, None, None

        # ── Deposit account ────────────────────────────────────────────────
        if account_type == "deposit":
            interest_income_cat = category_by_name.get("Проценты от вклада")
            if direction == "income":
                if any(w in sk for w in ("начисление процентов", "проценты по вкладу", "проценты по договору", "капитализация")):
                    return "regular", interest_income_cat, "Проценты по вкладу"
                if any(w in sk for w in ("пополнение", "взнос")):
                    return "transfer", None, "Пополнение вклада"
            if direction == "expense":
                if any(w in sk for w in ("частичное снятие", "снятие", "закрытие вклада")):
                    return "transfer", None, "Снятие с вклада"
            return None, None, None

        return None, None, None

    def _apply_rule(
        self, *, user_id: int, bucket: _ClusterAccumulator
    ) -> tuple[int | None, int | None, str, float, str, int, int]:
        """Find the best active rule matching this cluster.

        Priority:
          1. Exact identifier (identifier_key + identifier_value) → `identifier`
          2. Bank-scope rule (bank_code + normalized_description/skeleton) → `bank`
          3. Legacy normalized_description rule → `normalized_description`

        Identifier-aware trust (Phase 7 fix for the «ложная уверенность»
        problem): we pass `identifier_match` into confidence — so a rule
        that happened to share a skeleton with a cluster carrying a NEW
        identifier cannot inherit the full trust score granted to the old
        identifier. See `_ID_MATCH_*` constants for the semantics.
        """
        cluster_has_id = bool(bucket.identifier_key and bucket.identifier_value)

        # 1. Exact identifier — full trust only when identifier truly matches.
        if cluster_has_id:
            rule = self.rule_repo.get_active_rule_by_identifier(
                user_id=user_id,
                identifier_key=bucket.identifier_key,  # type: ignore[arg-type]
                identifier_value=bucket.identifier_value,  # type: ignore[arg-type]
            )
            if rule is not None:
                # Escalate base to "proven" when the user has confirmed this
                # exact identifier-category pairing at least AUTO_TRUST_MIN_CONFIRMS
                # times without a single rejection. That's the only path into
                # the auto-trust bucket.
                proven = (
                    rule.confirms >= AUTO_TRUST_MIN_CONFIRMS
                    and rule.rejections == 0
                )
                base = _CONF_EXACT_RULE_PROVEN if proven else _CONF_EXACT_RULE_ACTIVE
                confidence = self._compute_confidence(
                    base=base,
                    confirms=rule.confirms,
                    rejections=rule.rejections,
                    cluster_size=len(bucket.row_ids),
                    identifier_match=_ID_MATCH_MATCHED,
                    # Rule history overrides cluster-size weakness: 10 past
                    # confirmations of this contract are stronger evidence
                    # than the size of the current singleton cluster.
                    skip_singleton_drag=proven,
                )
                return (rule.id, rule.category_id, "identifier", confidence,
                        _ID_MATCH_MATCHED, rule.confirms, rule.rejections)

        # 2. Bank-scope rule — generalized across identifiers.
        if bucket.bank_code and bucket.skeleton:
            rule = self.rule_repo.get_active_rule_by_bank(
                user_id=user_id,
                bank_code=bucket.bank_code,
                normalized_description=bucket.skeleton,
            )
            if rule is not None:
                id_match = self._classify_identifier_match(bucket, rule)
                confidence = self._compute_confidence(
                    base=_CONF_BANK_RULE_ACTIVE,
                    confirms=rule.confirms,
                    rejections=rule.rejections,
                    cluster_size=len(bucket.row_ids),
                    identifier_match=id_match,
                )
                return (rule.id, rule.category_id, "bank", confidence,
                        id_match, rule.confirms, rule.rejections)

        # 3. Legacy rule — skeleton-only match. We use a strict lookup that
        # excludes rules carrying an identifier_value; those belong to path 1
        # and must not leak into path 3 through skeleton coincidence.
        if bucket.skeleton:
            rule = self.rule_repo.get_active_legacy_rule(
                user_id=user_id, normalized_description=bucket.skeleton
            )
            if rule is not None:
                # For a legacy rule (no identifier bound), identifier match
                # is UNMATCHED if the cluster has an identifier that was
                # never confirmed, ABSENT otherwise.
                id_match = _ID_MATCH_UNMATCHED if cluster_has_id else _ID_MATCH_ABSENT
                confidence = self._compute_confidence(
                    base=_CONF_LEGACY_RULE_ACTIVE,
                    confirms=rule.confirms,
                    rejections=rule.rejections,
                    cluster_size=len(bucket.row_ids),
                    identifier_match=id_match,
                )
                return (rule.id, rule.category_id, "normalized_description", confidence,
                        id_match, rule.confirms, rule.rejections)

        return None, None, "none", _CONF_FLOOR, _ID_MATCH_ABSENT, 0, 0

    def _resolve_refund_counterparty(
        self, *, user_id: int, brand: str,
    ) -> tuple[int | None, str | None, int | None]:
        """For a refund cluster, find the best (counterparty, category) pair.

        Search strategy: among the user's **expense** transactions over the last
        365 days, find those whose counterparty name or description contains
        `brand` (case-insensitive). Pick the counterparty with the most such
        transactions; within that counterparty, pick the category used in the
        most transactions. Both picks are majority vote — no weighting.

        Returns `(counterparty_id, counterparty_name, category_id)`. Any field
        may be None when no confident match exists (no hits → all None;
        counterparty found but none of its purchases were categorized →
        (id, name, None), in which case the cluster stays in attention
        bucket to let the user pick a category manually).
        """
        from collections import Counter as _Counter

        if not brand:
            return None, None, None

        brand_lc = brand.strip().lower()
        if not brand_lc:
            return None, None, None

        lookback_start = datetime.now(timezone.utc) - timedelta(days=365)
        like_pattern = f"%{brand_lc}%"

        rows = (
            self.db.query(
                Transaction.counterparty_id,
                Transaction.category_id,
                Counterparty.name,
            )
            .outerjoin(Counterparty, Counterparty.id == Transaction.counterparty_id)
            .filter(
                Transaction.user_id == user_id,
                Transaction.type == "expense",
                Transaction.transaction_date >= lookback_start,
                or_(
                    func.lower(Counterparty.name).like(like_pattern),
                    func.lower(Transaction.description).like(like_pattern),
                    func.lower(Transaction.normalized_description).like(like_pattern),
                ),
            )
            .all()
        )

        if not rows:
            return None, None, None

        # Pick counterparty by frequency. Counterparty_id can be NULL on older
        # rows — those are dropped here because we need a concrete binding to
        # inherit; description-match alone is not enough to create one.
        cp_counter: _Counter = _Counter(
            r.counterparty_id for r in rows if r.counterparty_id is not None
        )
        if not cp_counter:
            return None, None, None

        top_cp_id, _ = cp_counter.most_common(1)[0]
        cp_name = next(
            (r.name for r in rows if r.counterparty_id == top_cp_id and r.name),
            None,
        )

        # Dominant category for the chosen counterparty.
        cat_counter: _Counter = _Counter(
            r.category_id for r in rows
            if r.counterparty_id == top_cp_id and r.category_id is not None
        )
        top_cat_id = cat_counter.most_common(1)[0][0] if cat_counter else None

        return top_cp_id, cp_name, top_cat_id

    @staticmethod
    def _classify_identifier_match(bucket: "_ClusterAccumulator", rule: Any) -> str:
        """Compare the cluster's identifier against the rule's bound identifier."""
        cluster_val = bucket.identifier_value
        rule_val = getattr(rule, "identifier_value", None)

        # Neither side has an identifier — normal skeleton/bank match.
        if not cluster_val and not rule_val:
            return _ID_MATCH_ABSENT

        # Rule has no bound identifier, cluster does. That's exactly the «new
        # contract inherits an old category» scenario we want to catch.
        if cluster_val and not rule_val:
            return _ID_MATCH_UNMATCHED

        # Rule has an identifier, cluster doesn't — shouldn't happen through
        # `get_active_rule_by_bank` (bank rules are generalized), but stay safe.
        if rule_val and not cluster_val:
            return _ID_MATCH_UNMATCHED

        # Both have identifiers — compare.
        return _ID_MATCH_MATCHED if cluster_val == rule_val else _ID_MATCH_UNMATCHED

    @staticmethod
    def _compute_confidence(
        *,
        base: float,
        confirms: int,
        rejections: int,
        cluster_size: int,
        identifier_match: str = _ID_MATCH_ABSENT,
        skip_singleton_drag: bool = False,
    ) -> float:
        """Confidence = base × error_ratio × evidence × identifier_match.

        - error_ratio_factor: (1 - rejections / (confirms + rejections)); perfect
          history doesn't scale the base, poor history drags it toward 0.
        - evidence_factor: singleton clusters lose `_CONF_SINGLE_ROW_DRAG`
          because 1 row is weaker evidence than 5 rows. When
          `skip_singleton_drag=True` (proven exact rule) we skip this — the
          rule's past confirmations are stronger than cluster size.
        - identifier_factor: see `_ID_MATCH_*`. The headline fix here —
          a cluster carrying an identifier the rule has never seen confirmed
          gets a hard drag, so it can never sit in the green zone on skeleton
          similarity alone.
        - Result is clamped to [0, 1].
        """
        # Rule counters are Numeric/Decimal after migration 0053 — coerce to
        # float up-front so the mixed-type multiplication below stays pure
        # float arithmetic. Mixing Decimal with float raises TypeError.
        _c = float(confirms or 0)
        _r = float(rejections or 0)
        total = _c + _r
        error_ratio_factor = 1.0 if total == 0 else (_c / total)
        if skip_singleton_drag:
            evidence_factor = 1.0
        else:
            evidence_factor = 1.0 - (_CONF_SINGLE_ROW_DRAG if cluster_size <= 1 else 0.0)
        identifier_factor = _ID_MATCH_FACTORS.get(identifier_match, 1.0)
        score = base * error_ratio_factor * evidence_factor * identifier_factor
        return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Priority order for cluster-level identifier: pick the strongest distinguishing
# token present on the row. Phone / contract / IBAN / card / person_hash.
_IDENTIFIER_PRIORITY = ("contract", "phone", "iban", "card", "person_hash")


def _pick_identifier_key(tokens: dict[str, Any]) -> str | None:
    for key in _IDENTIFIER_PRIORITY:
        if tokens.get(key):
            return key
    return None


def _pick_identifier_value(tokens: dict[str, Any]) -> str | None:
    for key in _IDENTIFIER_PRIORITY:
        value = tokens.get(key)
        if value:
            return str(value)
    return None
