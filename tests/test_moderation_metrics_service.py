"""Phase 6.1: moderation metrics aggregation tests.

Covers confidence-band accounting, token totals, parked-row counting, and
ratios on empty / non-moderated sessions.

Uses in-memory SQLite with the existing SQLAlchemy models — no Celery, no
external provider.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.user import User
from app.services.moderation_metrics_service import (
    CONFIDENCE_ONECLICK,
    CONFIDENCE_SILENT,
    ModerationMetricsService,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _make_user(db, user_id: int = 1) -> User:
    user = User(
        id=user_id,
        email=f"user{user_id}@example.com",
        password_hash="x",
        full_name="Test",
    )
    db.add(user)
    db.flush()
    return user


def _make_session(db, user_id: int, summary: dict) -> ImportSession:
    s = ImportSession(
        user_id=user_id,
        filename="t.csv",
        source_type="csv",
        status="committed",
        file_content="",
        detected_columns=[],
        parse_settings={},
        mapping_json={},
        summary_json=summary,
    )
    db.add(s)
    db.flush()
    return s


def _make_row(db, session_id: int, row_index: int, normalized: dict, status: str = "committed") -> ImportRow:
    row = ImportRow(
        session_id=session_id,
        row_index=row_index,
        raw_data_json={},
        normalized_data_json=normalized,
        status=status,
    )
    db.add(row)
    db.flush()
    return row


class TestMetrics:
    def test_empty_user_returns_zeros(self, db):
        _make_user(db, user_id=1)
        db.commit()
        metrics = ModerationMetricsService(db).compute_for_user(user_id=1)
        assert metrics.sessions_total == 0
        assert metrics.clusters_total == 0
        assert metrics.silent_share == 0.0
        assert metrics.avg_tokens_per_session == 0.0

    def test_confidence_bands_classified_correctly(self, db):
        user = _make_user(db, user_id=1)
        session = _make_session(
            db,
            user_id=user.id,
            summary={"moderation": {"status": "ready", "tokens": {"input_tokens": 100, "output_tokens": 50, "llm_calls": 3}}},
        )
        # Silent (≥ 0.9)
        _make_row(db, session.id, 0, {"moderation": {"status": "ready", "hypothesis": {"confidence": 0.95}}})
        # One-click (0.7 ≤ < 0.9)
        _make_row(db, session.id, 1, {"moderation": {"status": "ready", "hypothesis": {"confidence": 0.80}}})
        _make_row(db, session.id, 2, {"moderation": {"status": "ready", "hypothesis": {"confidence": 0.70}}})
        # Follow-up (< 0.7)
        _make_row(db, session.id, 3, {"moderation": {"status": "ready", "hypothesis": {"confidence": 0.50}}})
        # Skipped (no hypothesis)
        _make_row(db, session.id, 4, {"moderation": {"status": "skipped"}})
        db.commit()

        m = ModerationMetricsService(db).compute_for_user(user_id=user.id)
        assert m.clusters_silent == 1
        assert m.clusters_oneclick == 2
        assert m.clusters_followup == 1
        assert m.clusters_skipped == 1
        assert m.clusters_total == 4  # excludes skipped
        assert m.silent_share == pytest.approx(0.25)
        assert m.oneclick_share == pytest.approx(0.5)
        assert m.followup_share == pytest.approx(0.25)

    def test_confidence_average_excludes_skipped(self, db):
        user = _make_user(db, user_id=1)
        session = _make_session(db, user_id=user.id, summary={"moderation": {"status": "ready"}})
        _make_row(db, session.id, 0, {"moderation": {"status": "ready", "hypothesis": {"confidence": 0.9}}})
        _make_row(db, session.id, 1, {"moderation": {"status": "ready", "hypothesis": {"confidence": 0.5}}})
        _make_row(db, session.id, 2, {"moderation": {"status": "skipped"}})
        db.commit()

        m = ModerationMetricsService(db).compute_for_user(user_id=user.id)
        assert m.confidence_avg == pytest.approx(0.7)

    def test_token_totals_accumulate_across_sessions(self, db):
        user = _make_user(db, user_id=1)
        _make_session(db, user_id=user.id, summary={
            "moderation": {"status": "ready", "tokens": {"input_tokens": 100, "output_tokens": 50, "llm_calls": 2}},
        })
        _make_session(db, user_id=user.id, summary={
            "moderation": {"status": "ready", "tokens": {"input_tokens": 200, "output_tokens": 80, "llm_calls": 3}},
        })
        db.commit()

        m = ModerationMetricsService(db).compute_for_user(user_id=user.id)
        assert m.input_tokens_total == 300
        assert m.output_tokens_total == 80 + 50
        assert m.llm_calls_total == 5
        assert m.sessions_with_moderation == 2
        assert m.avg_tokens_per_session == pytest.approx((300 + 130) / 2)

    def test_parked_rows_counted(self, db):
        user = _make_user(db, user_id=1)
        session = _make_session(db, user_id=user.id, summary={})
        _make_row(db, session.id, 0, {}, status="parked")
        _make_row(db, session.id, 1, {}, status="parked")
        _make_row(db, session.id, 2, {}, status="ready")
        db.commit()

        m = ModerationMetricsService(db).compute_for_user(user_id=user.id)
        assert m.parked_rows_total == 2

    def test_sessions_without_moderation_ignored_in_token_avg(self, db):
        user = _make_user(db, user_id=1)
        # No `moderation` key at all in summary_json — should NOT drive the denominator.
        _make_session(db, user_id=user.id, summary={})
        _make_session(db, user_id=user.id, summary={
            "moderation": {"status": "ready", "tokens": {"input_tokens": 100, "output_tokens": 20, "llm_calls": 1}},
        })
        db.commit()

        m = ModerationMetricsService(db).compute_for_user(user_id=user.id)
        assert m.sessions_with_moderation == 1
        assert m.avg_tokens_per_session == pytest.approx(120)

    def test_confidence_bands_use_correct_thresholds(self):
        # Sanity check that the band constants match the plan: ≥0.9 silent, ≥0.7 one-click.
        assert CONFIDENCE_SILENT == 0.9
        assert CONFIDENCE_ONECLICK == 0.7
