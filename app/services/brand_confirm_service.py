"""Brand confirm/reject orchestrator (Brand registry Ph6).

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

Counterparty bindings are NOT touched here. The existing
`attach_row_to_cluster` flow stays the contract for «I've decided this
row belongs to counterparty X». Brand confirm is a layer above —
informs the user's choice (showing the brand badge on the prompt UI),
but doesn't auto-create CounterpartyFingerprint bindings on its own.
That behaviour is a Ph7+ enhancement.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.category import Category
from app.models.counterparty import Counterparty
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.repositories.brand_repository import BrandRepository
from app.repositories.category_repository import CategoryRepository
from app.repositories.counterparty_repository import CounterpartyRepository
from app.repositories.import_repository import ImportRepository
from app.repositories.user_brand_category_override_repository import (
    UserBrandCategoryOverrideRepository,
)
from app.services.brand_pattern_strength_service import (
    BrandPatternNotFound,
    BrandPatternStrengthService,
)
from app.services.counterparty_fingerprint_service import (
    CounterpartyFingerprintService,
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
        self.cp_repo = CounterpartyRepository(db)
        self.category_repo = CategoryRepository(db)
        self.cp_fp_service = CounterpartyFingerprintService(db)
        self.strength = BrandPatternStrengthService(db)
        self.override_repo = UserBrandCategoryOverrideRepository(db)

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

        # Materialize the brand into a usable Counterparty + Category for
        # this user. find-or-create by name (case-insensitive equality).
        # Existing counterparties win over creation so user-edited names
        # ("Пятёрочка у дома") survive Brand confirms — we only create a
        # fresh row when no counterparty for that brand yet exists.
        counterparty = self._find_or_create_counterparty(
            user_id=user_id, brand=brand,
        )
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
        # Carry the resolved entity ids on the row so commit-time
        # transaction-builder picks them up the same way as a manual
        # confirm via `update_row`.
        nd["counterparty_id"] = counterparty.id
        if category is not None and not nd.get("category_id"):
            # Only auto-fill category when the user hasn't picked one
            # already — manual choice always wins over a brand hint.
            nd["category_id"] = category.id
        row.normalized_data_json = nd
        self.db.add(row)

        # Bind the row's fingerprint to the counterparty so future imports
        # of any skeleton resolving to this brand go straight to the right
        # counterparty without prompting again.
        self._bind_fingerprint(
            user_id=user_id, fingerprint=nd.get("fingerprint"),
            counterparty_id=counterparty.id,
        )

        # Propagate confirmation only when the user agreed with the
        # resolver — same-brand siblings inherit counterparty + category.
        # `force_category=True` when the user explicitly picked one in
        # the prompt: brand-level decision overrides per-row state.
        propagated = 0
        if predicted_brand_id == brand.id:
            propagated = self._propagate_confirm(
                user_id=user_id,
                session_id=session.id,
                except_row_id=row.id,
                brand_id=brand.id,
                counterparty_id=counterparty.id,
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
            "counterparty_id": counterparty.id,
            "counterparty_name": counterparty.name,
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
        counterparty_id: int,
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
            # Inherit the resolved counterparty for every sibling — they
            # all match the same brand, so they belong to the same merchant
            # entity from the user's perspective.
            rd["counterparty_id"] = counterparty_id
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
            self._bind_fingerprint(
                user_id=user_id, fingerprint=rd.get("fingerprint"),
                counterparty_id=counterparty_id,
            )
            propagated += 1
        return propagated

    # ── Counterparty / Category materialization ─────────────────────────

    def _find_or_create_counterparty(
        self, *, user_id: int, brand: Brand,
    ) -> Counterparty:
        """Find existing counterparty by case-insensitive name match, or create.

        Case-folding is done Python-side because SQLite's SQL `lower()`
        is ASCII-only — Cyrillic survives unchanged on that engine, which
        is what powers our test fixtures. Postgres lower() handles
        Cyrillic correctly, but the Python loop works on both engines.
        """
        target_fold = brand.canonical_name.casefold()
        candidates = (
            self.db.query(Counterparty)
            .filter(Counterparty.user_id == user_id)
            .all()
        )
        for c in candidates:
            if (c.name or "").casefold() == target_fold:
                return c
        return self.cp_repo.create(
            user_id=user_id, name=brand.canonical_name, auto_commit=False,
        )

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

    def _bind_fingerprint(
        self,
        *,
        user_id: int,
        fingerprint: Any,
        counterparty_id: int,
    ) -> None:
        """Best-effort `CounterpartyFingerprint` binding.

        Never raises — the binding is a learning side-effect, not part of
        the confirmation contract. A row can be confirmed even without a
        fingerprint (degraded normalizer output); we just skip the bind.
        """
        if not fingerprint:
            return
        try:
            self.cp_fp_service.bind(
                user_id=user_id,
                fingerprint=str(fingerprint),
                counterparty_id=counterparty_id,
            )
        except Exception:  # noqa: BLE001
            # Non-fatal: confirm flow continues, sibling propagation still
            # works through normalized_data.counterparty_id.
            pass
