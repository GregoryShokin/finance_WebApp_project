"""Tests for brand-level aggregation in ImportClusterService.

Focused on the pure `_group_by_brand` staticmethod so we don't have to mock
the full rule/account/bank_mechanics stack. End-to-end `build_bulk_clusters`
coverage belongs with the rest of the cluster-service suite once its fixture
is restored.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from app.services.import_cluster_service import (
    BrandCluster,
    Cluster,
    ImportClusterService,
    MIN_BRAND_CLUSTER_SIZE,
    MIN_FINGERPRINT_COUNT_FOR_BRAND,
)


def _cluster(
    fingerprint: str,
    count: int,
    skeleton: str,
    direction: str = "expense",
    total_amount: str = "100.00",
) -> Cluster:
    return Cluster(
        fingerprint=fingerprint,
        row_ids=tuple(range(count)),
        count=count,
        total_amount=Decimal(total_amount),
        direction=direction,
        skeleton=skeleton,
        identifier_key=None,
        identifier_value=None,
        bank_code="tbank",
        example_row_ids=(0, 1, 2),
        candidate_rule_id=None,
        candidate_category_id=None,
        rule_source="none",
        confidence=0.0,
    )


class TestGroupByBrand:
    def test_single_fingerprint_does_not_form_brand(self) -> None:
        # Pyaterochka has only one TT here — no brand group (needs ≥2 fingerprints).
        clusters = [
            _cluster("fp-a", 92, "оплата в pyaterochka 14130 volgodonsk rus"),
        ]
        assert ImportClusterService._group_by_brand(clusters) == []

    def test_two_fingerprints_same_brand_form_group(self) -> None:
        clusters = [
            _cluster("fp-a", 92, "оплата в pyaterochka 14130 volgodonsk rus",
                     total_amount="47997.48"),
            _cluster("fp-b", 36, "оплата в pyaterochka 20046 volgodonsk rus",
                     total_amount="19338.42"),
        ]
        groups = ImportClusterService._group_by_brand(clusters)
        assert len(groups) == 1
        g = groups[0]
        assert isinstance(g, BrandCluster)
        assert g.brand == "pyaterochka"
        assert g.count == 92 + 36
        assert g.total_amount == Decimal("47997.48") + Decimal("19338.42")
        assert set(g.fingerprint_cluster_ids) == {"fp-a", "fp-b"}

    def test_expense_and_income_same_brand_do_not_merge(self) -> None:
        # "Оплата в OZON" vs "Возврат OZON" — same brand, different direction.
        # Must emit two BrandClusters, not one.
        clusters = [
            _cluster("fp-a", 20, "оплата в ozon volgodonsk rus", direction="expense"),
            _cluster("fp-b", 15, "оплата в ozon rostov rus", direction="expense"),
            _cluster("fp-c", 6, "возврат ozon moscow rus", direction="income"),
            _cluster("fp-d", 4, "возврат ozon spb rus", direction="income"),
        ]
        groups = ImportClusterService._group_by_brand(clusters)
        assert len(groups) == 2
        directions = {g.direction for g in groups}
        assert directions == {"expense", "income"}

    def test_brand_group_skipped_when_total_below_min_size(self) -> None:
        # Two fingerprints share a brand, but combined count < MIN_BRAND_CLUSTER_SIZE.
        # Even though there are ≥2 fingerprints, we don't emit a group.
        assert MIN_BRAND_CLUSTER_SIZE == 5
        clusters = [
            _cluster("fp-a", 2, "оплата в magnit mm illertaler volgodonsk rus"),
            _cluster("fp-b", 2, "оплата в magnit gm volgodonsk 1 rus"),
        ]
        assert ImportClusterService._group_by_brand(clusters) == []

    def test_brand_group_requires_at_least_two_fingerprints(self) -> None:
        # One big Magnit cluster alone (100 rows) still won't form a brand
        # group — the whole *point* of brand merging is combining multiple
        # fingerprints. If there's only one, the existing fingerprint cluster
        # already represents the brand.
        assert MIN_FINGERPRINT_COUNT_FOR_BRAND == 2
        clusters = [
            _cluster("fp-a", 100, "оплата в magnit gm volgodonsk 1 rus"),
        ]
        assert ImportClusterService._group_by_brand(clusters) == []

    def test_transfer_clusters_never_form_brand(self) -> None:
        # Even if two transfer clusters share a surface word, the brand
        # extractor returns None for skeletons containing "перевод", so no
        # brand group is emitted.
        clusters = [
            _cluster("fp-a", 6, "внешний перевод по номеру телефона <phone>"),
            _cluster("fp-b", 5, "внешний перевод по номеру телефона <phone>"),
        ]
        assert ImportClusterService._group_by_brand(clusters) == []

    def test_multiple_brands_sorted_by_size_desc(self) -> None:
        # Pyaterochka (128 rows) should come before Magnit (31 rows).
        clusters = [
            _cluster("fp-m1", 15, "оплата в magnit gm volgodonsk 1 rus"),
            _cluster("fp-m2", 9, "оплата в magnit mm tulkas rus"),
            _cluster("fp-m3", 7, "оплата в magnit mm illertaler rus"),
            _cluster("fp-p1", 92, "оплата в pyaterochka 14130 volgodonsk rus"),
            _cluster("fp-p2", 36, "оплата в pyaterochka 20046 volgodonsk rus"),
        ]
        groups = ImportClusterService._group_by_brand(clusters)
        assert [g.brand for g in groups] == ["pyaterochka", "magnit"]
        assert groups[0].count == 128
        assert groups[1].count == 31

    def test_clusters_with_no_extractable_brand_are_ignored(self) -> None:
        # Clusters whose skeleton yields no brand (kiosk "qsr 26033"-style)
        # are simply dropped from brand consideration — they stay visible
        # at the fingerprint level elsewhere in the pipeline.
        clusters = [
            _cluster("fp-a", 11, "оплата в qsr 26033 volgodonsk rus"),
            _cluster("fp-b", 8, "оплата в 26033 mop sbp 0387"),
        ]
        assert ImportClusterService._group_by_brand(clusters) == []


# ---------------------------------------------------------------------------
# build_bulk_clusters filters: committed rows + transfer-like skeleton
# (regression fix after cluster "Внутренний перевод на договор" leaked into UI)
# ---------------------------------------------------------------------------


def _make_svc_with_rows(row_objects: list) -> ImportClusterService:
    from unittest.mock import MagicMock
    svc = object.__new__(ImportClusterService)
    svc.db = MagicMock()
    svc.import_repo = MagicMock()
    svc.import_repo.get_rows.return_value = row_objects
    svc.rule_repo = MagicMock()
    svc.rule_repo.get_active_rule_by_identifier.return_value = None
    svc.rule_repo.get_active_rule_by_bank.return_value = None
    svc.rule_repo.get_active_legacy_rule.return_value = None
    svc.account_repo = MagicMock()
    svc.account_repo.get_by_id_and_user.return_value = None
    svc.category_repo = MagicMock()
    svc.category_repo.list.return_value = []
    svc.bank_mechanics = MagicMock()
    svc.bank_mechanics.apply.return_value = MagicMock(
        operation_type=None, category_name=None, label=None,
        cross_session_warning=None, confidence_boost=0.0,
    )
    svc.global_patterns = MagicMock()
    svc.global_patterns.get_matching_pattern.return_value = None
    return svc


def _mk_row(row_id: int, fingerprint: str, skeleton: str, **kwargs):
    from unittest.mock import MagicMock
    row = MagicMock()
    row.id = row_id
    row.status = kwargs.pop("status", "ready")
    row.created_transaction_id = kwargs.pop("created_transaction_id", None)
    row.normalized_data = {
        "fingerprint": fingerprint,
        "direction": kwargs.pop("direction", "expense"),
        "skeleton": skeleton,
        "amount": "100.00",
        "bank_code": "tbank",
        "tokens": {},
        **kwargs,
    }
    row.normalized_data_json = row.normalized_data
    return row


class TestBuildBulkClustersFilters:
    def test_transfer_like_skeleton_cluster_is_excluded(self) -> None:
        """Regression: "Внутренний перевод на договор" cluster of 9 rows must
        not appear in bulk UI — transfers have their own pipeline."""
        rows = [
            _mk_row(i, "fp-transfer", "внутренний перевод <CONTRACT>")
            for i in range(1, 10)  # 9 rows, well above MIN_BULK_CLUSTER_SIZE
        ]
        svc = _make_svc_with_rows(rows)
        session = MagicMock(id=1, user_id=1, account_id=None, mapping_json={})
        fp_clusters, brand_clusters = svc.build_bulk_clusters(session)
        assert fp_clusters == []
        assert brand_clusters == []

    def test_committed_rows_do_not_inflate_cluster_size(self) -> None:
        """Regression: cluster that's 6 total but 4 committed + 2 non-committed
        must NOT qualify for bulk — only 2 actionable rows remain."""
        rows = [
            _mk_row(i, "fp-x", "оплата в pyaterochka 14130 volgodonsk rus",
                    status="committed", created_transaction_id=100 + i)
            for i in range(1, 5)  # 4 committed
        ] + [
            _mk_row(i + 100, "fp-x", "оплата в pyaterochka 14130 volgodonsk rus")
            for i in range(2)  # 2 non-committed
        ]
        svc = _make_svc_with_rows(rows)
        session = MagicMock(id=1, user_id=1, account_id=None, mapping_json={})
        fp_clusters, _ = svc.build_bulk_clusters(session)
        assert fp_clusters == []

    def test_rows_with_any_transfer_match_excluded(self) -> None:
        """Any row tagged by the transfer matcher — primary or secondary —
        is already assigned to a cross-account transfer pair and must not
        resurface in bulk UI. 3 regular + 3 with transfer_match → only 3
        remain → below threshold."""
        rows = [
            _mk_row(i, "fp-y", "оплата в pyaterochka 14130 volgodonsk rus")
            for i in range(1, 4)  # 3 regular
        ] + [
            _mk_row(i + 50, "fp-y", "оплата в pyaterochka 14130 volgodonsk rus",
                    transfer_match={"is_secondary": True})
            for i in range(3)
        ]
        svc = _make_svc_with_rows(rows)
        session = MagicMock(id=1, user_id=1, account_id=None, mapping_json={})
        fp_clusters, _ = svc.build_bulk_clusters(session)
        assert fp_clusters == []

    def test_primary_transfer_match_rows_also_excluded(self) -> None:
        """Primary side of a matched transfer pair (is_secondary falsy, but
        `transfer_match` is set) must also drop out — otherwise it would pull
        the pair apart when the user bulk-applies a category to it.
        Regression for the "Внутренний перевод на договор" bug where already
        matched transfers leaked back into the bulk bucket."""
        rows = [
            _mk_row(
                i,
                "fp-primary",
                "оплата в pyaterochka 14130 volgodonsk rus",
                transfer_match={"partner_row_id": 9000 + i, "is_secondary": False},
            )
            for i in range(1, 8)  # 7 rows, enough to exceed MIN_BULK_CLUSTER_SIZE
        ]
        svc = _make_svc_with_rows(rows)
        session = MagicMock(id=1, user_id=1, account_id=None, mapping_json={})
        fp_clusters, _ = svc.build_bulk_clusters(session)
        assert fp_clusters == []

    def test_transfer_cluster_with_phone_identifier_qualifies_at_low_threshold(self) -> None:
        """Transfer-like cluster backed by a concrete phone identifier should
        pass at MIN_TRANSFER_IDENTIFIER_CLUSTER_SIZE=2 — same phone repeated
        twice is already a real pattern worth one-click bulk confirm."""
        rows = [
            _mk_row(
                i,
                "fp-transfer-phone",
                "внешний перевод номеру телефона <phone>",
                tokens={"phone": "+79506366612"},
            )
            for i in range(1, 3)  # only 2 rows — below MIN_BULK_CLUSTER_SIZE
        ]
        svc = _make_svc_with_rows(rows)
        session = MagicMock(id=1, user_id=1, account_id=None, mapping_json={})
        fp_clusters, brand_clusters = svc.build_bulk_clusters(session)
        assert len(fp_clusters) == 1
        assert fp_clusters[0].count == 2
        assert fp_clusters[0].identifier_key == "phone"
        assert fp_clusters[0].identifier_value == "+79506366612"
        # Transfer clusters must never enter brand grouping.
        assert brand_clusters == []

    def test_transfer_cluster_without_identifier_still_excluded(self) -> None:
        """No identifier → the cluster would over-merge unrelated recipients.
        Drop regardless of row count."""
        rows = [
            _mk_row(i, "fp-transfer-no-id", "внешний перевод номеру телефона <phone>")
            for i in range(1, 10)  # 9 rows
        ]
        svc = _make_svc_with_rows(rows)
        session = MagicMock(id=1, user_id=1, account_id=None, mapping_json={})
        fp_clusters, _ = svc.build_bulk_clusters(session)
        assert fp_clusters == []

    def test_pure_merchant_cluster_still_qualifies(self) -> None:
        """Positive path — 6 non-committed, non-transfer rows → one cluster."""
        rows = [
            _mk_row(i, "fp-z", "оплата в pyaterochka 14130 volgodonsk rus")
            for i in range(1, 7)
        ]
        svc = _make_svc_with_rows(rows)
        session = MagicMock(id=1, user_id=1, account_id=None, mapping_json={})
        fp_clusters, _ = svc.build_bulk_clusters(session)
        assert len(fp_clusters) == 1
        assert fp_clusters[0].count == 6
