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
    amounts_extra: list[str] = Field(default_factory=list)
    dates_extra: list[str] = Field(default_factory=list)


class NormalizedDataV2(BaseModel):
    """v2 slice of ImportRow.normalized_data_json."""

    model_config = ConfigDict(extra="ignore")

    skeleton: str
    fingerprint: str
    tokens: TokensV2 = Field(default_factory=TokensV2)
    normalizer_version: int = NORMALIZER_VERSION

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
                amounts_extra=[_decimal_str(a) for a in tokens.amounts],
                dates_extra=[d.isoformat() for d in tokens.dates],
            ),
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
        return out


def _decimal_str(value: Decimal) -> str:
    """Stable string form for JSON; trailing zeros preserved."""
    return format(value, "f")
