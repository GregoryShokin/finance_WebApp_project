"""User-facing brand management (Brand registry Ph8b).

Companion to the read-only `BrandResolverService` and the user-action
`BrandConfirmService`. This module owns:

  • create_private_brand   — `POST /brands`
  • add_pattern_to_brand   — `POST /brands/{id}/patterns`
  • list_brands_for_picker — `GET /brands?scope=…&q=…`
  • get_with_patterns      — `GET /brands/{id}` (UI: «показать паттерны»)
  • suggest_from_row       — `GET /brands/suggest-from-row?row_id=…`
  • list_unresolved_groups — `GET /imports/sessions/{id}/brand-suggestions`

Authorization rules (Brand registry §8b decisions):
  • Only maintainer (via seed script) writes global brands. The API
    cannot create or mutate `is_global=True` rows.
  • Writing a *private* pattern to a *global* brand is allowed — that's
    the user-override mechanic from Ph3 and is required for the «не тот
    бренд → выбрать другой» path. The pattern lands as
    (is_global=False, scope_user_id=user_id).
  • Writing any pattern to someone else's *private* brand is rejected.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.brand import Brand, BrandPattern
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.repositories.brand_repository import BrandRepository
from app.services.brand_confirm_service import BrandConfirmError, BrandConfirmService
from app.services.brand_extractor_service import extract_brand
from app.services.brand_resolver_service import BrandResolverService
from app.services.import_normalizer_v2 import ExtractedTokens

logger = logging.getLogger(__name__)


# BGN/PCGN-style cyrillic→latin transliteration. Used to produce stable
# ascii slugs from arbitrary Russian brand names. Not a perfect linguistic
# match — only needs to be deterministic and produce something that
# survives PostgreSQL's UNIQUE constraint with a per-user suffix.
_CYR_TO_LAT: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

_SLUG_MAX_LEN = 48  # leaves headroom for "_u<id>_<n>" suffix; total ≤ 64

# Minimum cluster size before a candidate becomes a «Создать бренд?»
# suggestion. Below this, attention-feed stays quiet — single-shot rows
# don't justify a brand entity yet (user can still create manually via
# «+ Создать бренд» on the row itself).
_SUGGESTION_MIN_ROWS = 3


class BrandManagementError(Exception):
    """Raised on validation / authorization failure. Mapped to HTTP 400 / 403."""


@dataclass(frozen=True)
class _Suggestion:
    candidate: str
    row_count: int
    sample_descriptions: list[str]
    sample_row_ids: list[int]


class BrandManagementService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = BrandRepository(db)

    # ──────────────────────────────────────────────────────────────────
    # Create
    # ──────────────────────────────────────────────────────────────────

    def create_private_brand(
        self,
        *,
        user_id: int,
        canonical_name: str,
        category_hint: str | None,
    ) -> Brand:
        canonical_name = canonical_name.strip()
        if not canonical_name:
            raise BrandManagementError("canonical_name is required")
        slug = self._generate_unique_slug(canonical_name, user_id)
        return self.repo.create_brand(
            slug=slug,
            canonical_name=canonical_name,
            category_hint=(category_hint or "").strip() or None,
            is_global=False,
            created_by_user_id=user_id,
        )

    # ──────────────────────────────────────────────────────────────────
    # Add pattern
    # ──────────────────────────────────────────────────────────────────

    def add_pattern_to_brand(
        self,
        *,
        user_id: int,
        brand_id: int,
        kind: str,
        pattern: str,
        is_regex: bool = False,
    ) -> tuple[BrandPattern, bool]:
        brand = self.repo.get_brand(brand_id)
        if brand is None:
            raise BrandManagementError("brand not found")
        # Authorization: own private brand → ok. Global brand → ok (private
        # override). Someone else's private brand → reject.
        if not brand.is_global and brand.created_by_user_id != user_id:
            raise BrandManagementError("not your brand")

        pattern = pattern.strip()
        if not pattern:
            raise BrandManagementError("pattern is required")

        # Always write as private user-scope. Maintainer-curated globals
        # come from the seed script; the API never authors them.
        return self.repo.upsert_pattern(
            brand_id=brand.id,
            kind=kind,
            pattern=pattern,
            is_global=False,
            scope_user_id=user_id,
            is_regex=is_regex,
        )

    # ──────────────────────────────────────────────────────────────────
    # List / picker
    # ──────────────────────────────────────────────────────────────────

    def list_brands_for_picker(
        self,
        *,
        user_id: int,
        q: str | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> list[Brand]:
        brands = self.repo.list_brands_for_user(user_id=user_id)
        if scope == "private":
            brands = [b for b in brands if not b.is_global]
        elif scope == "global":
            brands = [b for b in brands if b.is_global]
        if q:
            ql = q.lower()
            brands = [
                b for b in brands
                if ql in b.slug.lower() or ql in b.canonical_name.lower()
            ]
        return brands[:limit]

    def get_with_patterns(
        self,
        *,
        user_id: int,
        brand_id: int,
    ) -> tuple[Brand, list[BrandPattern]]:
        brand = self.repo.get_brand(brand_id)
        if brand is None:
            raise BrandManagementError("brand not found")
        # Visibility: private brands are only visible to their owner.
        # Global brands are visible to everyone.
        if not brand.is_global and brand.created_by_user_id != user_id:
            raise BrandManagementError("brand not found")
        patterns = self.repo.list_patterns_for_brand(brand_id=brand.id)
        # Filter out other users' private patterns (paranoid; shouldn't
        # exist on a private brand owned by another user — but global
        # brands accumulate per-user overrides we mustn't leak).
        visible = [
            p for p in patterns
            if p.scope_user_id is None or p.scope_user_id == user_id
        ]
        return brand, visible

    # ──────────────────────────────────────────────────────────────────
    # Suggest (single row → prefill form)
    # ──────────────────────────────────────────────────────────────────

    def suggest_from_row(
        self,
        *,
        user_id: int,
        row_id: int,
    ) -> tuple[str | None, str | None, str | None]:
        """Return (canonical_name, pattern_kind, pattern_value) for prefill.

        Returns (None, None, None) when nothing usable can be derived —
        caller should still allow a fully-manual create.
        """
        row, _session = self._load_row_for_user(user_id=user_id, row_id=row_id)
        if row is None:
            return None, None, None

        nd = row.normalized_data_json or {}
        tokens = (nd.get("tokens") or {}) if isinstance(nd, dict) else {}
        skeleton = (nd.get("skeleton") or "") if isinstance(nd, dict) else ""

        sbp_merchant_id = tokens.get("sbp_merchant_id")
        candidate = extract_brand(skeleton) or None
        canonical = candidate.title() if candidate else None

        if sbp_merchant_id:
            # SBP merchant_id is the most precise pattern. canonical_name
            # comes from extractor when available; otherwise blank — user
            # types the brand name themselves.
            return canonical, "sbp_merchant_id", str(sbp_merchant_id)
        if candidate:
            return canonical, "text", candidate
        return None, None, None

    # ──────────────────────────────────────────────────────────────────
    # Unresolved groups (suggestions feed)
    # ──────────────────────────────────────────────────────────────────

    def list_unresolved_groups(
        self,
        *,
        user_id: int,
        session_id: int | None = None,
    ) -> list[_Suggestion]:
        """Group active-session unresolved rows by extracted brand candidate.

        Filters:
          • Same user only (no cross-user pollution).
          • Active sessions only (skip committed history).
          • Rows with skeleton + no `brand_id` + no user_decision.
          • operation_type ∈ {regular, refund, None} — transfers/debts
            don't carry a brand (extractor would mostly return None
            anyway, but the explicit filter keeps the SQL fast).

        Threshold of `_SUGGESTION_MIN_ROWS` rows per candidate avoids
        showing one-shot lines as «brands».
        """
        q = (
            self.db.query(ImportRow, ImportSession)
            .join(ImportSession, ImportRow.session_id == ImportSession.id)
            .filter(
                ImportSession.user_id == user_id,
                ImportSession.status != "committed",
            )
        )
        if session_id is not None:
            q = q.filter(ImportSession.id == session_id)

        groups: dict[str, list[ImportRow]] = defaultdict(list)
        for row, _session in q.all():
            nd = row.normalized_data_json or {}
            if not isinstance(nd, dict):
                continue
            if nd.get("brand_id") is not None:
                continue
            if nd.get("user_confirmed_brand_id") or nd.get("user_rejected_brand_id"):
                continue
            op = (nd.get("operation_type") or "regular").lower()
            if op not in ("regular", "refund"):
                continue
            skeleton = nd.get("skeleton") or ""
            cand = extract_brand(skeleton)
            if not cand:
                continue
            groups[cand].append(row)

        out: list[_Suggestion] = []
        for cand, rows in groups.items():
            if len(rows) < _SUGGESTION_MIN_ROWS:
                continue
            sample = rows[:3]
            out.append(_Suggestion(
                candidate=cand,
                row_count=len(rows),
                sample_descriptions=[_row_description(r) for r in sample],
                sample_row_ids=[r.id for r in sample],
            ))
        out.sort(key=lambda s: (-s.row_count, s.candidate))
        return out

    # ──────────────────────────────────────────────────────────────────
    # Apply brand across a session (bulk-confirm after pattern creation)
    # ──────────────────────────────────────────────────────────────────

    def apply_brand_to_session(
        self,
        *,
        user_id: int,
        brand_id: int,
        session_id: int,
    ) -> dict[str, int]:
        """Re-resolve every unresolved row in `session_id` against the now-
        updated pattern set; confirm each row that matches `brand_id`.

        Driven by the «Создать бренд» flow — a freshly-added pattern only
        appears on rows imported AFTER it. To make the modal-create UX feel
        instantaneous, we re-resolve the active session inline and confirm
        every newly-matching row through `BrandConfirmService` (which sets
        counterparty + category + fingerprint binding correctly).

        Returns counters: matched / confirmed / skipped_user_decision /
        skipped_already_resolved.
        """
        brand = self.repo.get_brand(brand_id)
        if brand is None:
            raise BrandManagementError("brand not found")
        # Visibility: own private OR any global. Same rule as get_with_patterns.
        if not brand.is_global and brand.created_by_user_id != user_id:
            raise BrandManagementError("not your brand")

        session = (
            self.db.query(ImportSession)
            .filter(
                ImportSession.id == session_id,
                ImportSession.user_id == user_id,
            )
            .first()
        )
        if session is None:
            raise BrandManagementError("session not found")
        if session.status == "committed":
            raise BrandManagementError("session already committed")

        rows = (
            self.db.query(ImportRow)
            .filter(ImportRow.session_id == session_id)
            .all()
        )

        resolver = BrandResolverService(self.db)
        confirmer = BrandConfirmService(self.db)

        matched = 0
        confirmed = 0
        skipped_user_decision = 0
        skipped_already_resolved = 0

        for row in rows:
            nd = dict(row.normalized_data_json or {}) if isinstance(row.normalized_data_json, dict) else {}
            if nd.get("user_confirmed_brand_id") or nd.get("user_rejected_brand_id"):
                skipped_user_decision += 1
                continue
            if nd.get("brand_id") == brand_id:
                # Row is already pointing at this brand from a previous resolve;
                # still let confirm_brand_for_row stamp the user-decision below.
                pass
            elif nd.get("brand_id") is not None:
                skipped_already_resolved += 1
                continue

            tokens = _rehydrate_tokens(nd.get("tokens") or {})
            skeleton = nd.get("skeleton") or ""
            match = resolver.resolve(
                skeleton=skeleton, tokens=tokens, user_id=user_id,
            )
            if match is None or match.brand_id != brand_id:
                continue

            matched += 1

            # Stamp prediction onto nd before calling confirmer so the
            # propagation/strength branches in confirm_brand_for_row treat
            # this as a confirmation (predicted == picked).
            nd["brand_id"] = match.brand_id
            nd["brand_pattern_id"] = match.pattern_id
            nd["brand_slug"] = match.brand_slug
            nd["brand_canonical_name"] = match.canonical_name
            nd["brand_category_hint"] = match.category_hint
            nd["brand_kind"] = match.kind
            nd["brand_confidence"] = match.confidence
            row.normalized_data_json = nd
            self.db.add(row)
            self.db.flush()

            try:
                confirmer.confirm_brand_for_row(
                    user_id=user_id, row_id=row.id, brand_id=brand_id,
                )
            except BrandConfirmError as exc:
                logger.warning(
                    "apply_brand_to_session: confirm failed for row %s: %s",
                    row.id, exc,
                )
                continue
            confirmed += 1

        return {
            "matched": matched,
            "confirmed": confirmed,
            "skipped_user_decision": skipped_user_decision,
            "skipped_already_resolved": skipped_already_resolved,
        }

    # ──────────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────────

    def _load_row_for_user(
        self,
        *,
        user_id: int,
        row_id: int,
    ) -> tuple[ImportRow | None, ImportSession | None]:
        joined = (
            self.db.query(ImportRow, ImportSession)
            .join(ImportSession, ImportRow.session_id == ImportSession.id)
            .filter(
                ImportRow.id == row_id,
                ImportSession.user_id == user_id,
            )
            .first()
        )
        if joined is None:
            return None, None
        row, session = joined
        return row, session

    def _generate_unique_slug(self, canonical_name: str, user_id: int) -> str:
        base = _slugify(canonical_name) or "brand"
        # Per-user namespace — the global UNIQUE on Brand.slug crosses
        # users, so collisions on canonical names like «Кофейня» between
        # two users would otherwise fail at insert.
        candidate = f"{base}_u{user_id}"
        if self.repo.get_brand_by_slug(candidate) is None:
            return candidate
        n = 2
        while True:
            attempt = f"{candidate}_{n}"
            if self.repo.get_brand_by_slug(attempt) is None:
                return attempt
            n += 1


# ──────────────────────────────────────────────────────────────────────
# Module helpers (testable in isolation)
# ──────────────────────────────────────────────────────────────────────


_SLUG_PUNCT_RX = re.compile(r"_+")


def _rehydrate_tokens(raw: dict) -> ExtractedTokens:
    """Build a typed ExtractedTokens from the persisted JSON shape.

    `person_name` is intentionally None — the JSON shape stores only the
    boolean `person_name_present`, not the name itself (privacy decision
    on TokensV2). Resolver doesn't care about name for matching.
    """
    return ExtractedTokens(
        phone=raw.get("phone"),
        contract=raw.get("contract"),
        iban=raw.get("iban"),
        card=raw.get("card"),
        person_name=None,
        counterparty_org=raw.get("counterparty_org"),
        sbp_merchant_id=raw.get("sbp_merchant_id"),
        # Backward-compat: rows imported before terminal_id → card_last4
        # rename (Brand registry post-Ph8) still carry the old key.
        card_last4=raw.get("card_last4") or raw.get("terminal_id"),
    )


def _row_description(row: ImportRow) -> str:
    """Best-effort raw description for the suggestions sample list.

    Lives in `normalized_data_json` under `original_description` (preferred,
    set by the import pipeline) or `description` (legacy / before enrichment).
    Falls back to empty string so callers can render None-safely.
    """
    nd = row.normalized_data_json or {}
    if not isinstance(nd, dict):
        return ""
    return str(nd.get("original_description") or nd.get("description") or "").strip()


def _slugify(name: str) -> str:
    """Deterministic ascii slug. 'Nippon Coffee' → 'nippon_coffee';
    'Кофейня «У Дома»' → 'kofeynya_u_doma'."""
    out: list[str] = []
    for ch in name.lower():
        if ch in _CYR_TO_LAT:
            out.append(_CYR_TO_LAT[ch])
        elif ch.isascii() and ch.isalnum():
            out.append(ch)
        elif ch.isspace() or ch in "-_":
            out.append("_")
        # everything else (punctuation, emoji, other-script chars) dropped
    s = _SLUG_PUNCT_RX.sub("_", "".join(out)).strip("_")
    return s[:_SLUG_MAX_LEN]
