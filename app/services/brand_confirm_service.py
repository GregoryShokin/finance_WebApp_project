"""Brand confirm/reject orchestrator (Brand registry Ph6, post-Phase C).

Two flows used by the moderator inline-prompt («Это <Brand>?»):

Confirm — user picks a brand for a row.
  * If the brand matches what the resolver predicted → bump pattern.confirms,
    propagate `user_confirmed_brand_*` to every row of the same session
    that resolved to the same brand. One click closes the prompt across
    the whole session-of-this-brand.
  * If the brand differs from the prediction → the resolver was wrong:
    bump pattern.rejections, stamp the user's choice on the row only.
    Other same-prediction rows still need separate attention.

Reject — user says «not this brand» without offering an alternative.
  * Bump pattern.rejections; stamp `user_rejected_brand_id` on the row so
    the resolver doesn't re-suggest the same brand on next read. No
    propagation — rejection is row-local.

Phase C (step 2): Brand IS the merchant entity now. `_get_brand_for_user`
returns the Brand; the prompt response carries `brand_id`. Counterparty
materialisation continues as a dual-write side effect — same DB row gets
created/updated with the same name so legacy reads keep working until
step 4 turns dual-write off.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.category import Category
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.repositories.brand_repository import BrandRepository
from app.repositories.category_repository import CategoryRepository
from app.repositories.import_repository import ImportRepository
from app.repositories.user_brand_category_override_repository import (
    UserBrandCategoryOverrideRepository,
)
from app.repositories.user_brand_display_name_repository import (
    UserBrandDisplayNameRepository,
)
from app.services.brand_extractor_service import extract_brand, is_personal_identifier_row
from app.services.brand_fingerprint_service import BrandFingerprintService
from app.services.brand_pattern_strength_service import (
    BrandPatternNotFound,
    BrandPatternStrengthService,
)

import logging

logger = logging.getLogger(__name__)

# Payment-rail tokens that must never be auto-learned as text-kind brand
# patterns. These are infrastructure identifiers (payment networks, clearing
# systems, card schemes), not merchants. Even if extract_brand surfaces one
# (e.g. via a Cyrillic alias or an unseen statement format), it gets blocked
# here so callers can't bootstrap a spurious text:sbp pattern by confirming a
# row that happens to have "sbp" as its first significant skeleton token.
_FORBIDDEN_LEARN_TOKENS: frozenset[str] = frozenset({
    "sbp", "сбп",           # Система Быстрых Платежей (payment rail)
    "qsr", "mop",           # NSPK merchant-category codes
    "pos",                  # point-of-sale terminal code
    "atm",                  # ATM code
    "mir", "visa", "mastercard",   # card schemes
})


def _looks_like_merchant_token(candidate: str) -> bool:
    """Structural guard for auto-learn candidates (spec v1.27).

    A real merchant token reaches our skeleton as a Latin transliteration
    («vkusnoitochka», «pyaterochka», «mrtshka», «kofemoloko») — bank
    statements may carry Russian wrapper text («Оплата товаров и услуг
    YANDEX*5399*market»), but the merchant identifier itself is almost
    always ASCII. A Cyrillic-only candidate from `extract_brand` therefore
    signals «we picked up a Russian wrapper word that bypassed
    `_FILLER_TOKENS`» — exactly the bug that produced
    `товаров`/`семейная`/`кофейня`-shaped private patterns matching every
    future statement of the same wording.

    Rule: auto-learn accepts a candidate only when it consists entirely
    of ASCII letters / digits / underscore. The minimum length is the
    same as `extract_brand`'s `_MIN_BRAND_LEN` (3) — real merchant codes
    can be that short (e.g. «dts» for МРТшка terminals). Manual
    «+ Создать бренд» (BrandManagementService.create_private_brand) is
    unaffected — Russian-named private brands stay possible, they just
    don't get auto-bootstrapped from a single confirm.
    """
    if not candidate or len(candidate) < 3:
        return False
    return all(
        ch.isascii() and (ch.isalnum() or ch == "_")
        for ch in candidate
    )


class BrandConfirmError(Exception):
    """Raised on validation failures (row not found, session committed, …).

    Caller (API layer) maps this to 400/404. Distinct exception type so
    bulk callers can catch & continue.
    """


class BrandConfirmService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.brand_repo = BrandRepository(db)
        self.import_repo = ImportRepository(db)
        self.category_repo = CategoryRepository(db)
        self.brand_fp_service = BrandFingerprintService(db)
        self.strength = BrandPatternStrengthService(db)
        self.override_repo = UserBrandCategoryOverrideRepository(db)
        self.display_repo = UserBrandDisplayNameRepository(db)

    # ------------------------------------------------------------------
    # Confirm
    # ------------------------------------------------------------------

    def confirm_brand_for_row(
        self,
        *,
        user_id: int,
        row_id: int,
        brand_id: int,
        category_id: int | None = None,
    ) -> dict[str, Any]:
        """Confirm a brand for one row.

        Optional `category_id`: when the user picks a category in the
        confirm prompt different from the brand's default hint, save that
        choice as a per-user override for this brand and apply it across
        every same-brand row in the session. Subsequent imports auto-pick
        the override too.
        """
        session, row = self._load_row(user_id=user_id, row_id=row_id)
        brand = self._validate_brand(brand_id=brand_id, user_id=user_id)
        explicit_category = (
            self._validate_category(user_id=user_id, category_id=category_id)
            if category_id is not None else None
        )

        # User picked an explicit category at confirm time → save as
        # override so future imports of this brand resolve to it without
        # asking again.
        if explicit_category is not None:
            self.override_repo.upsert(
                user_id=user_id, brand_id=brand.id, category_id=explicit_category.id,
            )

        nd = dict(row.normalized_data_json or {})
        predicted_pattern_id = nd.get("brand_pattern_id")
        predicted_brand_id = nd.get("brand_id")

        # Strength signal: only bump confirms when user agrees with the
        # resolver's prediction. Disagreement → rejection of the predicted
        # pattern (the user's choice is stamped without creating a new
        # pattern — pattern auto-creation is a future learning loop).
        try:
            if predicted_pattern_id and predicted_brand_id == brand.id:
                self.strength.on_confirmed(int(predicted_pattern_id))
            elif predicted_pattern_id:
                self.strength.on_rejected(int(predicted_pattern_id))
        except BrandPatternNotFound:
            pass

        # Phase C step 4: Brand is the only merchant entity now.
        # `_get_brand_for_user` returns the user's preferred display
        # label (UserBrandDisplayName when set, else canonical_name).
        # No Counterparty row created — that table is on its way out
        # (step 5 drops it).
        display_name = self._get_brand_for_user(user_id=user_id, brand=brand)
        # Category resolution: explicit (just-picked) > override > hint.
        if explicit_category is not None:
            category = explicit_category
        else:
            category = self._lookup_category_for_brand(
                user_id=user_id, brand=brand,
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        nd["user_confirmed_brand_id"] = brand.id
        nd["user_confirmed_brand_at"] = now_iso
        nd.pop("user_rejected_brand_id", None)
        nd.pop("user_rejected_brand_at", None)
        # Backfill brand display fields when the row had no resolver match.
        # tx-row.tsx renders «{brand_canonical_name}» as primary only when
        # `nd.brand_canonical_name` is set; without this, a manually-picked
        # brand (where the resolver returned None) keeps showing the raw
        # bank description even after confirm. Don't overwrite an existing
        # value — the resolver's match is the authoritative source when present.
        if not nd.get("brand_canonical_name"):
            nd["brand_id"] = brand.id
            nd["brand_slug"] = brand.slug
            nd["brand_canonical_name"] = brand.canonical_name
            nd["brand_category_hint"] = brand.category_hint
        else:
            # Always ensure brand_id is up to date even when display
            # fields were pre-populated by the resolver — the user might
            # have switched to a different brand after the first match.
            nd["brand_id"] = brand.id
        # Counterparty stamp removed in step 4. Existing rows retain
        # whatever stamp the dual-write era left; new confirms only
        # touch the brand side.
        nd.pop("counterparty_id", None)
        if category is not None and not nd.get("category_id"):
            # Only auto-fill category when the user hasn't picked one
            # already — manual choice always wins over a brand hint.
            nd["category_id"] = category.id
        row.normalized_data_json = nd
        self.db.add(row)

        # Bind the row's fingerprint to the Brand store. The legacy
        # counterparty_fingerprints binding is gone — step 4 made
        # brand_fingerprints the sole authoritative target.
        self._bind_fingerprint_brand(
            user_id=user_id,
            fingerprint=nd.get("fingerprint"),
            brand_id=brand.id,
        )

        # Auto-learn: extract a brand candidate from this row's skeleton and
        # upsert as a private text-pattern on the brand. Closes the gap where
        # a user manually attaches a brand to a row whose skeleton differs
        # from the brand's existing patterns — e.g. picking «MRTшка» on
        # «оплата в dts mrt» when the brand was created from a «mrtshка» row.
        # Without this, the next apply_brand_to_session call still misses
        # the dts-skeleton fingerprints, even though the user just told us
        # they belong to the same brand.
        # Pass tokens so the guard can skip personal-identifier rows (§X v1.26).
        self._learn_pattern_from_row(
            user_id=user_id, brand=brand, skeleton=nd.get("skeleton") or "",
            tokens=nd.get("tokens"),
        )

        # Propagate confirmation only when the user agreed with the
        # resolver — same-brand siblings inherit category. `force_category=True`
        # when the user explicitly picked one in the prompt: brand-level
        # decision overrides per-row state.
        propagated = 0
        if predicted_brand_id == brand.id:
            propagated = self._propagate_confirm(
                user_id=user_id,
                session_id=session.id,
                except_row_id=row.id,
                brand_id=brand.id,
                category_id=category.id if category is not None else None,
                now_iso=now_iso,
                force_category=explicit_category is not None,
            )

        self.db.commit()
        self.db.refresh(row)
        return {
            "row_id": row.id,
            "brand_id": brand.id,
            "brand_slug": brand.slug,
            "brand_canonical_name": brand.canonical_name,
            "brand_display_name": display_name,
            "category_id": category.id if category is not None else None,
            "category_name": category.name if category is not None else None,
            "propagated_count": propagated,
            "was_override": predicted_brand_id != brand.id,
        }

    # ------------------------------------------------------------------
    # Reject
    # ------------------------------------------------------------------

    def reject_brand_for_row(
        self,
        *,
        user_id: int,
        row_id: int,
    ) -> dict[str, Any]:
        _, row = self._load_row(user_id=user_id, row_id=row_id)

        nd = dict(row.normalized_data_json or {})
        predicted_pattern_id = nd.get("brand_pattern_id")
        predicted_brand_id = nd.get("brand_id")

        if predicted_pattern_id is None or predicted_brand_id is None:
            raise BrandConfirmError(
                "Строка не содержит предсказанного бренда — нечего отклонять.",
            )

        try:
            self.strength.on_rejected(int(predicted_pattern_id))
        except BrandPatternNotFound:
            pass

        now_iso = datetime.now(timezone.utc).isoformat()
        nd["user_rejected_brand_id"] = predicted_brand_id
        nd["user_rejected_brand_at"] = now_iso
        nd.pop("user_confirmed_brand_id", None)
        nd.pop("user_confirmed_brand_at", None)
        row.normalized_data_json = nd
        self.db.add(row)

        self.db.commit()
        self.db.refresh(row)
        return {
            "row_id": row.id,
            "rejected_brand_id": predicted_brand_id,
        }

    # ------------------------------------------------------------------
    # Standalone brand-category override (post-confirmation editing)
    # ------------------------------------------------------------------

    def apply_brand_category_for_user(
        self, *, user_id: int, brand_id: int, category_id: int,
    ) -> dict[str, Any]:
        """Set per-user category override for a brand and re-apply across
        every active import row that resolved to it.

        Use case: user already confirmed «Dodo Pizza» as «Кафе и
        рестораны» (default hint), now wants it as «Доставка еды» across
        all 26 historical operations + every future import. One call:
        saves override, sweeps active session rows, returns count.

        Affects:
          • UserBrandCategoryOverride row (upsert).
          • normalized_data.category_id on every active-session ImportRow
            whose `brand_id` == this brand. Existing per-row category is
            REPLACED — this is a brand-level decision by the user.
        """
        brand = self._validate_brand(brand_id=brand_id, user_id=user_id)
        category = self._validate_category(user_id=user_id, category_id=category_id)

        override, _is_new = self.override_repo.upsert(
            user_id=user_id, brand_id=brand.id, category_id=category.id,
        )

        rows_updated = 0
        rows = (
            self.db.query(ImportRow)
            .join(ImportSession, ImportRow.session_id == ImportSession.id)
            .filter(
                ImportSession.user_id == user_id,
                ImportSession.status != "committed",
            )
            .all()
        )
        for r in rows:
            rd = dict(r.normalized_data_json or {})
            if rd.get("brand_id") != brand.id:
                continue
            if rd.get("category_id") == category.id:
                continue
            rd["category_id"] = category.id
            r.normalized_data_json = rd
            self.db.add(r)
            rows_updated += 1

        self.db.commit()
        return {
            "brand_id": brand.id,
            "brand_canonical_name": brand.canonical_name,
            "category_id": category.id,
            "category_name": category.name,
            "rows_updated": rows_updated,
            "override_id": override.id,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load_row(
        self, *, user_id: int, row_id: int,
    ) -> tuple[ImportSession, ImportRow]:
        result = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
        if result is None:
            raise BrandConfirmError("Строка импорта не найдена.")
        session, row = result
        if str(session.status or "") == "committed":
            raise BrandConfirmError("Сессия уже закоммичена.")
        if (
            row.created_transaction_id is not None
            or str(row.status or "") == "committed"
        ):
            raise BrandConfirmError("Строка уже импортирована.")
        return session, row

    def _validate_brand(self, *, brand_id: int, user_id: int) -> Brand:
        brand = self.brand_repo.get_brand(brand_id)
        if brand is None:
            raise BrandConfirmError("Бренд не найден.")
        if not brand.is_global and brand.created_by_user_id != user_id:
            # Defensive: a private brand belongs to one user.
            raise BrandConfirmError("Бренд недоступен.")
        return brand

    def _propagate_confirm(
        self,
        *,
        user_id: int,
        session_id: int,
        except_row_id: int,
        brand_id: int,
        category_id: int | None,
        now_iso: str,
        force_category: bool = False,
    ) -> int:
        rows = (
            self.db.query(ImportRow)
            .filter(
                ImportRow.session_id == session_id,
                ImportRow.id != except_row_id,
            )
            .all()
        )
        propagated = 0
        for r in rows:
            rd = dict(r.normalized_data_json or {})
            if rd.get("brand_id") != brand_id:
                continue
            if rd.get("user_confirmed_brand_id") == brand_id:
                continue
            rd["user_confirmed_brand_id"] = brand_id
            rd["user_confirmed_brand_at"] = now_iso
            rd.pop("user_rejected_brand_id", None)
            rd.pop("user_rejected_brand_at", None)
            # Counterparty stamp removed in step 4 — siblings only inherit
            # the brand confirmation and (optionally) the category. Step 5
            # drops nd.counterparty_id from the JSON shape entirely.
            rd.pop("counterparty_id", None)
            # Category propagation rules:
            #   • force_category=True (user picked a category at confirm
            #     time, i.e. brand-level decision) → overwrite even if
            #     siblings already had a category.
            #   • force_category=False (default hint/override applied
            #     silently) → only fill empty slots; respect prior edits.
            if category_id is not None:
                if force_category or not rd.get("category_id"):
                    rd["category_id"] = category_id
            r.normalized_data_json = rd
            self.db.add(r)
            self._bind_fingerprint_brand(
                user_id=user_id,
                fingerprint=rd.get("fingerprint"),
                brand_id=brand_id,
            )
            propagated += 1
        return propagated

    # ── Brand / Counterparty materialization (Phase C) ─────────────────

    def _get_brand_for_user(
        self, *, user_id: int, brand: Brand,
    ) -> str:
        """Resolve the user's preferred display label for this Brand.

        Returns the UserBrandDisplayName override if the user has one
        for this brand (e.g. they renamed «Пятёрочка» to «Пятёрочка у
        дома» in the moderator), else the brand's canonical_name.

        Replaces the pre-Phase-C `_find_or_create_counterparty`. Brand
        is now the merchant entity — no Counterparty row is created.
        """
        override = self.display_repo.get(user_id=user_id, brand_id=brand.id)
        if override is not None and override.display_name:
            return override.display_name
        return brand.canonical_name

    def _lookup_category_for_brand(
        self, *, user_id: int, brand: Brand,
    ) -> Category | None:
        """Override-aware category resolution for a brand.

        Order:
          1. UserBrandCategoryOverride (per-user pin set explicitly).
          2. Brand.category_hint matched against user's categories by
             case-folded name.

        No category creation — if neither path resolves to a real Category
        owned by the user, returns None and the row stays without a
        category (counterparty binding still happens). The user picks
        manually in the moderator UI.
        """
        override = self.override_repo.get(user_id=user_id, brand_id=brand.id)
        if override is not None:
            cat = (
                self.db.query(Category)
                .filter(
                    Category.id == override.category_id,
                    Category.user_id == user_id,
                )
                .first()
            )
            if cat is not None:
                return cat

        if not brand.category_hint:
            return None
        target_fold = brand.category_hint.casefold()
        candidates = (
            self.db.query(Category)
            .filter(Category.user_id == user_id)
            .all()
        )
        for c in candidates:
            if (c.name or "").casefold() == target_fold:
                return c
        return None

    # Backward-compat alias used by Ph7c backfill script.
    _lookup_category_by_hint = _lookup_category_for_brand

    def _validate_category(
        self, *, user_id: int, category_id: int,
    ) -> Category:
        cat = (
            self.db.query(Category)
            .filter(Category.id == category_id, Category.user_id == user_id)
            .first()
        )
        if cat is None:
            raise BrandConfirmError("Категория не найдена.")
        return cat

    def _learn_pattern_from_row(
        self, *, user_id: int, brand: Brand, skeleton: str,
        tokens: dict | None = None,
    ) -> None:
        """Best-effort upsert of a `text` pattern derived from the row's skeleton.

        Idempotent and silent on failure — pattern learning is an opportunistic
        side-effect of confirm, never part of the contract. Safe to call from
        bulk paths (apply_brand_to_session) — duplicate writes are deduped by
        casefold equality with any existing pattern (regardless of scope, so
        we never grow a private duplicate of a global pattern).

        Why a private pattern: confirm authors per-user knowledge — global
        brands accumulate user-scope overrides exactly the same way the
        explicit «add pattern» UI does (see `add_pattern_to_brand`).

        Personal-identifier guard (Brand Registry §X, v1.26): if the row
        identifies a personal contact (phone / contract / person_name) with
        no merchant org or SBP ID, we skip auto-learning. The user explicitly
        chose to bind this row to a Brand (accepted override), but we MUST NOT
        propagate that binding by creating a generic text-pattern like
        «погашение» or «поступление» — those words match every future row of
        the same kind, associating unrelated operations with the same brand.
        The explicit fingerprint binding still applies (one-row learning only).
        """
        if not skeleton:
            return
        if is_personal_identifier_row(skeleton, tokens):
            logger.debug(
                "auto-learn: skipping personal-identifier row for brand %s", brand.id,
            )
            return
        candidate = extract_brand(skeleton)
        if not candidate:
            return
        if candidate.casefold() in _FORBIDDEN_LEARN_TOKENS:
            logger.debug(
                "auto-learn: skipping forbidden rail token %r (brand %s)",
                candidate, brand.id,
            )
            return
        # Structural guard — see `_looks_like_merchant_token` docstring.
        # Catches Cyrillic generic words («товаров», «семейная»,
        # «кофейня») and ultra-short Latin abbreviations («ip», «ms»,
        # «md») that no `_FILLER_TOKENS` extension can hope to enumerate
        # exhaustively.
        if not _looks_like_merchant_token(candidate):
            logger.debug(
                "auto-learn: skipping non-merchant-shaped token %r (brand %s)",
                candidate, brand.id,
            )
            return
        candidate_cf = candidate.casefold()
        # Same-brand idempotency: don't recreate a pattern this brand
        # already owns (any scope).
        existing = self.brand_repo.list_patterns_for_brand(brand_id=brand.id)
        for p in existing:
            if p.kind != "text":
                continue
            if (p.pattern or "").casefold() == candidate_cf:
                return
        # Cross-brand ambiguity guard (spec v1.27): if any OTHER brand
        # visible to the user already owns this exact text-pattern,
        # auto-learn would create competing matches — every future row
        # with this token would resolve unpredictably depending on
        # _sort_key tie-breaks. Common case: user has «Яндекс Плюс»
        # carrying a private pattern «yandex», then confirms a Маркет
        # row → without this guard we'd attach «yandex» to Маркет too,
        # and from then on every yandex-* row matches whichever pattern
        # `_sort_key` picks first. Refuse instead — the user can delete
        # the existing pattern manually if they meant to re-bind.
        all_user_patterns = self.brand_repo.list_active_patterns_for_user(
            user_id=user_id,
        )
        for p in all_user_patterns:
            if p.kind != "text" or p.brand_id == brand.id:
                continue
            if (p.pattern or "").casefold() == candidate_cf:
                logger.debug(
                    "auto-learn: skipping %r — already bound to brand %s, ambiguous",
                    candidate, p.brand_id,
                )
                return
        try:
            self.brand_repo.upsert_pattern(
                brand_id=brand.id,
                kind="text",
                pattern=candidate,
                is_global=False,
                scope_user_id=user_id,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "auto-learn pattern upsert failed for brand %s, candidate %r",
                brand.id, candidate, exc_info=True,
            )

    def _bind_fingerprint_brand(
        self,
        *,
        user_id: int,
        fingerprint: Any,
        brand_id: int,
    ) -> None:
        """Best-effort fingerprint → Brand binding.

        Phase C step 4: brand_fingerprints is the only authoritative
        store; the counterparty_fingerprints write was removed. The
        binding is a learning side effect (never part of the
        confirmation contract) so we swallow the rare exception.
        """
        if not fingerprint:
            return
        try:
            self.brand_fp_service.bind(
                user_id=user_id, fingerprint=str(fingerprint), brand_id=brand_id,
            )
        except Exception:  # noqa: BLE001
            pass
