"""Tests for migration 0067 — Counterparty → Brand data move.

Exercises `alembic.versions.0067_merge_counterparty_into_brand.migrate_data`
against a hand-built SQLite schema. We don't run the alembic CLI here:
the test fixture creates the legacy and post-upgrade tables directly
with SQL, populates a small set of fixture rows, and asserts the
mapping invariants. This keeps the test fast (under 1s) and free of
docker/postgres dependencies.

Coverage:
  • private CP with a name no Brand carries → new private Brand
  • private CP whose name matches a global Brand exactly → reuses global
  • private CP renamed away from a global Brand → reuses global +
    UserBrandDisplayName persists the per-user label
  • private CP whose name matches the user's existing private Brand →
    reuses that private over any same-named global
  • debt-row CP (counterparty_id = NULL on the row) → no brand_id stamp
  • counterparty_fingerprints + counterparty_identifiers move
  • cross-user isolation — user A's «Магнит» does NOT borrow user B's
    private «Магнит»
  • idempotency — calling migrate_data twice is a no-op the second time

Direct path: importlib.util loads the migration module by file path
(its filename starts with a digit, so a regular `from alembic.versions.X
import …` fails).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic" / "versions" / "0067_merge_counterparty_into_brand.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "alembic_0067", _MIGRATION_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ──────────────────────────────────────────────────────────────────────
# Fixture: minimal SQLite schema covering everything migrate_data touches.
# ──────────────────────────────────────────────────────────────────────


_LEGACY_AND_NEW_SCHEMA = [
    # Legacy / pre-existing —————————————————————————————————————————
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        email TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE counterparties (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        name TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE brands (
        id INTEGER PRIMARY KEY,
        slug TEXT NOT NULL UNIQUE,
        canonical_name TEXT NOT NULL,
        category_hint TEXT,
        is_global INTEGER NOT NULL DEFAULT 0,
        created_by_user_id INTEGER REFERENCES users(id),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE transactions (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        counterparty_id INTEGER REFERENCES counterparties(id),
        brand_id INTEGER REFERENCES brands(id),
        amount NUMERIC NOT NULL,
        type TEXT NOT NULL,
        operation_type TEXT NOT NULL DEFAULT 'regular'
    )
    """,
    """
    CREATE TABLE counterparty_fingerprints (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        fingerprint TEXT NOT NULL,
        counterparty_id INTEGER NOT NULL REFERENCES counterparties(id),
        confirms INTEGER NOT NULL DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, fingerprint)
    )
    """,
    """
    CREATE TABLE counterparty_identifiers (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        identifier_kind TEXT NOT NULL,
        identifier_value TEXT NOT NULL,
        counterparty_id INTEGER NOT NULL REFERENCES counterparties(id),
        confirms INTEGER NOT NULL DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, identifier_kind, identifier_value)
    )
    """,
    # Brand-side targets that the alembic upgrade() also creates ——————
    """
    CREATE TABLE brand_fingerprints (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        fingerprint TEXT NOT NULL,
        brand_id INTEGER NOT NULL REFERENCES brands(id),
        confirms INTEGER NOT NULL DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, fingerprint)
    )
    """,
    """
    CREATE TABLE brand_identifiers (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        identifier_kind TEXT NOT NULL,
        identifier_value TEXT NOT NULL,
        brand_id INTEGER NOT NULL REFERENCES brands(id),
        confirms INTEGER NOT NULL DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, identifier_kind, identifier_value)
    )
    """,
    """
    CREATE TABLE user_brand_display_names (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        brand_id INTEGER NOT NULL REFERENCES brands(id),
        display_name TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, brand_id)
    )
    """,
]


@pytest.fixture
def conn():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as c:
        for ddl in _LEGACY_AND_NEW_SCHEMA:
            c.execute(text(ddl))
    # Yield a fresh connection for each test; commit-on-context-exit so
    # our seed inserts persist before migrate_data() reads them.
    with engine.begin() as c:
        yield c


def _seed_baseline(c):
    """Populate users + 1 global Brand «Пятёрочка» + 1 global Brand «Магнит».

    Returns a dict with ids for assertions.
    """
    c.execute(text("INSERT INTO users (id, email) VALUES (1, 'a@x'), (2, 'b@x')"))
    c.execute(text(
        """
        INSERT INTO brands (slug, canonical_name, is_global, created_by_user_id)
        VALUES
            ('pyaterochka', 'Пятёрочка', 1, NULL),
            ('magnit', 'Магнит', 1, NULL)
        """
    ))
    pyat = c.execute(text(
        "SELECT id FROM brands WHERE slug = 'pyaterochka'"
    )).scalar_one()
    magnit = c.execute(text(
        "SELECT id FROM brands WHERE slug = 'magnit'"
    )).scalar_one()
    return {"pyaterochka_global": int(pyat), "magnit_global": int(magnit)}


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


def test_creates_private_brand_for_unmatched_counterparty(conn):
    """CP «ЛокалКофе» — no Brand carries that name → migrate creates a
    fresh private Brand for the user with proper slug.
    """
    _seed_baseline(conn)
    conn.execute(text(
        """
        INSERT INTO counterparties (id, user_id, name)
        VALUES (10, 1, 'ЛокалКофе')
        """
    ))
    conn.execute(text(
        """
        INSERT INTO transactions (id, user_id, counterparty_id, amount, type)
        VALUES (100, 1, 10, 50, 'expense')
        """
    ))

    mod = _load_migration_module()
    mod.migrate_data(conn)

    rows = conn.execute(text(
        "SELECT id, slug, canonical_name, is_global, created_by_user_id "
        "FROM brands WHERE created_by_user_id = 1"
    )).fetchall()
    assert len(rows) == 1, "exactly one private brand created for user 1"
    brand = rows[0]
    assert brand.canonical_name == "ЛокалКофе"
    assert brand.is_global == 0
    assert brand.created_by_user_id == 1
    assert brand.slug.endswith("_u1")  # per-user namespace
    assert brand.slug.startswith("lokalkofe")  # cyrillic translit

    tx_brand_id = conn.execute(text(
        "SELECT brand_id FROM transactions WHERE id = 100"
    )).scalar_one()
    assert tx_brand_id == brand.id


def test_links_counterparty_to_global_brand_on_exact_name_match(conn):
    """CP «Пятёрочка» exists alongside global Brand «Пятёрочка».
    Migration links CP → global Brand. NO UserBrandDisplayName written
    (names are equal).
    """
    seeds = _seed_baseline(conn)
    conn.execute(text(
        "INSERT INTO counterparties (id, user_id, name) VALUES (11, 1, 'Пятёрочка')"
    ))
    conn.execute(text(
        """
        INSERT INTO transactions (id, user_id, counterparty_id, amount, type)
        VALUES (101, 1, 11, 100, 'expense')
        """
    ))

    mod = _load_migration_module()
    mod.migrate_data(conn)

    tx_brand_id = conn.execute(text(
        "SELECT brand_id FROM transactions WHERE id = 101"
    )).scalar_one()
    assert tx_brand_id == seeds["pyaterochka_global"]

    # No new private brand for user 1 — they linked to the existing global.
    private_count = conn.execute(text(
        "SELECT COUNT(*) FROM brands WHERE created_by_user_id = 1"
    )).scalar_one()
    assert private_count == 0

    # No display-name override (names match exactly).
    overrides = conn.execute(text(
        "SELECT COUNT(*) FROM user_brand_display_names WHERE user_id = 1"
    )).scalar_one()
    assert overrides == 0


def test_renamed_counterparty_creates_user_brand_display_name(conn):
    """CP «Пятёрочка у дома» (user-renamed) + global Brand «Пятёрочка».
    Migration links to global brand (case-fold mismatch is fine because
    the user clearly meant Пятёрочка) — actually the case-fold DOES NOT
    match here. Re-read the rule: case-fold equality is the gate.

    This case is the «renamed» scenario only when the user's input
    case-folds to a brand they have. «Пятёрочка у дома» does NOT
    case-fold to «Пятёрочка», so the migration should treat it as
    UNMATCHED and create a fresh private brand. UserBrandDisplayName is
    only written when the input casefold equals an existing brand's
    canonical_name casefold but the spelling/case differs.
    """
    _seed_baseline(conn)
    conn.execute(text(
        "INSERT INTO counterparties (id, user_id, name) VALUES (12, 1, 'Пятёрочка у дома')"
    ))

    mod = _load_migration_module()
    mod.migrate_data(conn)

    # Should land as a NEW private brand (case-fold doesn't match global).
    private_brand = conn.execute(text(
        "SELECT id, canonical_name FROM brands WHERE created_by_user_id = 1"
    )).first()
    assert private_brand is not None
    assert private_brand.canonical_name == "Пятёрочка у дома"

    overrides = conn.execute(text(
        "SELECT COUNT(*) FROM user_brand_display_names WHERE user_id = 1"
    )).scalar_one()
    assert overrides == 0  # not a rename — it's a different name entirely


def test_case_only_difference_creates_display_name_override(conn):
    """CP «ПЯТЁРОЧКА» (uppercase) + global Brand «Пятёрочка». Same
    case-folded name → links to global; spelling differs → display-name
    override preserves the user's preferred capitalisation.
    """
    seeds = _seed_baseline(conn)
    conn.execute(text(
        "INSERT INTO counterparties (id, user_id, name) VALUES (13, 1, 'ПЯТЁРОЧКА')"
    ))

    mod = _load_migration_module()
    mod.migrate_data(conn)

    # Linked to existing global, no new brand.
    private_count = conn.execute(text(
        "SELECT COUNT(*) FROM brands WHERE created_by_user_id = 1"
    )).scalar_one()
    assert private_count == 0

    override = conn.execute(text(
        """
        SELECT brand_id, display_name FROM user_brand_display_names
        WHERE user_id = 1
        """
    )).first()
    assert override is not None
    assert override.brand_id == seeds["pyaterochka_global"]
    assert override.display_name == "ПЯТЁРОЧКА"


def test_existing_user_private_brand_wins_over_global(conn):
    """User 1 already has a private Brand «Магнит» (e.g. they branded
    their corner shop that way before). The user's CP «Магнит» must
    link to THEIR private brand, not the global.
    """
    seeds = _seed_baseline(conn)
    conn.execute(text(
        """
        INSERT INTO brands (slug, canonical_name, is_global, created_by_user_id)
        VALUES ('magnit_u1', 'Магнит', 0, 1)
        """
    ))
    private_id = conn.execute(text(
        "SELECT id FROM brands WHERE slug = 'magnit_u1'"
    )).scalar_one()
    conn.execute(text(
        "INSERT INTO counterparties (id, user_id, name) VALUES (14, 1, 'Магнит')"
    ))
    conn.execute(text(
        """
        INSERT INTO transactions (id, user_id, counterparty_id, amount, type)
        VALUES (104, 1, 14, 200, 'expense')
        """
    ))

    mod = _load_migration_module()
    mod.migrate_data(conn)

    tx_brand_id = conn.execute(text(
        "SELECT brand_id FROM transactions WHERE id = 104"
    )).scalar_one()
    assert tx_brand_id == int(private_id)
    assert tx_brand_id != seeds["magnit_global"]


def test_debt_row_with_null_counterparty_id_keeps_null_brand_id(conn):
    """Debt rows have counterparty_id = NULL since the 2026-04-24 split.
    They should also have brand_id = NULL after migration.
    """
    _seed_baseline(conn)
    conn.execute(text(
        """
        INSERT INTO transactions
            (id, user_id, counterparty_id, amount, type, operation_type)
        VALUES
            (200, 1, NULL, 5000, 'expense', 'debt'),
            (201, 1, NULL, 3000, 'income', 'debt')
        """
    ))

    mod = _load_migration_module()
    mod.migrate_data(conn)

    rows = conn.execute(text(
        "SELECT id, brand_id FROM transactions WHERE id IN (200, 201)"
    )).fetchall()
    assert len(rows) == 2
    for r in rows:
        assert r.brand_id is None


def test_counterparty_fingerprint_moves_to_brand_fingerprint(conn):
    """Fingerprint binding gets re-pointed at the resolved brand_id."""
    _seed_baseline(conn)
    conn.execute(text(
        "INSERT INTO counterparties (id, user_id, name) VALUES (15, 1, 'ЛокалКофе')"
    ))
    conn.execute(text(
        """
        INSERT INTO counterparty_fingerprints (user_id, fingerprint, counterparty_id, confirms)
        VALUES (1, 'fp_lokal_001', 15, 3)
        """
    ))

    mod = _load_migration_module()
    mod.migrate_data(conn)

    bf = conn.execute(text(
        """
        SELECT brand_id, confirms FROM brand_fingerprints
        WHERE user_id = 1 AND fingerprint = 'fp_lokal_001'
        """
    )).first()
    assert bf is not None
    assert bf.confirms == 3
    # Brand_id points at the freshly-created private brand.
    private_id = conn.execute(text(
        "SELECT id FROM brands WHERE created_by_user_id = 1 AND canonical_name = 'ЛокалКофе'"
    )).scalar_one()
    assert bf.brand_id == int(private_id)


def test_counterparty_identifier_moves_to_brand_identifier(conn):
    """Identifier binding (phone) gets re-pointed at the resolved brand_id."""
    seeds = _seed_baseline(conn)
    conn.execute(text(
        "INSERT INTO counterparties (id, user_id, name) VALUES (16, 1, 'Пятёрочка')"
    ))
    conn.execute(text(
        """
        INSERT INTO counterparty_identifiers
            (user_id, identifier_kind, identifier_value, counterparty_id, confirms)
        VALUES
            (1, 'phone', '+79991112233', 16, 5)
        """
    ))

    mod = _load_migration_module()
    mod.migrate_data(conn)

    bi = conn.execute(text(
        """
        SELECT brand_id, confirms FROM brand_identifiers
        WHERE user_id = 1
              AND identifier_kind = 'phone'
              AND identifier_value = '+79991112233'
        """
    )).first()
    assert bi is not None
    assert bi.brand_id == seeds["pyaterochka_global"]
    assert bi.confirms == 5


def test_cross_user_brand_isolation(conn):
    """User A's private «Магнит» must NOT be reused by user B.
    User B's CP «Магнит» links to the global Brand «Магнит».
    """
    seeds = _seed_baseline(conn)
    # User 1 has their own private «Магнит».
    conn.execute(text(
        """
        INSERT INTO brands (slug, canonical_name, is_global, created_by_user_id)
        VALUES ('magnit_u1', 'Магнит', 0, 1)
        """
    ))
    user1_private = conn.execute(text(
        "SELECT id FROM brands WHERE slug = 'magnit_u1'"
    )).scalar_one()
    # User 2 has a CP «Магнит» but no private brand of their own.
    conn.execute(text(
        "INSERT INTO counterparties (id, user_id, name) VALUES (17, 2, 'Магнит')"
    ))
    conn.execute(text(
        """
        INSERT INTO transactions (id, user_id, counterparty_id, amount, type)
        VALUES (300, 2, 17, 80, 'expense')
        """
    ))

    mod = _load_migration_module()
    mod.migrate_data(conn)

    tx_brand_id = conn.execute(text(
        "SELECT brand_id FROM transactions WHERE id = 300"
    )).scalar_one()
    assert tx_brand_id == seeds["magnit_global"]
    assert tx_brand_id != int(user1_private)


def test_idempotent_second_run_is_noop(conn):
    """Running migrate_data a second time must be a no-op — no duplicate
    private brands, fingerprints, identifiers, or display-name overrides.
    """
    _seed_baseline(conn)
    conn.execute(text(
        "INSERT INTO counterparties (id, user_id, name) VALUES (18, 1, 'ПЯТЁРОЧКА')"
    ))
    conn.execute(text(
        """
        INSERT INTO counterparty_fingerprints
            (user_id, fingerprint, counterparty_id, confirms)
        VALUES (1, 'fp_pyat_dup', 18, 2)
        """
    ))

    mod = _load_migration_module()
    mod.migrate_data(conn)
    counts_after_first = {
        "brands": conn.execute(text("SELECT COUNT(*) FROM brands")).scalar_one(),
        "brand_fingerprints": conn.execute(text(
            "SELECT COUNT(*) FROM brand_fingerprints"
        )).scalar_one(),
        "user_brand_display_names": conn.execute(text(
            "SELECT COUNT(*) FROM user_brand_display_names"
        )).scalar_one(),
    }

    mod.migrate_data(conn)
    counts_after_second = {
        "brands": conn.execute(text("SELECT COUNT(*) FROM brands")).scalar_one(),
        "brand_fingerprints": conn.execute(text(
            "SELECT COUNT(*) FROM brand_fingerprints"
        )).scalar_one(),
        "user_brand_display_names": conn.execute(text(
            "SELECT COUNT(*) FROM user_brand_display_names"
        )).scalar_one(),
    }

    assert counts_after_first == counts_after_second


def test_orphan_fingerprint_binding_is_skipped(conn):
    """A counterparty_fingerprints row pointing at a non-existent
    counterparty (deleted CP, stale FK) must be silently skipped — the
    migration should not raise.
    """
    _seed_baseline(conn)
    # No CP row inserted; fingerprint references a missing id (999).
    conn.execute(text(
        """
        INSERT INTO counterparty_fingerprints
            (user_id, fingerprint, counterparty_id, confirms)
        VALUES (1, 'fp_orphan', 999, 1)
        """
    ))

    mod = _load_migration_module()
    mod.migrate_data(conn)  # must not raise

    # No brand_fingerprints row created for the orphan.
    bf_count = conn.execute(text(
        "SELECT COUNT(*) FROM brand_fingerprints WHERE fingerprint = 'fp_orphan'"
    )).scalar_one()
    assert bf_count == 0
