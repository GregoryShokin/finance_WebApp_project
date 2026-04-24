"""Unit tests for CounterpartyFingerprintService (Phase 3).

Covers:
  * bind — new + idempotent upsert (confirms increments)
  * resolve — hit / miss / per-user isolation
  * resolve_many — batch path
  * bind_many — a single counterparty choice binds every cluster member
  * unbind — removes the binding
"""
from __future__ import annotations

import pytest
from decimal import Decimal

from app.models.counterparty_fingerprint import CounterpartyFingerprint
from app.services.counterparty_fingerprint_service import (
    CounterpartyFingerprintService,
)


@pytest.fixture
def counterparty(db, user):
    from app.models.counterparty import Counterparty
    cp = Counterparty(user_id=user.id, name="Вкусная точка")
    db.add(cp)
    db.commit()
    db.refresh(cp)
    return cp


@pytest.fixture
def other_counterparty(db, user):
    from app.models.counterparty import Counterparty
    cp = Counterparty(user_id=user.id, name="Пятёрочка")
    db.add(cp)
    db.commit()
    db.refresh(cp)
    return cp


# ───────────────────────────────────────────────────────────────────
# resolve()
# ───────────────────────────────────────────────────────────────────


def test_resolve_unmapped_fingerprint_returns_none(db, user):
    svc = CounterpartyFingerprintService(db)
    assert svc.resolve(user_id=user.id, fingerprint="missing") is None


def test_resolve_after_bind_returns_counterparty_id(db, user, counterparty):
    svc = CounterpartyFingerprintService(db)
    svc.bind(user_id=user.id, fingerprint="fp1", counterparty_id=counterparty.id)
    db.commit()
    assert svc.resolve(user_id=user.id, fingerprint="fp1") == counterparty.id


def test_resolve_is_per_user(db, user, counterparty):
    from app.models.user import User
    other = User(email="other@example.com", password_hash="x", is_active=True)
    db.add(other)
    db.commit()
    db.refresh(other)

    svc = CounterpartyFingerprintService(db)
    svc.bind(user_id=user.id, fingerprint="fp1", counterparty_id=counterparty.id)
    db.commit()
    # Other user can't see our binding.
    assert svc.resolve(user_id=other.id, fingerprint="fp1") is None


# ───────────────────────────────────────────────────────────────────
# bind() / upsert semantics
# ───────────────────────────────────────────────────────────────────


def test_bind_is_idempotent_and_counts_confirms(db, user, counterparty):
    svc = CounterpartyFingerprintService(db)
    svc.bind(user_id=user.id, fingerprint="fp1", counterparty_id=counterparty.id)
    db.commit()
    b1 = db.query(CounterpartyFingerprint).filter_by(
        user_id=user.id, fingerprint="fp1"
    ).one()
    assert b1.confirms == 1

    # Second bind for the same (user, fp, cp) increments confirms.
    svc.bind(user_id=user.id, fingerprint="fp1", counterparty_id=counterparty.id)
    db.commit()
    b2 = db.query(CounterpartyFingerprint).filter_by(
        user_id=user.id, fingerprint="fp1"
    ).one()
    assert b2.id == b1.id
    assert b2.confirms == 2


def test_bind_rewrites_counterparty_on_reassignment(
    db, user, counterparty, other_counterparty
):
    """If the user reassigns a fingerprint to a different counterparty, the
    binding's counterparty_id is overwritten (their latest choice wins)."""
    svc = CounterpartyFingerprintService(db)
    svc.bind(user_id=user.id, fingerprint="fp1", counterparty_id=counterparty.id)
    db.commit()

    svc.bind(user_id=user.id, fingerprint="fp1", counterparty_id=other_counterparty.id)
    db.commit()

    binding = db.query(CounterpartyFingerprint).filter_by(
        user_id=user.id, fingerprint="fp1"
    ).one()
    assert binding.counterparty_id == other_counterparty.id


def test_bind_empty_fingerprint_rejected(db, user, counterparty):
    svc = CounterpartyFingerprintService(db)
    with pytest.raises(ValueError):
        svc.bind(user_id=user.id, fingerprint="", counterparty_id=counterparty.id)


# ───────────────────────────────────────────────────────────────────
# resolve_many()
# ───────────────────────────────────────────────────────────────────


def test_resolve_many_returns_only_mapped_fingerprints(db, user, counterparty):
    svc = CounterpartyFingerprintService(db)
    svc.bind(user_id=user.id, fingerprint="fp1", counterparty_id=counterparty.id)
    svc.bind(user_id=user.id, fingerprint="fp2", counterparty_id=counterparty.id)
    db.commit()
    out = svc.resolve_many(user_id=user.id, fingerprints=["fp1", "fp2", "missing"])
    assert out == {"fp1": counterparty.id, "fp2": counterparty.id}


def test_resolve_many_empty_input(db, user):
    svc = CounterpartyFingerprintService(db)
    assert svc.resolve_many(user_id=user.id, fingerprints=[]) == {}


# ───────────────────────────────────────────────────────────────────
# bind_many() — the bulk-apply path
# ───────────────────────────────────────────────────────────────────


def test_bind_many_binds_every_unique_fingerprint(db, user, counterparty):
    """A single user choice at bulk-apply binds ALL fingerprints in the cluster
    to the same counterparty. This is the core invariant of Phase 3 — a brand
    spread across 5 distinct fingerprints collapses under one counterparty
    after a single confirmation."""
    svc = CounterpartyFingerprintService(db)
    count = svc.bind_many(
        user_id=user.id,
        fingerprints=["fp1", "fp2", "fp3", "fp2", ""],  # duplicates + empty
        counterparty_id=counterparty.id,
    )
    db.commit()
    assert count == 3  # empty + duplicate ignored
    for fp in ("fp1", "fp2", "fp3"):
        assert svc.resolve(user_id=user.id, fingerprint=fp) == counterparty.id


# ───────────────────────────────────────────────────────────────────
# unbind()
# ───────────────────────────────────────────────────────────────────


def test_unbind_removes_the_binding(db, user, counterparty):
    svc = CounterpartyFingerprintService(db)
    svc.bind(user_id=user.id, fingerprint="fp1", counterparty_id=counterparty.id)
    db.commit()
    assert svc.unbind(user_id=user.id, fingerprint="fp1") is True
    db.commit()
    assert svc.resolve(user_id=user.id, fingerprint="fp1") is None


def test_unbind_missing_returns_false(db, user):
    svc = CounterpartyFingerprintService(db)
    assert svc.unbind(user_id=user.id, fingerprint="missing") is False
