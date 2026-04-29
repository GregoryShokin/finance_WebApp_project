"""Phase 6.2 + 6.5: end-to-end moderation pipeline on synthetic inputs.

Flow:
  synthetic rows → normalizer_v2 (Phase 1) → ImportClusterService (Phase 3)
                 → ImportModeratorService with fake LLM provider (Phase 4)
                 → assert each stage's invariants.

**Why synthetic, not golden**: golden raw-statements are still PII-gated
(pending raw in fixtures/statements/raw/). Synthetic rows exercise the
integration points without leaking real data.

**Honest-warning coverage (6.5)**: a cluster in the gray zone (<0.7) must
surface the LLM's follow_up_question rather than silently promote the
guess. This test asserts the full chain preserves the field end-to-end.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.services.import_cluster_service import Cluster, ImportClusterService
from app.services.import_moderator_service import (
    ClusterHypothesis,
    ImportModeratorService,
    ModerationContext,
)
from app.services.import_normalizer_v2 import (
    extract_tokens,
    fingerprint,
    normalize_skeleton,
)
from app.services.llm.base import LLMResult


class _FakeProvider:
    """Minimal fake LLMProvider that returns canned hypotheses.

    `responses` is a dict keyed by a substring of the user prompt — letting
    tests tailor the hypothesis per cluster.
    """

    def __init__(
        self,
        responses: dict[str, ClusterHypothesis] | None = None,
        default: ClusterHypothesis | None = None,
    ):
        self.responses = responses or {}
        self.default = default
        self.calls: list[dict] = []

    @property
    def is_enabled(self) -> bool:
        return True

    @property
    def model_id(self) -> str:
        return "fake-model"

    def generate_structured(self, *, system, user, schema, max_tokens=1024, cache_key=None):
        self.calls.append({"system": system, "user": user, "cache_key": cache_key})
        for needle, hypothesis in self.responses.items():
            if needle in user:
                return LLMResult(parsed=hypothesis, input_tokens=50, output_tokens=20)
        if self.default:
            return LLMResult(parsed=self.default, input_tokens=30, output_tokens=10)
        return None


def _row(row_id: int, description: str, direction: str, amount: str, bank: str = "tinkoff"):
    """Produce a fake ImportRow-like object carrying v2-normalized data."""
    tokens = extract_tokens(description)
    skeleton = normalize_skeleton(description, tokens)
    fp = fingerprint(
        bank=bank,
        account_id=1,
        direction=direction,
        skeleton=skeleton,
        contract=tokens.contract,
    )
    row = MagicMock()
    row.id = row_id
    row.normalized_data = {
        "fingerprint": fp,
        "skeleton": skeleton,
        "direction": direction,
        "amount": amount,
        "bank_code": bank,
        "tokens": {
            "phone": tokens.phone,
            "contract": tokens.contract,
            "iban": tokens.iban,
            "card": tokens.card,
            "person_hash": "PRESENT" if tokens.person_name else None,
            "counterparty_org": tokens.counterparty_org,
        },
    }
    row.normalized_data_json = row.normalized_data
    return row


def _make_cluster_svc(rows):
    svc = object.__new__(ImportClusterService)
    svc.db = MagicMock()
    svc.import_repo = MagicMock()
    svc.import_repo.get_rows.return_value = rows
    svc.rule_repo = MagicMock()
    svc.rule_repo.get_active_rule_by_identifier.return_value = None
    svc.rule_repo.get_active_rule_by_bank.return_value = None
    svc.rule_repo.get_active_legacy_rule.return_value = None
    # Additional service mocks required by build_clusters (added in later phases).
    svc.account_repo = MagicMock()
    svc.account_repo.get_by_id_and_user.return_value = None
    svc.category_repo = MagicMock()
    svc.category_repo.list.return_value = []
    from types import SimpleNamespace
    svc.bank_mechanics = MagicMock()
    svc.bank_mechanics.apply.return_value = SimpleNamespace(
        operation_type=None, category_name=None, label=None,
        cross_session_warning=None, confidence_boost=0.0,
        suggest_exclude=False, resolved_target_account_id=None,
    )
    svc.global_patterns = MagicMock()
    svc.global_patterns.get_matching_pattern.return_value = None
    svc.counterparty_fp_service = MagicMock()
    svc.counterparty_fp_service.resolve_many.return_value = {}
    svc.counterparty_id_service = MagicMock()
    svc.counterparty_id_service.resolve_many.return_value = {}
    return svc


def _session(user_id=1, session_id=10):
    s = MagicMock()
    s.id = session_id
    s.user_id = user_id
    return s


# ---------------------------------------------------------------------------
# 6.2: End-to-end happy path
# ---------------------------------------------------------------------------


class TestE2EHappyPath:
    def test_three_similar_rows_form_one_cluster_and_get_hypothesis(self):
        rows = [
            _row(1, "ПЯТЕРОЧКА МАГАЗИН ПРОДУКТЫ", "expense", "500.00"),
            _row(2, "ПЯТЕРОЧКА МАГАЗИН ПРОДУКТЫ", "expense", "320.00"),
            _row(3, "ПЯТЕРОЧКА МАГАЗИН ПРОДУКТЫ", "expense", "180.00"),
        ]
        # They must cluster together (same skeleton, bank, direction).
        cluster_svc = _make_cluster_svc(rows)
        clusters = cluster_svc.build_clusters(_session())
        assert len(clusters) == 1
        assert clusters[0].count == 3
        assert clusters[0].total_amount == Decimal("1000.00")

        # Feed the cluster to the moderator with a canned 0.93 hypothesis.
        hypothesis = ClusterHypothesis(
            operation_type="regular",
            direction="expense",
            predicted_category_id=10,
            confidence=0.93,
            reasoning="Пятёрочка — продуктовый магазин",
        )
        provider = _FakeProvider(responses={"пятерочка": hypothesis})
        moderator = ImportModeratorService(db=MagicMock(), provider=provider)
        result = moderator.moderate_cluster(
            clusters[0],
            ModerationContext(
                user_id=1,
                categories=[MagicMock(id=10, name="Еда", kind="expense")],
                active_rule_snippets=[],
            ),
        )
        assert result is not None
        assert result.confidence == pytest.approx(0.93)
        assert result.predicted_category_id == 10

    def test_rows_with_different_contracts_form_separate_clusters(self):
        rows = [
            _row(1, "Оплата по договору № 12345 от Иванов", "expense", "1000"),
            _row(2, "Оплата по договору № 12345 от Иванов", "expense", "1000"),
            _row(3, "Оплата по договору № 99999 от Петров", "expense", "1000"),
        ]
        cluster_svc = _make_cluster_svc(rows)
        clusters = cluster_svc.build_clusters(_session())
        # Contract numbers are part of the fingerprint → different clusters.
        assert len(clusters) == 2
        counts = sorted(c.count for c in clusters)
        assert counts == [1, 2]


# ---------------------------------------------------------------------------
# 6.5: Honest-warning — gray-zone clusters surface follow_up_question
# ---------------------------------------------------------------------------


class TestHonestWarning:
    def test_low_confidence_preserves_follow_up_question(self):
        """When LLM confidence < 0.7 and it supplies a follow_up_question,
        the moderator must propagate that field intact (no silent promotion)."""
        rows = [_row(1, "Неизвестное поступление", "income", "5000")]
        cluster_svc = _make_cluster_svc(rows)
        clusters = cluster_svc.build_clusters(_session())

        gray_zone_hypothesis = ClusterHypothesis(
            operation_type="regular",
            direction="income",
            predicted_category_id=None,
            confidence=0.45,
            reasoning="Недостаточно информации",
            follow_up_question="Это зарплата или разовая премия?",
        )
        provider = _FakeProvider(default=gray_zone_hypothesis)
        moderator = ImportModeratorService(db=MagicMock(), provider=provider)
        result = moderator.moderate_cluster(
            clusters[0],
            ModerationContext(user_id=1, categories=[], active_rule_snippets=[]),
        )
        assert result is not None
        assert result.confidence < 0.7
        assert result.follow_up_question == "Это зарплата или разовая премия?"
        assert result.predicted_category_id is None  # Never silently guesses

    def test_no_hallucinated_category_when_none_valid(self):
        """If the LLM hallucinates a category_id not in the user's list,
        the moderator nulls it but keeps the rest (honest warning path)."""
        rows = [_row(1, "Перевод другу", "expense", "1000")]
        cluster_svc = _make_cluster_svc(rows)
        clusters = cluster_svc.build_clusters(_session())

        hallucinated = ClusterHypothesis(
            operation_type="transfer",
            direction="expense",
            predicted_category_id=99999,  # doesn't belong to user
            confidence=0.85,
            reasoning="Похоже на перевод",
        )
        provider = _FakeProvider(default=hallucinated)
        moderator = ImportModeratorService(db=MagicMock(), provider=provider)
        result = moderator.moderate_cluster(
            clusters[0],
            ModerationContext(
                user_id=1,
                categories=[MagicMock(id=10, name="Еда", kind="expense")],
                active_rule_snippets=[],
            ),
        )
        assert result is not None
        # Category nulled (safer than guessing), rest preserved.
        assert result.predicted_category_id is None
        assert result.confidence == pytest.approx(0.85)
        assert result.operation_type == "transfer"


# ---------------------------------------------------------------------------
# Token usage propagation (6.1 wiring check)
# ---------------------------------------------------------------------------


class TestTokenUsagePropagation:
    def test_moderate_cluster_with_usage_returns_llm_result(self):
        rows = [_row(1, "Магазин Пятерочка", "expense", "500")]
        cluster_svc = _make_cluster_svc(rows)
        clusters = cluster_svc.build_clusters(_session())

        hypothesis = ClusterHypothesis(
            operation_type="regular",
            direction="expense",
            predicted_category_id=None,
            confidence=0.8,
            reasoning="ok",
        )
        provider = _FakeProvider(default=hypothesis)
        moderator = ImportModeratorService(db=MagicMock(), provider=provider)
        outcome = moderator.moderate_cluster_with_usage(
            clusters[0],
            ModerationContext(user_id=1, categories=[], active_rule_snippets=[]),
        )
        assert outcome is not None
        hypothesis_out, llm_result = outcome
        assert hypothesis_out.reasoning == "ok"
        assert llm_result.input_tokens == 30
        assert llm_result.output_tokens == 10
