"""Unified «+ Имя / Бренд» bind orchestrator (spec v1.27).

The moderator UI exposes a single entry point on every non-transfer row
to name its counterparty — bypassing the prior fork between «Выбрать
бренд» (merchant) and the inline DebtPartner picker (personal contact).
This service routes the user's choice to the right entity:

  • kind='brand'   → Brand (private or global). Stamp brand_id on the
    row, propagate same-brand siblings, optionally bind tokens.phone as
    a brand identifier so future imports auto-resolve. Heavy lifting
    delegated to BrandConfirmService.confirm_brand_for_row — that's
    where pattern auto-learn / category override / sibling propagation
    already live, and we don't fork that flow.

  • kind='contact' → DebtPartner. Stamp `personal_counterparty_*` keys
    on normalized_data so the moderator description switches to the
    contact name. For debt-operation rows we additionally stamp
    `debt_partner_id` because §12.2 invariant requires the FK at commit.
    Token identifiers (phone / contract / person_hash) are persisted to
    `debt_partner_identifiers` and propagated to every other active row
    of the user that carries the same identifier — picking «Брат» on
    one Sber row catches the same +7-prefix on a Tinkoff row uploaded
    next month.

Validations:
  • The row must belong to the user and live in a non-committed session.
  • operation_type='transfer' is rejected — transfers are between own
    accounts and have no counterparty (spec §6.10 / §12.11).
  • debt rows are locked to kind='contact' (§12.2 — operation_type='debt'
    requires debt_partner_id and forbids brand_id).
  • exactly one of {existing_id, name} must be provided.

Returns a `BindResult` describing the chosen entity and how many sibling
rows the propagation step touched. The moderator UI invalidates its
preview/cluster queries on success and the row description re-renders
with the user's chosen label.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.category import Category
from app.models.debt_partner import DebtPartner
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.repositories.brand_repository import BrandRepository
from app.repositories.category_repository import CategoryRepository
from app.repositories.debt_partner_identifier_repository import (
    DebtPartnerIdentifierRepository,
)
from app.repositories.debt_partner_repository import DebtPartnerRepository
from app.repositories.import_repository import ImportRepository
from app.services.brand_confirm_service import BrandConfirmError, BrandConfirmService
from app.services.brand_extractor_service import _TRANSFER_SKELETON_TOKENS
from app.services.brand_identifier_service import BrandIdentifierService
from app.services.brand_management_service import (
    BrandManagementError,
    BrandManagementService,
)

logger = logging.getLogger(__name__)


# DebtPartnerIdentifier kinds — distinct from BrandIdentifier's set:
#   • card / iban  — reserved for transfer-rail bindings; binding a
#     personal contact to «card 4242» would mis-route every transfer.
#   • person_hash  — derived from a free-form name; safe for personal
#     contacts (false positives only collide on identically-spelled
#     names within the same user).
_SUPPORTED_DP_IDENTIFIER_KINDS: frozenset[str] = frozenset({
    "phone", "contract", "person_hash",
})


class PersonalNameBindError(Exception):
    """Raised on validation failures. API maps to 400/404."""


Kind = Literal["brand", "contact"]


@dataclass(frozen=True)
class BindResult:
    kind: Kind
    id: int
    name: str
    category_id: int | None
    category_name: str | None
    propagated_count: int


def _hash_person_name(name: str) -> str:
    """Stable identifier for a person's spelling. Lowercases, collapses
    whitespace, then hex-digests via SHA-256 truncated to 32 chars
    (fits the 128-char column with room to spare). Same input → same
    hash, different formatting (case, double spaces) → same hash too.
    """
    if not name:
        return ""
    canonical = " ".join(name.lower().split())
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _is_transfer_like_skeleton(skeleton: str) -> bool:
    if not skeleton:
        return False
    lowered = skeleton.lower()
    return any(tok in lowered for tok in _TRANSFER_SKELETON_TOKENS)


class PersonalNameBindService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.import_repo = ImportRepository(db)
        self.brand_repo = BrandRepository(db)
        self.dp_repo = DebtPartnerRepository(db)
        self.dp_identifier_repo = DebtPartnerIdentifierRepository(db)
        self.cat_repo = CategoryRepository(db)
        self.brand_id_service = BrandIdentifierService(db)
        self.brand_mgmt = BrandManagementService(db)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def bind_name_to_row(
        self,
        *,
        user_id: int,
        row_id: int,
        kind: Kind,
        name: str | None = None,
        existing_id: int | None = None,
        category_id: int | None = None,
    ) -> BindResult:
        if kind not in ("brand", "contact"):
            raise PersonalNameBindError(
                "kind должен быть 'brand' или 'contact'.",
            )
        if (name is None or not name.strip()) and existing_id is None:
            raise PersonalNameBindError(
                "Укажи name (новое имя) или existing_id (выбрать существующее).",
            )

        session, row = self._load_row(user_id=user_id, row_id=row_id)
        nd = dict(row.normalized_data_json or {})
        op_type = str(nd.get("operation_type") or "regular")

        if op_type == "transfer":
            raise PersonalNameBindError(
                "Перевод между своими счетами не имеет контрагента — назвать его нельзя.",
            )

        # §12.2 invariant guard. brand_id is rejected on debt rows at
        # the Transaction level, so binding a brand here would create
        # state the commit step has to undo.
        if op_type == "debt" and kind == "brand":
            raise PersonalNameBindError(
                "Долговая операция требует контакт, а не бренд.",
            )

        category = self._validate_category(user_id=user_id, category_id=category_id)

        if kind == "brand":
            return self._bind_brand(
                user_id=user_id,
                session=session,
                row=row,
                name=(name or "").strip() if name else None,
                existing_id=existing_id,
                category=category,
            )
        return self._bind_contact(
            user_id=user_id,
            session=session,
            row=row,
            name=(name or "").strip() if name else None,
            existing_id=existing_id,
            category=category,
            op_type=op_type,
        )

    # ------------------------------------------------------------------
    # Brand branch
    # ------------------------------------------------------------------

    def _bind_brand(
        self,
        *,
        user_id: int,
        session: ImportSession,
        row: ImportRow,
        name: str | None,
        existing_id: int | None,
        category: Category | None,
    ) -> BindResult:
        if existing_id is not None:
            brand = self._validate_brand_access(brand_id=existing_id, user_id=user_id)
        else:
            assert name is not None
            brand = self._find_or_create_private_brand(
                user_id=user_id,
                name=name,
                category_hint=(category.name if category is not None else None),
            )

        # Delegate stamp + propagation + auto-learn to the existing
        # BrandConfirmService — single source of truth for brand_id
        # writes. Note: confirm_brand_for_row commits internally.
        confirm_service = BrandConfirmService(self.db)
        try:
            resp = confirm_service.confirm_brand_for_row(
                user_id=user_id,
                row_id=row.id,
                brand_id=brand.id,
                category_id=category.id if category is not None else None,
            )
        except BrandConfirmError as exc:
            raise PersonalNameBindError(str(exc)) from exc

        # Identifier binding: phone-as-brand only on non-transfer rows.
        # The row's transfer-likeness is already guaranteed (we rejected
        # operation_type='transfer' above), but the skeleton guard mirrors
        # the §12.11 card-binding rule one level deeper — defensive.
        # Refresh row state because confirm_service committed.
        row_after = self.db.query(ImportRow).filter(ImportRow.id == row.id).first()
        nd_after = (row_after.normalized_data_json or {}) if row_after else {}
        skeleton = str(nd_after.get("skeleton") or "")
        tokens = nd_after.get("tokens") or {}
        if isinstance(tokens, dict) and not _is_transfer_like_skeleton(skeleton):
            phone = tokens.get("phone")
            if phone:
                try:
                    self.brand_id_service.bind(
                        user_id=user_id,
                        identifier_kind="phone",
                        identifier_value=str(phone),
                        brand_id=brand.id,
                    )
                    self.db.commit()
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "brand identifier bind failed user=%s phone=%s brand=%s",
                        user_id, phone, brand.id, exc_info=True,
                    )
                    self.db.rollback()

        return BindResult(
            kind="brand",
            id=brand.id,
            name=resp.get("brand_canonical_name") or brand.canonical_name,
            category_id=resp.get("category_id"),
            category_name=resp.get("category_name"),
            propagated_count=int(resp.get("propagated_count") or 0),
        )

    def _find_or_create_private_brand(
        self,
        *,
        user_id: int,
        name: str,
        category_hint: str | None,
    ) -> Brand:
        target_fold = name.casefold()
        for b in self.brand_repo.list_brands_for_user(user_id=user_id):
            if not b.is_global and b.created_by_user_id == user_id and (
                (b.canonical_name or "").casefold() == target_fold
            ):
                return b
        try:
            return self.brand_mgmt.create_private_brand(
                user_id=user_id,
                canonical_name=name,
                category_hint=category_hint,
            )
        except BrandManagementError as exc:
            raise PersonalNameBindError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Contact branch
    # ------------------------------------------------------------------

    def _bind_contact(
        self,
        *,
        user_id: int,
        session: ImportSession,
        row: ImportRow,
        name: str | None,
        existing_id: int | None,
        category: Category | None,
        op_type: str,
    ) -> BindResult:
        if existing_id is not None:
            partner = self.dp_repo.get_by_id_and_user(existing_id, user_id)
            if partner is None:
                raise PersonalNameBindError("Контакт не найден.")
        else:
            assert name is not None
            partner, _created = self.dp_repo.find_or_create_by_name(
                user_id=user_id,
                name=name,
                default_category_id=(category.id if category is not None else None),
            )

        # Stamp the row that triggered the bind.
        self._stamp_row(
            row=row,
            partner=partner,
            category_id=(category.id if category is not None else None),
            category_name=(category.name if category is not None else None),
            op_type=op_type,
        )

        # Identifier persistence — record every supported token kind on
        # the row so future imports of the same identifier auto-resolve.
        nd = dict(row.normalized_data_json or {})
        tokens = nd.get("tokens") or {}
        identifier_pairs = self._collect_identifier_pairs(tokens)
        for kind_, value in identifier_pairs:
            self.dp_identifier_repo.upsert(
                user_id=user_id,
                identifier_kind=kind_,
                identifier_value=value,
                debt_partner_id=partner.id,
            )

        # Propagate the stamp across every active row of the user that
        # carries any of the same identifiers. We deliberately scan only
        # rows in non-committed sessions — committed rows are immutable.
        propagated = self._propagate_to_matching_rows(
            user_id=user_id,
            partner=partner,
            category_id=(category.id if category is not None else None),
            category_name=(category.name if category is not None else None),
            identifier_pairs=identifier_pairs,
            except_row_id=row.id,
        )

        self.db.commit()
        self.db.refresh(partner)

        return BindResult(
            kind="contact",
            id=partner.id,
            name=partner.name,
            category_id=partner.default_category_id,
            category_name=(category.name if category is not None else None),
            propagated_count=propagated,
        )

    def _collect_identifier_pairs(
        self, tokens: Any,
    ) -> list[tuple[str, str]]:
        """Pull (kind, value) pairs from the row's tokens. person_hash is
        derived on the fly from `person_name` (the v2 normalizer leaves
        the slot empty by default — we hash here so the binding survives
        across rows that re-spell the same name).
        """
        if not isinstance(tokens, dict):
            return []
        pairs: list[tuple[str, str]] = []
        phone = tokens.get("phone")
        if phone:
            pairs.append(("phone", str(phone)))
        contract = tokens.get("contract")
        if contract:
            pairs.append(("contract", str(contract)))
        # Honour an explicit person_hash if upstream populated one;
        # otherwise derive from person_name. Both forms are stable.
        person_hash = tokens.get("person_hash")
        if not person_hash:
            person_name = tokens.get("person_name")
            if person_name:
                person_hash = _hash_person_name(str(person_name))
        if person_hash:
            pairs.append(("person_hash", str(person_hash)))
        # Filter to supported kinds (defensive — keeps the contract on
        # the repo upsert simple).
        return [
            (k, v) for (k, v) in pairs
            if k in _SUPPORTED_DP_IDENTIFIER_KINDS and v
        ]

    def _propagate_to_matching_rows(
        self,
        *,
        user_id: int,
        partner: DebtPartner,
        category_id: int | None,
        category_name: str | None,
        identifier_pairs: list[tuple[str, str]],
        except_row_id: int,
    ) -> int:
        """Stamp every other active row of the user whose tokens carry
        any of the same identifier values. Same-row stamp already
        applied by the caller.

        Walks rows in active (non-committed) sessions. Skips rows that
        already carry the same `personal_counterparty_id` to keep the
        operation idempotent — repeated binds against the same partner
        return propagated_count=0 the second time.
        """
        if not identifier_pairs:
            return 0
        wanted: dict[str, set[str]] = {}
        for k, v in identifier_pairs:
            wanted.setdefault(k, set()).add(v)

        rows = (
            self.db.query(ImportRow)
            .join(ImportSession, ImportRow.session_id == ImportSession.id)
            .filter(
                ImportSession.user_id == user_id,
                ImportSession.status != "committed",
                ImportRow.id != except_row_id,
            )
            .all()
        )
        propagated = 0
        for r in rows:
            nd = dict(r.normalized_data_json or {})
            if nd.get("personal_counterparty_id") == partner.id:
                continue
            tokens = nd.get("tokens") or {}
            if not isinstance(tokens, dict):
                continue
            # Match if ANY identifier kind/value overlaps. Single shared
            # phone is enough to claim the row — user's intent on one
            # row binds the contact across the user's data.
            person_hash = tokens.get("person_hash")
            if not person_hash and tokens.get("person_name"):
                person_hash = _hash_person_name(str(tokens.get("person_name")))
            row_pairs = {
                "phone": str(tokens.get("phone") or ""),
                "contract": str(tokens.get("contract") or ""),
                "person_hash": str(person_hash or ""),
            }
            matched = False
            for k, vs in wanted.items():
                if row_pairs.get(k) and row_pairs[k] in vs:
                    matched = True
                    break
            if not matched:
                continue
            r_op_type = str(nd.get("operation_type") or "regular")
            self._stamp_row(
                row=r,
                partner=partner,
                category_id=category_id,
                category_name=category_name,
                op_type=r_op_type,
            )
            propagated += 1
        return propagated

    def _stamp_row(
        self,
        *,
        row: ImportRow,
        partner: DebtPartner,
        category_id: int | None,
        category_name: str | None,
        op_type: str,
    ) -> None:
        nd = dict(row.normalized_data_json or {})
        # Defensive: a transfer row should never reach the stamp path
        # (rejected up top). Belt-and-braces guard for the propagation
        # loop, which iterates rows of mixed op_types.
        if str(nd.get("operation_type") or "regular") == "transfer":
            return
        nd["personal_counterparty_id"] = partner.id
        nd["personal_counterparty_name"] = partner.name
        if category_id is not None:
            nd["personal_counterparty_category_id"] = category_id
        else:
            nd.pop("personal_counterparty_category_id", None)
        if category_name is not None:
            nd["personal_counterparty_category_name"] = category_name
        else:
            nd.pop("personal_counterparty_category_name", None)
        # Debt-row §12.2 — also stamp the FK column so commit_orchestrator
        # passes validation. Other op_types don't carry a personal-contact
        # FK on Transaction; the stamp lives in normalized_data only.
        if op_type == "debt":
            nd["debt_partner_id"] = partner.id
            nd.pop("brand_id", None)
            nd.pop("user_confirmed_brand_id", None)
        # Brands and contacts are mutually exclusive on a row — clear
        # any leftover brand stamps so the moderator UI doesn't render
        # both at once.
        if op_type != "debt":
            # For non-debt rows we leave brand stamps alone if the row
            # already had a confirmed brand — the user re-binding to a
            # contact via this flow is unusual but supported. Replace
            # the brand markers so the description switches over.
            for key in (
                "brand_id", "brand_slug", "brand_canonical_name",
                "brand_category_hint", "brand_pattern_id",
                "user_confirmed_brand_id", "user_confirmed_brand_at",
                "user_rejected_brand_id", "user_rejected_brand_at",
            ):
                nd.pop(key, None)
        # Mark the bind time so downstream consumers (preview
        # serializer, audit log) can tell the stamp came from an
        # explicit user action vs. an inferred enrichment.
        nd["personal_counterparty_bound_at"] = datetime.now(timezone.utc).isoformat()
        row.normalized_data_json = nd
        self.db.add(row)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load_row(
        self, *, user_id: int, row_id: int,
    ) -> tuple[ImportSession, ImportRow]:
        result = self.import_repo.get_row_for_user(row_id=row_id, user_id=user_id)
        if result is None:
            raise PersonalNameBindError("Строка импорта не найдена.")
        session, row = result
        if str(session.status or "") == "committed":
            raise PersonalNameBindError("Сессия уже закоммичена.")
        if (
            row.created_transaction_id is not None
            or str(row.status or "") == "committed"
        ):
            raise PersonalNameBindError("Строка уже импортирована.")
        return session, row

    def _validate_brand_access(self, *, brand_id: int, user_id: int) -> Brand:
        brand = self.brand_repo.get_brand(brand_id)
        if brand is None:
            raise PersonalNameBindError("Бренд не найден.")
        if not brand.is_global and brand.created_by_user_id != user_id:
            raise PersonalNameBindError("Бренд недоступен.")
        return brand

    def _validate_category(
        self, *, user_id: int, category_id: int | None,
    ) -> Category | None:
        if category_id is None:
            return None
        cat = self.cat_repo.get_by_id(category_id=category_id, user_id=user_id)
        if cat is None:
            raise PersonalNameBindError("Категория не найдена.")
        return cat
