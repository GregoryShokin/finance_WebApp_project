"""Pydantic schema for v2 fields inside ImportRow.normalized_data_json.

Phase 1.2 of И-08. The model is additive: it only describes the keys
introduced by normalizer v2. The surrounding normalized_data_json dict
can carry arbitrary v1 keys alongside — `merge_into` preserves them.

Privacy note: `person_name` is *not* stored. The boolean
`person_name_present` records whether the regex found a name, without
persisting the name itself. The raw description remains available in
other fields (ImportRow.raw_description / description) for downstream
matchers that need it, but this JSON column is read by the UI and can
leak into exports/logs — so no name here.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.services.brand_resolver_service import BrandMatch
from app.services.import_normalizer_v2 import ExtractedTokens


NORMALIZER_VERSION = 2


class TokensV2(BaseModel):
    """Structured identifiers extracted from the row description."""

    model_config = ConfigDict(extra="ignore")

    phone: str | None = None
    contract: str | None = None
    iban: str | None = None
    card: str | None = None
    person_name_present: bool = False
    counterparty_org: str | None = None
    sbp_merchant_id: str | None = None
    card_last4: str | None = None
    amounts_extra: list[str] = Field(default_factory=list)
    dates_extra: list[str] = Field(default_factory=list)


class NormalizedDataV2(BaseModel):
    """v2 slice of ImportRow.normalized_data_json."""

    model_config = ConfigDict(extra="ignore")

    skeleton: str
    fingerprint: str
    tokens: TokensV2 = Field(default_factory=TokensV2)
    normalizer_version: int = NORMALIZER_VERSION
    # Refund flag — True when the row reads as a reversal of a prior purchase
    # ("возврат", "отмена операции ...", "refund"). Brand is the merchant
    # inferred from the skeleton (KOFEMOLOKO → "kofemoloko"); used by the
    # clusterer to look up the purchase-side counterparty + its category.
    is_refund: bool = False
    refund_brand: str | None = None

    # Brand registry resolution (Ph3-Ph4). All None when the resolver didn't
    # produce a match above the prompt threshold OR wasn't run (legacy rows
    # imported before Ph4). The frontend reads these to render the inline
    # «Это <brand_canonical_name>?» prompt; gating logic (which op_types
    # show the prompt) lives in the UI, not here.
    brand_id: int | None = None
    brand_slug: str | None = None
    brand_canonical_name: str | None = None
    brand_category_hint: str | None = None
    brand_pattern_id: int | None = None
    brand_kind: str | None = None
    brand_confidence: float | None = None

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_tokens(
        cls,
        *,
        tokens: ExtractedTokens,
        skeleton: str,
        fingerprint: str,
        is_refund: bool = False,
        refund_brand: str | None = None,
        brand_match: BrandMatch | None = None,
    ) -> "NormalizedDataV2":
        """Build the v2 payload from a normalizer run."""
        return cls(
            skeleton=skeleton,
            fingerprint=fingerprint,
            tokens=TokensV2(
                phone=tokens.phone,
                contract=tokens.contract,
                iban=tokens.iban,
                card=tokens.card,
                person_name_present=tokens.person_name is not None,
                counterparty_org=tokens.counterparty_org,
                sbp_merchant_id=tokens.sbp_merchant_id,
                card_last4=tokens.card_last4,
                amounts_extra=[_decimal_str(a) for a in tokens.amounts],
                dates_extra=[d.isoformat() for d in tokens.dates],
            ),
            is_refund=is_refund,
            refund_brand=refund_brand,
            brand_id=brand_match.brand_id if brand_match else None,
            brand_slug=brand_match.brand_slug if brand_match else None,
            brand_canonical_name=brand_match.canonical_name if brand_match else None,
            brand_category_hint=brand_match.category_hint if brand_match else None,
            brand_pattern_id=brand_match.pattern_id if brand_match else None,
            brand_kind=brand_match.kind if brand_match else None,
            brand_confidence=brand_match.confidence if brand_match else None,
        )

    @classmethod
    def from_normalized_data(cls, data: dict[str, Any] | None) -> "NormalizedDataV2 | None":
        """Parse the v2 slice from a raw normalized_data_json dict.

        Returns None if the dict is empty or lacks `normalizer_version == 2`.
        """
        if not data:
            return None
        if data.get("normalizer_version") != NORMALIZER_VERSION:
            return None
        return cls.model_validate(data)

    @classmethod
    def from_import_row(cls, row: Any) -> "NormalizedDataV2 | None":
        """Parse v2 from an ImportRow-like object (duck-typed)."""
        return cls.from_normalized_data(getattr(row, "normalized_data_json", None))

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------

    def merge_into(self, existing: dict[str, Any] | None) -> dict[str, Any]:
        """Return `existing` with v2 keys added/overwritten; other keys untouched."""
        out: dict[str, Any] = dict(existing or {})
        out["skeleton"] = self.skeleton
        out["fingerprint"] = self.fingerprint
        out["tokens"] = self.tokens.model_dump()
        out["normalizer_version"] = self.normalizer_version
        out["is_refund"] = self.is_refund
        out["refund_brand"] = self.refund_brand
        out["brand_id"] = self.brand_id
        out["brand_slug"] = self.brand_slug
        out["brand_canonical_name"] = self.brand_canonical_name
        out["brand_category_hint"] = self.brand_category_hint
        out["brand_pattern_id"] = self.brand_pattern_id
        out["brand_kind"] = self.brand_kind
        out["brand_confidence"] = self.brand_confidence
        return out


def _decimal_str(value: Decimal) -> str:
    """Stable string form for JSON; trailing zeros preserved."""
    return format(value, "f")
