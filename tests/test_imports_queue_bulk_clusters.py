"""Tests for cross-session bulk-clusters endpoint (v1.23).

`GET /imports/queue/bulk-clusters` runs the same fingerprint/brand/counterparty
aggregation as the per-session endpoint, but across every preview-ready session
of the user. The non-trivial property: brand-level groups now span sessions,
so «Магнит ×1 в Сбере + Магнит ×1 в Т-Банке» rolls into one BrandCluster
crossing the MIN_FINGERPRINT_COUNT_FOR_BRAND threshold.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.account import Account
from app.models.bank import Bank
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.services.import_service import ImportService


def _mk_bank(db, *, code: str) -> Bank:
    b = Bank(name=code.title(), code=code, is_popular=False)
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def _mk_account(db, *, user_id: int, bank: Bank, name: str) -> Account:
    a = Account(
        user_id=user_id,
        bank_id=bank.id,
        name=name,
        currency="RUB",
        balance=Decimal("0"),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _mk_session(
    db, *, user_id: int, account_id: int, status: str = "preview_ready",
    filename: str = "t.csv",
) -> ImportSession:
    s = ImportSession(
        user_id=user_id,
        filename=filename,
        source_type="csv",
        status=status,
        account_id=account_id,
        file_content="",
        detected_columns=[],
        parse_settings={},
        mapping_json={},
        summary_json={},
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _mk_row(
    db,
    *,
    session_id: int,
    account_id: int,
    row_index: int,
    skeleton: str,
    direction: str = "expense",
    bank_code: str = "test",
    amount: str = "100.00",
) -> ImportRow:
    # Stable fingerprint per (account_id, skeleton, direction) — identical
    # to what import_normalizer_v2.fingerprint() builds at import time.
    import hashlib
    payload = f"{bank_code}|{account_id}|{direction}|{skeleton}".encode("utf-8")
    fp = hashlib.sha256(payload).hexdigest()[:16]
    r = ImportRow(
        session_id=session_id,
        row_index=row_index,
        raw_data_json={"date": "2026-01-15"},
        normalized_data_json={
            "amount": amount,
            "direction": direction,
            "transaction_date": "2026-01-15T12:00:00+00:00",
            "skeleton": skeleton,
            "fingerprint": fp,
            "bank_code": bank_code,
            "tokens": {},
        },
        status="ready",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


# ──────────────────────────────────────────────────────────────────────


def test_brand_cluster_spans_sessions_when_two_banks_have_same_brand(db, user):
    """Cross-session brand aggregation — the headline feature of v1.23.

    Two banks (different sessions, different accounts → different
    fingerprints), each with 1 row of brand «pyaterochka». Single-session
    aggregation would yield two singleton fingerprint clusters and zero
    BrandClusters (MIN_FINGERPRINT_COUNT_FOR_BRAND=2 not met per-session).
    Cross-session aggregation rolls them into one BrandCluster.
    """
    sber = _mk_bank(db, code="sber")
    tbank = _mk_bank(db, code="tbank")
    sber_acc = _mk_account(db, user_id=user.id, bank=sber, name="Карта Сбер")
    tbank_acc = _mk_account(db, user_id=user.id, bank=tbank, name="Дебет Т-Банк")
    sber_session = _mk_session(db, user_id=user.id, account_id=sber_acc.id, filename="sber.csv")
    tbank_session = _mk_session(db, user_id=user.id, account_id=tbank_acc.id, filename="tbank.csv")

    # Different skeleton per bank (TT-номер in each), but same extracted brand.
    _mk_row(db, session_id=sber_session.id, account_id=sber_acc.id, row_index=1,
            skeleton="оплата в pyaterochka 14130", bank_code="sber")
    _mk_row(db, session_id=tbank_session.id, account_id=tbank_acc.id, row_index=1,
            skeleton="оплата в pyaterochka 20046", bank_code="tbank")

    payload = ImportService(db).get_queue_bulk_clusters(user_id=user.id)

    brand_clusters = payload["brand_clusters"]
    assert len(brand_clusters) == 1
    bc = brand_clusters[0]
    assert bc["brand"] == "pyaterochka"
    assert bc["count"] == 2
    assert bc["direction"] == "expense"
    # Both fingerprint cluster IDs from the two banks must be members.
    assert len(bc["fingerprint_cluster_ids"]) == 2


def test_no_brand_cluster_when_only_one_session_has_the_brand(db, user):
    """Single fingerprint with one row — nothing to aggregate. Both the
    MIN_FINGERPRINT_COUNT_FOR_BRAND=2 and MIN_BRAND_CLUSTER_SIZE=2
    thresholds protect against premature emission.
    """
    sber = _mk_bank(db, code="sber")
    sber_acc = _mk_account(db, user_id=user.id, bank=sber, name="Карта")
    s = _mk_session(db, user_id=user.id, account_id=sber_acc.id)
    _mk_row(db, session_id=s.id, account_id=sber_acc.id, row_index=1,
            skeleton="оплата в pyaterochka 14130", bank_code="sber")

    payload = ImportService(db).get_queue_bulk_clusters(user_id=user.id)
    assert payload["brand_clusters"] == []


def test_empty_queue_returns_empty_clusters(db, user):
    payload = ImportService(db).get_queue_bulk_clusters(user_id=user.id)
    assert payload == {
        "fingerprint_clusters": [],
        "brand_clusters": [],
        "counterparty_groups": [],
    }


def test_session_without_account_does_not_contribute(db, user):
    """An admit-filter-failing session must not leak its rows into the
    cross-session aggregate, even if the rows themselves are well-formed."""
    sber = _mk_bank(db, code="sber")
    sber_acc = _mk_account(db, user_id=user.id, bank=sber, name="Карта")
    eligible = _mk_session(db, user_id=user.id, account_id=sber_acc.id)
    # Session with no account — should be silently excluded.
    orphan = _mk_session(
        db, user_id=user.id, account_id=sber_acc.id, filename="orphan.csv",
    )
    orphan.account_id = None
    db.commit()

    _mk_row(db, session_id=eligible.id, account_id=sber_acc.id, row_index=1,
            skeleton="оплата в pyaterochka 14130", bank_code="sber")
    _mk_row(db, session_id=eligible.id, account_id=sber_acc.id, row_index=2,
            skeleton="оплата в pyaterochka 14130", bank_code="sber")
    # These rows would push the brand over threshold if admitted.
    _mk_row(db, session_id=orphan.id, account_id=sber_acc.id, row_index=1,
            skeleton="оплата в pyaterochka 99999", bank_code="sber")
    _mk_row(db, session_id=orphan.id, account_id=sber_acc.id, row_index=2,
            skeleton="оплата в pyaterochka 99999", bank_code="sber")

    payload = ImportService(db).get_queue_bulk_clusters(user_id=user.id)

    # Only the eligible session contributes — its single fingerprint with
    # 2 rows forms a cluster but doesn't form a brand group (need ≥2 fps).
    assert payload["brand_clusters"] == []
    fps = payload["fingerprint_clusters"]
    # Eligible session has 1 fingerprint with 2 rows.
    assert len(fps) == 1
    assert fps[0]["count"] == 2


def test_committed_session_does_not_contribute(db, user):
    """Committed session — even with rows still in normalized_data_json —
    is filtered by `list_active_sessions`, never reaching the queue."""
    sber = _mk_bank(db, code="sber")
    sber_acc = _mk_account(db, user_id=user.id, bank=sber, name="Карта")
    active = _mk_session(db, user_id=user.id, account_id=sber_acc.id)
    committed = _mk_session(
        db, user_id=user.id, account_id=sber_acc.id,
        status="committed", filename="old.csv",
    )

    _mk_row(db, session_id=active.id, account_id=sber_acc.id, row_index=1,
            skeleton="оплата в pyaterochka 14130", bank_code="sber")
    _mk_row(db, session_id=active.id, account_id=sber_acc.id, row_index=2,
            skeleton="оплата в pyaterochka 14130", bank_code="sber")
    _mk_row(db, session_id=committed.id, account_id=sber_acc.id, row_index=1,
            skeleton="оплата в magnit 99", bank_code="sber")

    payload = ImportService(db).get_queue_bulk_clusters(user_id=user.id)

    # No magnit anywhere in the queue.
    assert all(
        b["brand"] != "magnit" for b in payload["brand_clusters"]
    )
    # No row from committed session in any fingerprint cluster.
    committed_row_ids = {
        r.id for r in db.query(ImportRow).filter(ImportRow.session_id == committed.id)
    }
    leaked = [
        rid for c in payload["fingerprint_clusters"]
        for rid in c["row_ids"]
        if rid in committed_row_ids
    ]
    assert leaked == []
