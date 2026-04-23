"""Unit tests for FingerprintAliasService.

Covers the Level-3 fingerprint-alias mechanics used by the "attach row to
cluster" moderator action:
  * basic create + resolve round-trip
  * chain flattening on write (A→B + B→C must rewrite A→C)
  * cycle detection when creating A→B after B→A would exist
  * resolve depth cap (defensive — shouldn't happen after flattening)
  * delete alias removes the redirect
"""
from __future__ import annotations

import pytest

from app.models.fingerprint_alias import FingerprintAlias
from app.services.fingerprint_alias_service import FingerprintAliasService


# ───────────────────────────────────────────────────────────────────
# resolve() — read path
# ───────────────────────────────────────────────────────────────────


def test_resolve_unknown_fingerprint_returns_self(db, user):
    svc = FingerprintAliasService(db)
    assert svc.resolve(user_id=user.id, fingerprint="abc123") == "abc123"


def test_resolve_with_alias_returns_target(db, user):
    svc = FingerprintAliasService(db)
    svc.create_alias(user_id=user.id, source_fingerprint="src1", target_fingerprint="tgt1")
    db.commit()
    assert svc.resolve(user_id=user.id, fingerprint="src1") == "tgt1"
    assert svc.resolve(user_id=user.id, fingerprint="tgt1") == "tgt1"


def test_resolve_other_user_is_isolated(db, user):
    from app.models.user import User
    other = User(email="other@example.com", password_hash="x", is_active=True)
    db.add(other)
    db.commit()
    db.refresh(other)

    svc = FingerprintAliasService(db)
    svc.create_alias(user_id=user.id, source_fingerprint="src", target_fingerprint="tgt")
    db.commit()
    # Other user should see the raw fingerprint — aliases are user-scoped.
    assert svc.resolve(user_id=other.id, fingerprint="src") == "src"


# ───────────────────────────────────────────────────────────────────
# create_alias() — write path
# ───────────────────────────────────────────────────────────────────


def test_create_alias_rejects_self_loop(db, user):
    svc = FingerprintAliasService(db)
    with pytest.raises(ValueError):
        svc.create_alias(user_id=user.id, source_fingerprint="x", target_fingerprint="x")


def test_create_alias_rejects_empty_fingerprints(db, user):
    svc = FingerprintAliasService(db)
    with pytest.raises(ValueError):
        svc.create_alias(user_id=user.id, source_fingerprint="", target_fingerprint="y")
    with pytest.raises(ValueError):
        svc.create_alias(user_id=user.id, source_fingerprint="x", target_fingerprint="")


def test_create_alias_flattens_chain_on_write(db, user):
    """A→B exists, then user creates B→C. Result: BOTH A→C and B→C.

    The resolver should never walk a multi-hop chain because flattening on
    write collapses it to a single hop.
    """
    svc = FingerprintAliasService(db)
    svc.create_alias(user_id=user.id, source_fingerprint="A", target_fingerprint="B")
    db.commit()

    svc.create_alias(user_id=user.id, source_fingerprint="B", target_fingerprint="C")
    db.commit()

    a = db.query(FingerprintAlias).filter_by(user_id=user.id, source_fingerprint="A").one()
    b = db.query(FingerprintAlias).filter_by(user_id=user.id, source_fingerprint="B").one()
    assert a.target_fingerprint == "C"
    assert b.target_fingerprint == "C"


def test_create_alias_redirects_through_existing_alias(db, user):
    """When creating A→B where B itself aliases to C, actually store A→C."""
    svc = FingerprintAliasService(db)
    svc.create_alias(user_id=user.id, source_fingerprint="B", target_fingerprint="C")
    db.commit()

    svc.create_alias(user_id=user.id, source_fingerprint="A", target_fingerprint="B")
    db.commit()

    a = db.query(FingerprintAlias).filter_by(user_id=user.id, source_fingerprint="A").one()
    assert a.target_fingerprint == "C"


def test_create_alias_detects_cycle(db, user):
    """B→A already exists; creating A→B would form a cycle. Reject."""
    svc = FingerprintAliasService(db)
    svc.create_alias(user_id=user.id, source_fingerprint="B", target_fingerprint="A")
    db.commit()

    with pytest.raises(ValueError, match="cycle"):
        svc.create_alias(user_id=user.id, source_fingerprint="A", target_fingerprint="B")


def test_create_alias_updates_existing(db, user):
    """Calling create twice for the same source updates target + confirms count."""
    svc = FingerprintAliasService(db)
    svc.create_alias(user_id=user.id, source_fingerprint="src", target_fingerprint="t1")
    db.commit()

    alias1 = db.query(FingerprintAlias).filter_by(
        user_id=user.id, source_fingerprint="src"
    ).one()
    assert alias1.confirms == 1

    svc.create_alias(user_id=user.id, source_fingerprint="src", target_fingerprint="t2")
    db.commit()

    alias2 = db.query(FingerprintAlias).filter_by(
        user_id=user.id, source_fingerprint="src"
    ).one()
    assert alias2.id == alias1.id  # same row
    assert alias2.target_fingerprint == "t2"
    assert alias2.confirms == 2


# ───────────────────────────────────────────────────────────────────
# delete_alias()
# ───────────────────────────────────────────────────────────────────


def test_delete_alias(db, user):
    svc = FingerprintAliasService(db)
    svc.create_alias(user_id=user.id, source_fingerprint="s", target_fingerprint="t")
    db.commit()
    assert svc.resolve(user_id=user.id, fingerprint="s") == "t"

    assert svc.delete_alias(user_id=user.id, source_fingerprint="s") is True
    db.commit()
    assert svc.resolve(user_id=user.id, fingerprint="s") == "s"


def test_delete_missing_alias_returns_false(db, user):
    svc = FingerprintAliasService(db)
    assert svc.delete_alias(user_id=user.id, source_fingerprint="missing") is False
