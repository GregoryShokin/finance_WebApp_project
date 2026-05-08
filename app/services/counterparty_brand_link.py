"""CP→Brand resolver helper used by services that still accept
`counterparty_id` from clients (transaction form, legacy import paths)
and need to stamp `brand_id` alongside it during the dual-write window
(Phase C steps 2–3).

The lookup mirrors migration 0067 / `sweep_import_rows_cp_to_brand` so
the resolver and the data-move script always agree on which Brand a
given Counterparty maps to:

  1. case-fold equality with a Brand visible to the user (private wins
     over global on ties);
  2. otherwise create a private Brand for the user with the CP name as
     canonical_name (slug via BrandManagementService — same suffix
     convention the rest of the codebase already produces).

Step 4 turns this helper off — at that point clients submit `brand_id`
directly and CP-only payloads stop being accepted.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.brand import Brand
from app.models.counterparty import Counterparty
from app.repositories.brand_repository import BrandRepository
from app.services.brand_management_service import BrandManagementService


def resolve_brand_id_for_counterparty(
    db: Session, *, user_id: int, counterparty_id: int,
) -> int | None:
    """Return the Brand id that mirrors this Counterparty for the user.

    Creates a private Brand on first use when no existing Brand matches
    the CP name. Returns None only when the counterparty doesn't exist
    or doesn't belong to the user — caller treats that as a no-op stamp
    (the FK validation upstream catches the real error).
    """
    cp = (
        db.query(Counterparty)
        .filter(
            Counterparty.id == counterparty_id,
            Counterparty.user_id == user_id,
        )
        .first()
    )
    if cp is None:
        return None
    return resolve_brand_id_for_name(db, user_id=user_id, name=cp.name)


def resolve_brand_id_for_name(
    db: Session, *, user_id: int, name: str,
) -> int:
    """Variant for callers that already have the canonical name in hand
    (`brand_confirm._dualwrite_counterparty`-adjacent flows). Always
    returns a brand id — creates a private Brand if no match exists.
    """
    target_fold = (name or "").strip().casefold()
    if not target_fold:
        raise ValueError("name must be non-empty")

    repo = BrandRepository(db)
    visible = repo.list_brands_for_user(user_id=user_id)
    private_match: Brand | None = None
    global_match: Brand | None = None
    for b in visible:
        if (b.canonical_name or "").casefold() != target_fold:
            continue
        if not b.is_global and b.created_by_user_id == user_id:
            private_match = b
            break
        if b.is_global and global_match is None:
            global_match = b
    matched = private_match or global_match
    if matched is not None:
        return matched.id

    mgmt = BrandManagementService(db)
    brand = mgmt.create_private_brand(
        user_id=user_id,
        canonical_name=name.strip(),
        category_hint=None,
    )
    db.flush()
    return brand.id
