"""Moderation metrics aggregator (И-08 Phase 6.1).

Reads across the user's recent `ImportSession.summary_json["moderation"]` blocks
(written by the Celery task) and produces the distribution / token metrics
named in the plan:

  - Share of clusters with confidence ≥ 0.9 (silent-auto band).
  - Share of clusters with 0.7 ≤ confidence < 0.9 (one-click band).
  - Share of clusters with confidence < 0.7 (LLM follow-up band).
  - Average confidence after LLM moderation.
  - Average token cost per session (input/output/cache breakdown).
  - Total parked row count across sessions.

This is a read-only service — no writes, no mutations. It's the data source
for a future telemetry dashboard; the heavy lifting (actually running the
moderator, storing hypotheses) happens in `moderate_import_session.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models.import_row import ImportRow
from app.models.import_session import ImportSession


# Confidence band edges — mirror the moderator gate in the plan.
CONFIDENCE_SILENT = 0.9    # ≥ 0.9 : auto
CONFIDENCE_ONECLICK = 0.7  # ≥ 0.7 : one-click
# Anything below is "LLM follow-up" — the gray zone.


@dataclass(frozen=True)
class ModerationMetrics:
    """Snapshot of moderator behaviour across the user's sessions."""

    sessions_total: int
    sessions_with_moderation: int
    clusters_total: int
    clusters_silent: int       # confidence ≥ 0.9
    clusters_oneclick: int     # 0.7 ≤ confidence < 0.9
    clusters_followup: int     # confidence < 0.7
    clusters_skipped: int      # moderator marked skipped (no hypothesis)
    confidence_avg: float      # arithmetic mean over clusters with a hypothesis
    input_tokens_total: int
    output_tokens_total: int
    cache_read_tokens_total: int
    cache_creation_tokens_total: int
    llm_calls_total: int
    parked_rows_total: int

    @property
    def silent_share(self) -> float:
        return _safe_ratio(self.clusters_silent, self.clusters_total)

    @property
    def oneclick_share(self) -> float:
        return _safe_ratio(self.clusters_oneclick, self.clusters_total)

    @property
    def followup_share(self) -> float:
        return _safe_ratio(self.clusters_followup, self.clusters_total)

    @property
    def avg_tokens_per_session(self) -> float:
        if self.sessions_with_moderation == 0:
            return 0.0
        total = self.input_tokens_total + self.output_tokens_total
        return total / self.sessions_with_moderation

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessions_total": self.sessions_total,
            "sessions_with_moderation": self.sessions_with_moderation,
            "clusters_total": self.clusters_total,
            "clusters_silent": self.clusters_silent,
            "clusters_oneclick": self.clusters_oneclick,
            "clusters_followup": self.clusters_followup,
            "clusters_skipped": self.clusters_skipped,
            "silent_share": self.silent_share,
            "oneclick_share": self.oneclick_share,
            "followup_share": self.followup_share,
            "confidence_avg": self.confidence_avg,
            "input_tokens_total": self.input_tokens_total,
            "output_tokens_total": self.output_tokens_total,
            "cache_read_tokens_total": self.cache_read_tokens_total,
            "cache_creation_tokens_total": self.cache_creation_tokens_total,
            "llm_calls_total": self.llm_calls_total,
            "avg_tokens_per_session": self.avg_tokens_per_session,
            "parked_rows_total": self.parked_rows_total,
        }


class ModerationMetricsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def compute_for_user(self, *, user_id: int) -> ModerationMetrics:
        sessions = (
            self.db.query(ImportSession)
            .filter(ImportSession.user_id == user_id)
            .all()
        )

        sessions_total = len(sessions)
        sessions_with_moderation = 0
        clusters_silent = 0
        clusters_oneclick = 0
        clusters_followup = 0
        clusters_skipped = 0
        confidence_sum = 0.0
        confidence_count = 0

        tokens = {
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_creation": 0,
            "llm_calls": 0,
        }

        for session in sessions:
            summary = session.summary_json or {}
            moderation = summary.get("moderation") or {}
            if not moderation:
                continue
            sessions_with_moderation += 1

            # Token usage (accumulated by the Celery task per cluster).
            t = moderation.get("tokens") or {}
            tokens["input"] += int(t.get("input_tokens") or 0)
            tokens["output"] += int(t.get("output_tokens") or 0)
            tokens["cache_read"] += int(t.get("cache_read_tokens") or 0)
            tokens["cache_creation"] += int(t.get("cache_creation_tokens") or 0)
            tokens["llm_calls"] += int(t.get("llm_calls") or 0)

        # Cluster-level confidence distribution lives on ImportRow — the
        # anchor row of each cluster carries `normalized_data.moderation`.
        row_rows = (
            self.db.query(ImportRow)
            .join(ImportSession, ImportRow.session_id == ImportSession.id)
            .filter(ImportSession.user_id == user_id)
            .all()
        )
        for row in row_rows:
            normalized = row.normalized_data_json or {}
            mod_block = normalized.get("moderation")
            if not mod_block:
                continue
            status = mod_block.get("status")
            hypothesis = mod_block.get("hypothesis")
            if status == "skipped" or not hypothesis:
                clusters_skipped += 1
                continue
            try:
                confidence = float(hypothesis.get("confidence") or 0.0)
            except (TypeError, ValueError):
                continue
            confidence_sum += confidence
            confidence_count += 1
            if confidence >= CONFIDENCE_SILENT:
                clusters_silent += 1
            elif confidence >= CONFIDENCE_ONECLICK:
                clusters_oneclick += 1
            else:
                clusters_followup += 1

        parked_rows_total = (
            self.db.query(ImportRow)
            .join(ImportSession, ImportRow.session_id == ImportSession.id)
            .filter(
                ImportSession.user_id == user_id,
                ImportRow.status == "parked",
            )
            .count()
        )

        clusters_total = clusters_silent + clusters_oneclick + clusters_followup
        confidence_avg = (
            confidence_sum / confidence_count if confidence_count else 0.0
        )

        return ModerationMetrics(
            sessions_total=sessions_total,
            sessions_with_moderation=sessions_with_moderation,
            clusters_total=clusters_total,
            clusters_silent=clusters_silent,
            clusters_oneclick=clusters_oneclick,
            clusters_followup=clusters_followup,
            clusters_skipped=clusters_skipped,
            confidence_avg=confidence_avg,
            input_tokens_total=tokens["input"],
            output_tokens_total=tokens["output"],
            cache_read_tokens_total=tokens["cache_read"],
            cache_creation_tokens_total=tokens["cache_creation"],
            llm_calls_total=tokens["llm_calls"],
            parked_rows_total=parked_rows_total,
        )


def _safe_ratio(num: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    return num / denom
