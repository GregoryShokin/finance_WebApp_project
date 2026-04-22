"""Phase 3.1–3.4: clustering + rule matching + confidence tests.

Covers fingerprint grouping, cluster aggregates, rule priority
(identifier > bank > legacy > none), and confidence calculation.

All tests use mocks — no real DB required.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.import_cluster_service import (
    Cluster,
    ImportClusterService,
    _CONF_BANK_RULE_ACTIVE,
    _CONF_EXACT_RULE_ACTIVE,
    _CONF_LEGACY_RULE_ACTIVE,
    _CONF_SINGLE_ROW_DRAG,
    _ID_MATCH_ABSENT,
    _ID_MATCH_FACTORS,
    _ID_MATCH_MATCHED,
    _ID_MATCH_UNMATCHED,
)


def _row(
    row_id: int,
    fingerprint: str,
    direction: str = "expense",
    skeleton: str = "",
    amount: str = "100.00",
    tokens: dict | None = None,
    bank_code: str | None = None,
) -> MagicMock:
    row = MagicMock()
    row.id = row_id
    row.normalized_data = {
        "fingerprint": fingerprint,
        "direction": direction,
        "skeleton": skeleton,
        "amount": amount,
        "bank_code": bank_code,
        "tokens": tokens or {},
    }
    row.normalized_data_json = row.normalized_data
    return row


def _make_svc(rows: list, rule_by_identifier=None, rule_by_bank=None, rule_by_desc=None) -> ImportClusterService:
    svc = object.__new__(ImportClusterService)
    svc.db = MagicMock()
    svc.import_repo = MagicMock()
    svc.import_repo.get_rows.return_value = rows
    svc.rule_repo = MagicMock()
    svc.rule_repo.get_active_rule_by_identifier.return_value = rule_by_identifier
    svc.rule_repo.get_active_rule_by_bank.return_value = rule_by_bank
    svc.rule_repo.get_active_legacy_rule.return_value = rule_by_desc
    return svc


def _session(user_id: int = 1, session_id: int = 10) -> MagicMock:
    s = MagicMock()
    s.id = session_id
    s.user_id = user_id
    return s


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

class TestGrouping:
    def test_rows_with_same_fingerprint_form_one_cluster(self):
        rows = [
            _row(1, "fp-a", amount="100"),
            _row(2, "fp-a", amount="200"),
            _row(3, "fp-b", amount="50"),
        ]
        svc = _make_svc(rows)
        clusters = svc.build_clusters(_session())
        assert len(clusters) == 2
        fps = {c.fingerprint: c for c in clusters}
        assert fps["fp-a"].count == 2
        assert fps["fp-a"].total_amount == Decimal("300")
        assert fps["fp-b"].count == 1
        assert fps["fp-b"].total_amount == Decimal("50")

    def test_rows_without_fingerprint_become_singleton_clusters(self):
        row_a = _row(1, "")
        row_a.normalized_data = {}
        row_a.normalized_data_json = {}
        svc = _make_svc([row_a])
        clusters = svc.build_clusters(_session())
        assert len(clusters) == 1
        assert clusters[0].fingerprint == "no-fp:1"
        assert clusters[0].count == 1

    def test_example_row_ids_capped_at_three(self):
        rows = [_row(i, "fp-a", amount="10") for i in range(1, 6)]
        svc = _make_svc(rows)
        clusters = svc.build_clusters(_session())
        assert len(clusters) == 1
        assert len(clusters[0].example_row_ids) == 3
        assert clusters[0].count == 5


# ---------------------------------------------------------------------------
# Rule matching priority
# ---------------------------------------------------------------------------

class TestRulePriority:
    def _rule(self, id: int = 1, category_id: int = 100, confirms: int = 5, rejections: int = 0) -> MagicMock:
        r = MagicMock()
        r.id = id
        r.category_id = category_id
        r.confirms = confirms
        r.rejections = rejections
        r.is_active = True
        return r

    def test_identifier_rule_wins(self):
        rows = [_row(1, "fp-a", skeleton="магазин", tokens={"contract": "Д123"}, bank_code="tinkoff")]
        id_rule = self._rule(id=10, category_id=100)
        bank_rule = self._rule(id=20, category_id=200)
        desc_rule = self._rule(id=30, category_id=300)
        svc = _make_svc(rows, rule_by_identifier=id_rule, rule_by_bank=bank_rule, rule_by_desc=desc_rule)

        clusters = svc.build_clusters(_session())

        assert clusters[0].rule_source == "identifier"
        assert clusters[0].candidate_rule_id == 10
        assert clusters[0].candidate_category_id == 100

    def test_bank_rule_wins_when_no_identifier(self):
        # No identifier tokens on the row — should fall through to bank rule.
        rows = [_row(1, "fp-a", skeleton="магазин", bank_code="tinkoff")]
        bank_rule = self._rule(id=20, category_id=200)
        desc_rule = self._rule(id=30, category_id=300)
        svc = _make_svc(rows, rule_by_bank=bank_rule, rule_by_desc=desc_rule)

        clusters = svc.build_clusters(_session())

        assert clusters[0].rule_source == "bank"
        assert clusters[0].candidate_rule_id == 20

    def test_legacy_rule_used_when_nothing_else_matches(self):
        rows = [_row(1, "fp-a", skeleton="магазин")]  # no bank_code, no identifier
        desc_rule = self._rule(id=30, category_id=300)
        svc = _make_svc(rows, rule_by_desc=desc_rule)

        clusters = svc.build_clusters(_session())

        assert clusters[0].rule_source == "normalized_description"
        assert clusters[0].candidate_rule_id == 30

    def test_inactive_legacy_rule_not_used(self):
        # With Phase 7 trust fix, `get_active_legacy_rule` filters `is_active`
        # at the repository layer — so an inactive rule simply doesn't come
        # back. The service no longer needs a secondary `is_active` check.
        rows = [_row(1, "fp-a", skeleton="магазин")]
        svc = _make_svc(rows, rule_by_desc=None)

        clusters = svc.build_clusters(_session())
        assert clusters[0].rule_source == "none"
        assert clusters[0].candidate_rule_id is None

    def test_no_rule_gives_zero_confidence(self):
        rows = [_row(1, "fp-a")]
        svc = _make_svc(rows)
        clusters = svc.build_clusters(_session())
        assert clusters[0].rule_source == "none"
        assert clusters[0].confidence == 0.0


# ---------------------------------------------------------------------------
# Confidence calculation
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_singleton_cluster_has_evidence_drag(self):
        confirms = 10
        conf = ImportClusterService._compute_confidence(
            base=_CONF_EXACT_RULE_ACTIVE, confirms=confirms, rejections=0, cluster_size=1
        )
        # Expected: base × 1.0 (no errors) × (1 - drag)
        expected = _CONF_EXACT_RULE_ACTIVE * (1.0 - _CONF_SINGLE_ROW_DRAG)
        assert conf == pytest.approx(expected)

    def test_multi_row_cluster_no_evidence_drag(self):
        conf = ImportClusterService._compute_confidence(
            base=_CONF_EXACT_RULE_ACTIVE, confirms=10, rejections=0, cluster_size=3
        )
        assert conf == pytest.approx(_CONF_EXACT_RULE_ACTIVE)

    def test_rejection_ratio_drags_confidence_down(self):
        # 5 confirms, 5 rejections → error_ratio_factor = 0.5
        conf = ImportClusterService._compute_confidence(
            base=_CONF_EXACT_RULE_ACTIVE, confirms=5, rejections=5, cluster_size=3
        )
        assert conf == pytest.approx(_CONF_EXACT_RULE_ACTIVE * 0.5)

    def test_no_history_uses_full_base(self):
        conf = ImportClusterService._compute_confidence(
            base=_CONF_BANK_RULE_ACTIVE, confirms=0, rejections=0, cluster_size=3
        )
        assert conf == pytest.approx(_CONF_BANK_RULE_ACTIVE)

    def test_all_rejections_gives_zero(self):
        conf = ImportClusterService._compute_confidence(
            base=_CONF_EXACT_RULE_ACTIVE, confirms=0, rejections=3, cluster_size=3
        )
        assert conf == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

class TestClusterSorting:
    def _rule(self, id: int, cat: int) -> MagicMock:
        r = MagicMock()
        r.id = id
        r.category_id = cat
        r.confirms = 5
        r.rejections = 0
        r.is_active = True
        return r

    def test_clusters_sorted_by_confidence_descending(self):
        # fp-a: will match identifier rule → high confidence
        # fp-b: no match → confidence 0
        rows = [
            _row(1, "fp-b"),
            _row(2, "fp-a", skeleton="магазин", tokens={"contract": "Д1"}),
            _row(3, "fp-a", skeleton="магазин", tokens={"contract": "Д1"}),
        ]
        svc = _make_svc(rows, rule_by_identifier=self._rule(10, 100))
        clusters = svc.build_clusters(_session())
        assert [c.fingerprint for c in clusters] == ["fp-a", "fp-b"]


class TestIdentifierAwareTrust:
    """Phase 7 trust fix: identifier-match factor must drag confidence when
    the cluster carries an identifier the rule has never seen confirmed.

    This is the regression guard for the «перевод по договору ДГ-99999
    получил категорию от ДГ-12345» class of bugs.
    """

    def _rule(self, id=10, category_id=100, confirms=14, rejections=0, identifier_value=None):
        r = MagicMock()
        r.id = id
        r.category_id = category_id
        r.confirms = confirms
        r.rejections = rejections
        r.is_active = True
        r.identifier_value = identifier_value
        return r

    def test_matched_identifier_keeps_full_confidence(self):
        """Same identifier as the rule was trained on → full trust.
        A rule with 14 confirms and 0 rejections lands in the proven tier
        (base 0.99, singleton drag skipped), so confidence = 0.99.
        """
        rows = [_row(1, "fp-a", skeleton="перевод", tokens={"contract": "ДГ-12345"})]
        rule = self._rule(identifier_value="ДГ-12345")  # default confirms=14
        svc = _make_svc(rows, rule_by_identifier=rule)
        clusters = svc.build_clusters(_session())
        # Proven tier base 0.99, no rejections, matched, no singleton drag.
        assert clusters[0].confidence == pytest.approx(0.99)
        assert clusters[0].auto_trust is True

    def test_unmatched_identifier_drops_to_red_zone(self):
        """Cluster has a NEW identifier; only a legacy rule matches by skeleton.
        Confidence must be dragged below the one-click threshold (≈0.65),
        so the card is NOT presented as ready/one-click."""
        rows = [_row(1, "fp-a", skeleton="перевод", tokens={"contract": "ДГ-99999"})]
        # Suppose user has a legacy rule for this skeleton (identifier_value=None).
        legacy_rule = self._rule(identifier_value=None, confirms=14)
        svc = _make_svc(rows, rule_by_desc=legacy_rule)
        clusters = svc.build_clusters(_session())
        # base 0.78 × error_ratio=1 × evidence=0.95 × id=0.60
        # ≈ 0.445 — hard red zone
        assert clusters[0].confidence < 0.70
        assert clusters[0].rule_source == "normalized_description"

    def test_bank_rule_with_unmatched_identifier_also_drags(self):
        """Bank-scope rule + cluster carrying a never-before-seen identifier."""
        rows = [_row(1, "fp-a", skeleton="магазин", bank_code="tinkoff", tokens={"contract": "NEW-123"})]
        # Bank rule with a different bound identifier or none — either triggers UNMATCHED.
        bank_rule = self._rule(identifier_value=None, confirms=20)
        svc = _make_svc(rows, rule_by_bank=bank_rule)
        clusters = svc.build_clusters(_session())
        # Confidence drops below full bank base (0.85)
        assert clusters[0].confidence < _CONF_BANK_RULE_ACTIVE * 0.95
        assert clusters[0].rule_source == "bank"

    def test_absent_identifier_does_not_drag(self):
        """Cluster has no identifier, rule has no identifier — pure skeleton match,
        no penalty (identifier_match = ABSENT)."""
        rows = [_row(1, "fp-a", skeleton="магазин")]  # no tokens
        legacy_rule = self._rule(identifier_value=None)
        svc = _make_svc(rows, rule_by_desc=legacy_rule)
        clusters = svc.build_clusters(_session())
        # base × error_ratio=1 × evidence=0.95 × id=1.0 (ABSENT)
        assert clusters[0].confidence == pytest.approx(_CONF_LEGACY_RULE_ACTIVE * 0.95)

    def test_unmatched_factor_is_strictly_less_than_one(self):
        """Guard against a silent regression: the UNMATCHED factor must
        meaningfully drag, otherwise the trust fix is toothless."""
        assert _ID_MATCH_FACTORS[_ID_MATCH_UNMATCHED] < 0.75
        assert _ID_MATCH_FACTORS[_ID_MATCH_MATCHED] == 1.0
        assert _ID_MATCH_FACTORS[_ID_MATCH_ABSENT] == 1.0


class TestAutoTrustBucket:
    """Two-bucket UX model: auto_trust vs attention.
    Only exact-identifier matches with proven history (confirms >= 5, 0 rejections)
    qualify for auto-trust. Everything else lands in attention.
    """

    def _rule(self, confirms=5, rejections=0, identifier_value="ID-1"):
        r = MagicMock()
        r.id = 10
        r.category_id = 100
        r.confirms = confirms
        r.rejections = rejections
        r.is_active = True
        r.identifier_value = identifier_value
        return r

    def test_exact_match_with_proven_rule_qualifies_for_auto_trust(self):
        rows = [_row(1, "fp-a", skeleton="x", tokens={"contract": "ID-1"})]
        rule = self._rule(confirms=5, rejections=0, identifier_value="ID-1")
        svc = _make_svc(rows, rule_by_identifier=rule)
        clusters = svc.build_clusters(_session())
        assert clusters[0].auto_trust is True
        assert clusters[0].confidence >= 0.99

    def test_exact_match_with_too_few_confirms_stays_in_attention(self):
        rows = [_row(1, "fp-a", skeleton="x", tokens={"contract": "ID-1"})]
        rule = self._rule(confirms=3, rejections=0, identifier_value="ID-1")
        svc = _make_svc(rows, rule_by_identifier=rule)
        clusters = svc.build_clusters(_session())
        assert clusters[0].auto_trust is False
        # still above yellow, just not proven
        assert clusters[0].confidence < 0.99

    def test_exact_match_with_any_rejection_stays_in_attention(self):
        """One rejection in the rule's history blocks auto-trust."""
        rows = [_row(1, "fp-a", skeleton="x", tokens={"contract": "ID-1"})]
        rule = self._rule(confirms=10, rejections=1, identifier_value="ID-1")
        svc = _make_svc(rows, rule_by_identifier=rule)
        clusters = svc.build_clusters(_session())
        assert clusters[0].auto_trust is False

    def test_bank_scope_rule_never_qualifies_for_auto_trust(self):
        """No matter how confident bank-scope match is, it's never auto-trust —
        because bank-scope doesn't prove identifier-level pattern."""
        rows = [_row(1, "fp-a", skeleton="x", bank_code="tinkoff")]
        rule = self._rule(confirms=100, rejections=0, identifier_value=None)
        svc = _make_svc(rows, rule_by_bank=rule)
        clusters = svc.build_clusters(_session())
        assert clusters[0].auto_trust is False

    def test_legacy_rule_never_qualifies(self):
        rows = [_row(1, "fp-a", skeleton="x")]
        rule = self._rule(confirms=100, rejections=0, identifier_value=None)
        svc = _make_svc(rows, rule_by_desc=rule)
        clusters = svc.build_clusters(_session())
        assert clusters[0].auto_trust is False

    def test_singleton_cluster_still_qualifies_when_rule_is_proven(self):
        """The drag for size=1 must not push a proven rule out of auto-trust."""
        rows = [_row(1, "fp-a", skeleton="x", tokens={"contract": "ID-1"})]
        rule = self._rule(confirms=20, rejections=0, identifier_value="ID-1")
        svc = _make_svc(rows, rule_by_identifier=rule)
        clusters = svc.build_clusters(_session())
        assert clusters[0].count == 1
        assert clusters[0].auto_trust is True


class TestClusterDictSerialization:
    def test_to_dict_has_all_keys(self):
        c = Cluster(
            fingerprint="fp-a",
            row_ids=(1, 2),
            count=2,
            total_amount=Decimal("150.00"),
            direction="expense",
            skeleton="магазин",
            identifier_key="contract",
            identifier_value="Д1",
            bank_code="tinkoff",
            example_row_ids=(1, 2),
            candidate_rule_id=10,
            candidate_category_id=100,
            rule_source="identifier",
            confidence=0.92,
        )
        d = c.to_dict()
        assert d["fingerprint"] == "fp-a"
        assert d["row_ids"] == [1, 2]
        assert d["total_amount"] == "150.00"
        assert d["rule_source"] == "identifier"
        assert d["confidence"] == 0.92
