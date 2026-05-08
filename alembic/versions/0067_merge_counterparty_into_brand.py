"""Merge Counterparty into Brand at the DB level (Phase C, step 1).

Revision ID: 0067
Revises: 0066
Create Date: 2026-05-08

Background. Phase A introduced Brand as a recognition layer above
Counterparty. Phase B (v1.24, commit bebb2d0) unified the moderator UI
around Brand. Both still co-exist at the DB level: confirming a brand
materialises a Counterparty, every binding goes via the
counterparty_*-tables. The two entities drift the moment a confirm in
one UI surface stamps Counterparty while another stamps Brand alone —
production already saw 41 rows go out of sync in a single day.

This migration is step 1 of 5 in the Phase C drop. After this revision
runs:

  • brand_fingerprints / brand_identifiers exist alongside the legacy
    counterparty_fingerprints / counterparty_identifiers (legacy tables
    stay readable; step 5 drops them).
  • transactions.brand_id is populated for every row that had
    counterparty_id (counterparty_id stays so step 2 can dual-write).
  • user_brand_display_names is the new home for «Пятёрочка у дома»-style
    per-user labels that previously hid in renamed Counterparty rows.

Mapping rule per Counterparty:
  1. case-fold equality with an existing Brand visible to the user
     (private, then global).
  2. otherwise create a private Brand for the user with the
     Counterparty.name as canonical_name.

Brand creation reuses the BrandManagementService slug logic via
inline helpers — keeping the migration self-contained so it survives
future refactors of the service module.

When the matched Brand has a different canonical_name (the user
renamed «Пятёрочка» to «Пятёрочка у дома»), a UserBrandDisplayName
row preserves the per-user label without forking the global brand.

Counterparty.opening_receivable_amount / opening_payable_amount are
NOT carried over — those fields are dead since the DebtPartner split
on 2026-04-24 and have no Brand equivalent.

Downgrade restores the legacy column / FK shape but cannot recover
UserBrandDisplayName — `brand_id` reverts to a nullable column for
forward compatibility.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0067"
down_revision: Union[str, None] = "0066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ──────────────────────────────────────────────────────────────────────────
# Slug helpers (inlined from BrandManagementService — keep migration
# self-contained against future service refactors).
# ──────────────────────────────────────────────────────────────────────────

_CYR_TO_LAT: dict[str, str] = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
_SLUG_MAX_LEN = 48


def _slugify(name: str) -> str:
    out: list[str] = []
    for ch in name.lower():
        if ch in _CYR_TO_LAT:
            out.append(_CYR_TO_LAT[ch])
        elif ch.isascii() and ch.isalnum():
            out.append(ch)
        elif ch.isspace() or ch in "-_":
            out.append("_")
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    slug = slug.strip("_")[:_SLUG_MAX_LEN]
    return slug or "brand"


def _generate_unique_slug(conn, *, canonical_name: str, user_id: int) -> str:
    base = _slugify(canonical_name)
    candidate = f"{base}_u{user_id}"
    sql = sa.text("SELECT 1 FROM brands WHERE slug = :slug LIMIT 1")
    if conn.execute(sql, {"slug": candidate}).first() is None:
        return candidate
    n = 2
    while True:
        attempt = f"{candidate}_{n}"
        if conn.execute(sql, {"slug": attempt}).first() is None:
            return attempt
        n += 1


# ──────────────────────────────────────────────────────────────────────────
# Data-move helper (split out so the migration test can exercise it
# against a hand-built SQLite fixture without invoking the full alembic
# stack).
# ──────────────────────────────────────────────────────────────────────────


def migrate_data(conn) -> None:  # noqa: C901 — sequential SQL, splitting hurts clarity
    """Populate brand_id / brand_fingerprints / brand_identifiers /
    user_brand_display_names from existing counterparty_* rows.

    Assumes the new tables and `transactions.brand_id` already exist
    (created by the alembic operations at the top of `upgrade()` or by
    the test fixture). All writes are idempotent at the row level —
    duplicate runs skip rows that already moved.
    """
    cp_rows = conn.execute(sa.text(
        "SELECT id, user_id, name FROM counterparties"
    )).fetchall()

    cp_to_brand: dict[int, int] = {}
    user_brand_cache: dict[int, dict[str, int]] = {}
    user_renames: list[tuple[int, int, str]] = []  # (user_id, brand_id, display_name)

    def _load_user_brands(uid: int) -> dict[str, int]:
        cache = user_brand_cache.get(uid)
        if cache is not None:
            return cache
        # Visible brands for the user: every global + their privates.
        # Order matters: prefer the user's own private over a same-named
        # global. The picker uses the same ordering, so this matches
        # what the user would see.
        rows = conn.execute(sa.text(
            """
            SELECT id, canonical_name, is_global, created_by_user_id
            FROM brands
            WHERE is_global = TRUE OR created_by_user_id = :uid
            """
        ), {"uid": uid}).fetchall()
        cache = {}
        for r in rows:
            if r.is_global:
                cache.setdefault(str(r.canonical_name).casefold(), int(r.id))
        for r in rows:
            if not r.is_global and r.created_by_user_id == uid:
                cache[str(r.canonical_name).casefold()] = int(r.id)
        user_brand_cache[uid] = cache
        return cache

    for cp in cp_rows:
        uid = int(cp.user_id)
        name = str(cp.name or "").strip()
        if not name:
            continue
        cache = _load_user_brands(uid)
        key = name.casefold()
        brand_id = cache.get(key)
        matched_canonical: str | None = None
        if brand_id is not None:
            row = conn.execute(sa.text(
                "SELECT canonical_name FROM brands WHERE id = :bid"
            ), {"bid": brand_id}).first()
            matched_canonical = str(row.canonical_name) if row else None
        if brand_id is None:
            slug = _generate_unique_slug(conn, canonical_name=name, user_id=uid)
            conn.execute(sa.text(
                """
                INSERT INTO brands (
                    slug, canonical_name, category_hint,
                    is_global, created_by_user_id,
                    created_at, updated_at
                )
                VALUES (
                    :slug, :name, NULL,
                    FALSE, :uid,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ), {"slug": slug, "name": name, "uid": uid})
            # Read back via slug — uniformly portable across SQLite (where
            # `lastrowid` works) and Postgres (where it doesn't on plain
            # text() inserts). Slug is UNIQUE, so this is single-row.
            brand_id = int(conn.execute(sa.text(
                "SELECT id FROM brands WHERE slug = :slug"
            ), {"slug": slug}).scalar_one())
            cache[key] = brand_id
        elif matched_canonical is not None and matched_canonical != name:
            # CP name differs from matched brand's canonical_name → user
            # renamed it («Пятёрочка у дома»). Preserve the per-user
            # label without forking the global brand.
            user_renames.append((uid, int(brand_id), name))
        cp_to_brand[int(cp.id)] = brand_id

    # Backfill transactions.brand_id.
    for cp_id, brand_id in cp_to_brand.items():
        conn.execute(sa.text(
            "UPDATE transactions SET brand_id = :bid WHERE counterparty_id = :cid"
        ), {"bid": brand_id, "cid": cp_id})

    # Backfill brand_fingerprints.
    cp_fp_rows = conn.execute(sa.text(
        """
        SELECT user_id, fingerprint, counterparty_id, confirms,
               created_at, updated_at
        FROM counterparty_fingerprints
        """
    )).fetchall()
    for fp in cp_fp_rows:
        new_brand_id = cp_to_brand.get(int(fp.counterparty_id))
        if new_brand_id is None:
            continue
        # Idempotency: skip if (user, fingerprint) already migrated.
        existing = conn.execute(sa.text(
            """
            SELECT 1 FROM brand_fingerprints
            WHERE user_id = :uid AND fingerprint = :fp LIMIT 1
            """
        ), {"uid": int(fp.user_id), "fp": str(fp.fingerprint)}).first()
        if existing is not None:
            continue
        conn.execute(sa.text(
            """
            INSERT INTO brand_fingerprints
                (user_id, fingerprint, brand_id, confirms,
                 created_at, updated_at)
            VALUES
                (:uid, :fp, :bid, :confirms, :ca, :ua)
            """
        ), {
            "uid": int(fp.user_id), "fp": str(fp.fingerprint),
            "bid": new_brand_id, "confirms": int(fp.confirms or 1),
            "ca": fp.created_at, "ua": fp.updated_at,
        })

    # Backfill brand_identifiers.
    cp_id_rows = conn.execute(sa.text(
        """
        SELECT user_id, identifier_kind, identifier_value,
               counterparty_id, confirms, created_at, updated_at
        FROM counterparty_identifiers
        """
    )).fetchall()
    for ci in cp_id_rows:
        new_brand_id = cp_to_brand.get(int(ci.counterparty_id))
        if new_brand_id is None:
            continue
        existing = conn.execute(sa.text(
            """
            SELECT 1 FROM brand_identifiers
            WHERE user_id = :uid AND identifier_kind = :kind
                  AND identifier_value = :val LIMIT 1
            """
        ), {
            "uid": int(ci.user_id),
            "kind": str(ci.identifier_kind),
            "val": str(ci.identifier_value),
        }).first()
        if existing is not None:
            continue
        conn.execute(sa.text(
            """
            INSERT INTO brand_identifiers
                (user_id, identifier_kind, identifier_value, brand_id,
                 confirms, created_at, updated_at)
            VALUES
                (:uid, :kind, :val, :bid, :confirms, :ca, :ua)
            """
        ), {
            "uid": int(ci.user_id),
            "kind": str(ci.identifier_kind),
            "val": str(ci.identifier_value),
            "bid": new_brand_id,
            "confirms": int(ci.confirms or 1),
            "ca": ci.created_at, "ua": ci.updated_at,
        })

    # Persist user-rename overrides.
    for uid, brand_id, display_name in user_renames:
        existing = conn.execute(sa.text(
            """
            SELECT 1 FROM user_brand_display_names
            WHERE user_id = :uid AND brand_id = :bid LIMIT 1
            """
        ), {"uid": uid, "bid": brand_id}).first()
        if existing is not None:
            continue
        conn.execute(sa.text(
            """
            INSERT INTO user_brand_display_names
                (user_id, brand_id, display_name, created_at, updated_at)
            VALUES
                (:uid, :bid, :dn, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        ), {"uid": uid, "bid": brand_id, "dn": display_name})


# ──────────────────────────────────────────────────────────────────────────
# Upgrade
# ──────────────────────────────────────────────────────────────────────────


def upgrade() -> None:
    # 1. transactions.brand_id (nullable; NULL means «no merchant», same
    #    semantics as counterparty_id NULL did for debt/transfer rows).
    op.add_column(
        "transactions",
        sa.Column(
            "brand_id",
            sa.Integer(),
            sa.ForeignKey("brands.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_transactions_brand_id",
        "transactions",
        ["brand_id"],
    )

    # 2. user_brand_display_names — per-user override for the visible
    #    label of a brand. Mirrors UserBrandCategoryOverride shape.
    op.create_table(
        "user_brand_display_names",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "brand_id",
            sa.Integer(),
            sa.ForeignKey("brands.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "user_id", "brand_id",
            name="uq_user_brand_display_names_user_brand",
        ),
    )

    # 3. brand_fingerprints — same shape as counterparty_fingerprints with
    #    counterparty_id → brand_id rename. Created fresh; data backfilled
    #    in step 5 below.
    op.create_table(
        "brand_fingerprints",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("fingerprint", sa.String(32), nullable=False, index=True),
        sa.Column(
            "brand_id",
            sa.Integer(),
            sa.ForeignKey("brands.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "confirms",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "user_id", "fingerprint",
            name="uq_brand_fingerprint_user_fp",
        ),
    )

    # 4. brand_identifiers — same shape as counterparty_identifiers.
    op.create_table(
        "brand_identifiers",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("identifier_kind", sa.String(16), nullable=False),
        sa.Column("identifier_value", sa.String(128), nullable=False),
        sa.Column(
            "brand_id",
            sa.Integer(),
            sa.ForeignKey("brands.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "confirms",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "user_id", "identifier_kind", "identifier_value",
            name="uq_brand_identifier_user_kind_value",
        ),
    )

    # 5. Run the data-move (backfill brand_id, fingerprints, identifiers,
    #    user-rename overrides). Logic lives in `migrate_data` so the
    #    migration test can exercise it without invoking alembic.
    migrate_data(op.get_bind())


# ──────────────────────────────────────────────────────────────────────────
# Downgrade
# ──────────────────────────────────────────────────────────────────────────


def downgrade() -> None:
    """Restore the column / FK shape. Data already living in the legacy
    tables is unchanged. Brand-scoped data added since upgrade (new
    fingerprints, identifiers, display-name overrides) is dropped — these
    rows have no counterparty equivalent and the user must re-confirm
    after rolling back.
    """
    op.drop_table("brand_identifiers")
    op.drop_table("brand_fingerprints")
    op.drop_table("user_brand_display_names")
    op.drop_index("ix_transactions_brand_id", table_name="transactions")
    op.drop_column("transactions", "brand_id")
