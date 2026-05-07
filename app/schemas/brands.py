"""Brand-management request/response schemas (Brand registry Ph8b).

Covers user-private brand creation, pattern attachment, brand search/picker,
and the «suggest brand from row» helper that prefills the create form.

Read/write boundaries are encoded here: the API never exposes
`is_global=True` write paths — global seed is maintainer-only via
`scripts/seed_brand_registry.py`. Every endpoint that accepts a brand_id
goes through `BrandManagementService` which checks ownership for writes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# Kinds the user-facing API accepts. Mirrors BRAND_PATTERN_KINDS minus any
# kind we don't want users to author directly. As of Ph8b: all four are
# allowed (text is the common case; sbp_merchant_id/org_full/alias_exact
# are valid when the row's tokens carry them).
USER_PATTERN_KIND = Literal[
    "text",
    "sbp_merchant_id",
    "org_full",
    "alias_exact",
]


class BrandCreateRequest(BaseModel):
    canonical_name: str = Field(..., min_length=1, max_length=128)
    category_hint: str | None = Field(default=None, max_length=64)


class BrandPatternCreateRequest(BaseModel):
    kind: USER_PATTERN_KIND
    pattern: str = Field(..., min_length=1, max_length=256)
    is_regex: bool = False


class BrandPatternResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    pattern: str
    is_regex: bool
    is_global: bool
    is_active: bool


class BrandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    canonical_name: str
    category_hint: str | None = None
    is_global: bool
    created_by_user_id: int | None = None


class BrandWithPatternsResponse(BrandResponse):
    patterns: list[BrandPatternResponse]


class BrandSuggestionResponse(BaseModel):
    """Prefill payload for «+ Создать бренд» on a specific row.

    Two-tier suggestion:
      1. If `tokens.sbp_merchant_id` is present, return a `sbp_merchant_id`
         pattern — that's the most precise possible signal for SBP rails.
      2. Otherwise run `brand_extractor_service.extract_brand` on the
         skeleton and return a `text` pattern with the extracted token.

    `canonical_name` is a best-effort guess (Title-cased extractor output
    or empty when nothing usable was found). The user always has the
    chance to override before submitting.
    """

    canonical_name: str | None = None
    pattern_kind: USER_PATTERN_KIND | None = None
    pattern_value: str | None = None


class SuggestedBrandGroup(BaseModel):
    """One «we see N rows that look like X — create brand?» card.

    Aggregated across active sessions of one user (no cross-user pollution).
    Threshold for inclusion is enforced by the service.
    """

    candidate: str
    row_count: int
    sample_descriptions: list[str] = Field(default_factory=list)
    sample_row_ids: list[int] = Field(default_factory=list)


class SuggestedBrandsResponse(BaseModel):
    suggestions: list[SuggestedBrandGroup]
