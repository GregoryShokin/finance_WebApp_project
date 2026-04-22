"""Celery task: moderate an import session with LLM (И-08 Phase 4.4).

Walks the session's clusters (Phase 3.2), calls the LLM moderator (Phase 4.2)
for those with confidence < 0.7, and writes hypotheses back onto the first
row of each cluster (`normalized_data_json["moderation"]`). Session-level
status is tracked on `ImportSession.summary_json["moderation"]`:

    {
      "status": "pending" | "running" | "ready" | "failed" | "skipped",
      "total_clusters": int,
      "processed_clusters": int,
      "started_at": iso,
      "finished_at": iso | null,
      "error": str | null,
    }

Per-cluster status is implicit:
  - `normalized_data.moderation.status = "ready"` → LLM returned a hypothesis
  - `normalized_data.moderation.status = "skipped"` → confidence already ≥ 0.7
    or provider unavailable

Retries are deliberately NOT wired: a failed session shows "failed" in UI
and the user can re-trigger moderation. Silent retries would burn tokens.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.celery_app import celery_app
from app.core.db import SessionLocal
# Eagerly load every ORM model so SQLAlchemy resolves all `relationship("X")`
# string references before the first query. Without this, the worker blows up
# with `InvalidRequestError: failed to locate a name ('User')` the moment it
# queries any table that has a relationship back to a not-yet-imported class.
import app.models  # noqa: F401

logger = logging.getLogger(__name__)

# Clusters with confidence ≥ this threshold skip LLM moderation —
# deterministic rule match is already strong enough (matches the 0.7/0.9
# gate spec in the plan).
MODERATION_CONFIDENCE_CUTOFF = 0.7


@celery_app.task(name="moderate_import_session")
def moderate_import_session(session_id: int) -> dict[str, Any]:
    """Entry point used by the API handler that kicks off moderation.

    Returns a small status dict so the Celery result backend carries
    enough information for manual inspection. The authoritative state is
    written to `ImportSession.summary_json["moderation"]`.
    """
    from app.models.category import Category
    from app.models.import_session import ImportSession
    from app.repositories.transaction_category_rule_repository import (
        TransactionCategoryRuleRepository,
    )
    from app.services.import_cluster_service import ImportClusterService
    from app.services.import_moderator_service import (
        ImportModeratorService,
        ModerationContext,
    )

    db = SessionLocal()
    try:
        session = db.query(ImportSession).filter(ImportSession.id == session_id).first()
        if session is None:
            logger.warning("moderate_import_session: session %s not found", session_id)
            return {"status": "failed", "error": "session not found"}

        _set_moderation_status(session, status="running", started_at=_now_iso())
        db.add(session)
        db.commit()

        cluster_svc = ImportClusterService(db)
        moderator = ImportModeratorService(db)

        clusters = cluster_svc.build_clusters(session)
        # Pre-moderation fast path: LLM disabled → skip everything, set status
        # to "skipped" so the UI renders the manual review directly.
        if not moderator.is_enabled:
            _set_moderation_status(
                session,
                status="skipped",
                total_clusters=len(clusters),
                processed_clusters=0,
                finished_at=_now_iso(),
            )
            db.add(session)
            db.commit()
            return {"status": "skipped", "session_id": session_id}

        context = _build_context(db, user_id=session.user_id)

        processed = 0
        for cluster in clusters:
            if cluster.confidence >= MODERATION_CONFIDENCE_CUTOFF:
                # Deterministic rules already gave a strong answer — no LLM call.
                _mark_cluster_skipped(db, cluster)
                processed += 1
                _set_moderation_status(
                    session,
                    status="running",
                    total_clusters=len(clusters),
                    processed_clusters=processed,
                )
                db.add(session)
                db.commit()
                continue

            outcome = moderator.moderate_cluster_with_usage(cluster, context)
            if outcome is not None:
                hypothesis, llm_result = outcome
                _store_cluster_hypothesis(db, cluster, hypothesis)
                _accumulate_token_usage(session, llm_result)
            else:
                _mark_cluster_skipped(db, cluster)

            processed += 1
            _set_moderation_status(
                session,
                status="running",
                total_clusters=len(clusters),
                processed_clusters=processed,
            )
            db.add(session)
            db.commit()

        _set_moderation_status(
            session,
            status="ready",
            total_clusters=len(clusters),
            processed_clusters=processed,
            finished_at=_now_iso(),
        )
        db.add(session)
        db.commit()
        return {
            "status": "ready",
            "session_id": session_id,
            "total_clusters": len(clusters),
            "processed_clusters": processed,
        }
    except Exception as exc:
        logger.exception("moderate_import_session failed for session %s", session_id)
        try:
            db.rollback()
            # Best-effort: write failure to the session summary so UI can see it.
            session = db.query(ImportSession).filter(ImportSession.id == session_id).first()
            if session is not None:
                _set_moderation_status(
                    session,
                    status="failed",
                    finished_at=_now_iso(),
                    error=str(exc)[:500],
                )
                db.add(session)
                db.commit()
        except Exception:
            logger.exception("failed to record moderation failure for session %s", session_id)
        return {"status": "failed", "error": str(exc)[:500]}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_moderation_status(session: Any, **updates: Any) -> None:
    """Merge updates into `session.summary_json['moderation']`."""
    summary = dict(session.summary_json or {})
    mod = dict(summary.get("moderation") or {})
    mod.update(updates)
    summary["moderation"] = mod
    session.summary_json = summary


def _accumulate_token_usage(session: Any, llm_result: Any) -> None:
    """Sum up per-call token counts onto `summary_json['moderation']['tokens']`.

    Phase 6.1: feeds the moderation-metrics aggregator so we can see the
    cost curve per session (and later per user / per month).
    """
    summary = dict(session.summary_json or {})
    mod = dict(summary.get("moderation") or {})
    tokens = dict(mod.get("tokens") or {})

    for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens"):
        incoming = getattr(llm_result, key, None)
        if incoming is None:
            continue
        tokens[key] = int(tokens.get(key) or 0) + int(incoming)
    tokens["llm_calls"] = int(tokens.get("llm_calls") or 0) + 1

    mod["tokens"] = tokens
    summary["moderation"] = mod
    session.summary_json = summary


def _build_context(db: Any, *, user_id: int):
    from app.models.category import Category
    from app.services.import_moderator_service import ModerationContext
    from app.repositories.transaction_category_rule_repository import (
        TransactionCategoryRuleRepository,
    )

    categories = db.query(Category).filter(Category.user_id == user_id).all()

    # Active rules — give the LLM up to N examples of what the user has
    # already decided. Only pass the pre-anonymized `normalized_description`
    # and the category name, never raw identifiers.
    rule_repo = TransactionCategoryRuleRepository(db)
    active_rules = rule_repo.list_rules(user_id=user_id, is_active=True)
    category_by_id = {c.id: c.name for c in categories}
    snippets: list[str] = []
    for rule in active_rules[:20]:
        cat_name = category_by_id.get(rule.category_id, "?")
        snippets.append(f"{rule.normalized_description} → {cat_name}")

    return ModerationContext(
        user_id=user_id,
        categories=categories,
        active_rule_snippets=snippets,
    )


def _store_cluster_hypothesis(db: Any, cluster: Any, hypothesis: Any) -> None:
    """Write the hypothesis onto the first row of the cluster."""
    from app.models.import_row import ImportRow

    if not cluster.row_ids:
        return
    anchor_row = db.query(ImportRow).filter(ImportRow.id == cluster.row_ids[0]).first()
    if anchor_row is None:
        return

    normalized = dict(anchor_row.normalized_data_json or {})
    normalized["moderation"] = {
        "status": "ready",
        "cluster_fingerprint": cluster.fingerprint,
        "cluster_row_ids": list(cluster.row_ids),
        "hypothesis": hypothesis.model_dump(),
        "generated_at": _now_iso(),
    }
    anchor_row.normalized_data_json = normalized
    db.add(anchor_row)


def _mark_cluster_skipped(db: Any, cluster: Any) -> None:
    """Mark a cluster as moderation-skipped (already confident, or LLM down)."""
    from app.models.import_row import ImportRow

    if not cluster.row_ids:
        return
    anchor_row = db.query(ImportRow).filter(ImportRow.id == cluster.row_ids[0]).first()
    if anchor_row is None:
        return

    normalized = dict(anchor_row.normalized_data_json or {})
    normalized["moderation"] = {
        "status": "skipped",
        "cluster_fingerprint": cluster.fingerprint,
        "cluster_row_ids": list(cluster.row_ids),
        "generated_at": _now_iso(),
    }
    anchor_row.normalized_data_json = normalized
    db.add(anchor_row)
