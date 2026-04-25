"""PR1: rebuild_decisions_for_orphans.py — clears decisions for ImportRows
whose `applied_rule_id` points at a rule deactivated by the legacy cleanup.

Spec compliance verified:
  * §3.2: facts (skeleton/tokens/fingerprint) NOT touched.
  * §4.3: only decisions (applied_rule_id, predicted_*, category_id) reset.
  * §1.2: re-matched rows escalate to `warning`, never silently re-ready.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.category import Category
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.transaction_category_rule import TransactionCategoryRule


@pytest.fixture
def category(db, user):
    c = Category(
        user_id=user.id, name="Продукты", kind="expense",
        priority="expense_essential", regularity="regular",
    )
    db.add(c); db.commit(); db.refresh(c)
    return c


@pytest.fixture
def session(db, user, regular_account):
    s = ImportSession(
        user_id=user.id, account_id=regular_account.id,
        filename="test.csv", file_content="", file_hash="orphan",
        source_type="csv", status="preview_ready",
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


def _make_rule(db, user, category, *, scope, is_active, normalized_description, confirms=5.0):
    r = TransactionCategoryRule(
        user_id=user.id, category_id=category.id,
        normalized_description=normalized_description,
        scope=scope, is_active=is_active,
        confirms=Decimal(str(confirms)), rejections=Decimal("0.00"),
    )
    db.add(r); db.commit(); db.refresh(r)
    return r


def _make_row(db, session, *, status, normalized):
    row = ImportRow(
        session_id=session.id, row_index=0, status=status,
        raw_data_json={}, normalized_data_json=normalized,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


class _NoCloseSession:
    def __init__(self, s): self.s = s
    def __enter__(self): return self.s
    def __exit__(self, *exc): return False


class TestRebuildDecisionsForOrphans:
    def test_dry_run_does_not_persist(
        self, db, user, category, session, monkeypatch,
    ):
        from scripts import rebuild_decisions_for_orphans as script

        rule = _make_rule(
            db, user, category,
            scope="legacy_pattern", is_active=False,
            normalized_description="оплата чтото",
        )
        row = _make_row(
            db, session, status="ready",
            normalized={
                "applied_rule_id": rule.id,
                "applied_rule_category_id": category.id,
                "predicted_category_id": category.id,
                "category_id": category.id,
                "normalized_description": "оплата чтото",
                "skeleton": "оплата чтото",
            },
        )

        monkeypatch.setattr(script, "SessionLocal", lambda: _NoCloseSession(db))
        script.run(execute=False, session_filter=None)

        db.refresh(row)
        # Untouched on dry-run.
        assert row.status == "ready"
        assert row.normalized_data_json["applied_rule_id"] == rule.id

    def test_execute_clears_decisions_and_escalates_to_warning(
        self, db, user, category, session, monkeypatch,
    ):
        from scripts import rebuild_decisions_for_orphans as script

        rule = _make_rule(
            db, user, category,
            scope="legacy_pattern", is_active=False,
            normalized_description="оплата чтото",
        )
        row = _make_row(
            db, session, status="ready",
            normalized={
                "applied_rule_id": rule.id,
                "applied_rule_category_id": category.id,
                "predicted_category_id": category.id,
                "category_id": category.id,
                "normalized_description": "оплата чтото",
                "skeleton": "оплата чтото",
                "fingerprint": "fp-fact",  # facts must survive
                "amount": "100.00",        # facts must survive
            },
        )

        monkeypatch.setattr(script, "SessionLocal", lambda: _NoCloseSession(db))
        script.run(execute=True, session_filter=None)

        db.refresh(row)
        norm = row.normalized_data_json

        # Decisions cleared.
        assert norm.get("applied_rule_id") is None
        assert norm.get("applied_rule_category_id") is None
        assert norm.get("predicted_category_id") is None
        assert norm.get("category_id") is None

        # Facts intact (§3.2).
        assert norm["fingerprint"] == "fp-fact"
        assert norm["amount"] == "100.00"
        assert norm["skeleton"] == "оплата чтото"

        # §1.2: status escalated to warning even if no new rule found.
        assert row.status == "warning"

    def test_execute_rematches_to_active_general_rule(
        self, db, user, category, session, monkeypatch,
    ):
        from scripts import rebuild_decisions_for_orphans as script

        # The orphaned legacy rule the row was attached to.
        orphan = _make_rule(
            db, user, category,
            scope="legacy_pattern", is_active=False,
            normalized_description="оплата чтото",
        )
        # A different category / different rule on the same skeleton — the
        # new general rule that should pick the row up.
        good_cat = Category(
            user_id=user.id, name="Услуги", kind="expense",
            priority="expense_essential", regularity="regular",
        )
        db.add(good_cat); db.commit(); db.refresh(good_cat)
        good_rule = _make_rule(
            db, user, good_cat,
            scope="general", is_active=True,
            normalized_description="оплата чтото", confirms=10.0,
        )

        row = _make_row(
            db, session, status="ready",
            normalized={
                "applied_rule_id": orphan.id,
                "applied_rule_category_id": category.id,
                "category_id": category.id,
                "normalized_description": "оплата чтото",
                "skeleton": "оплата чтото",
            },
        )

        monkeypatch.setattr(script, "SessionLocal", lambda: _NoCloseSession(db))
        script.run(execute=True, session_filter=None)

        db.refresh(row)
        norm = row.normalized_data_json
        # Re-matched to the new rule.
        assert norm["applied_rule_id"] == good_rule.id
        assert norm["applied_rule_category_id"] == good_cat.id
        assert norm["category_id"] == good_cat.id
        # Still warning per §1.2 — user must touch on this migration pass.
        assert row.status == "warning"

    def test_row_with_active_general_rule_is_untouched(
        self, db, user, category, session, monkeypatch,
    ):
        """A row whose applied_rule is still active in a non-legacy scope
        is NOT an orphan and must not be touched."""
        from scripts import rebuild_decisions_for_orphans as script

        live_rule = _make_rule(
            db, user, category,
            scope="general", is_active=True,
            normalized_description="оплата живая",
        )
        row = _make_row(
            db, session, status="ready",
            normalized={
                "applied_rule_id": live_rule.id,
                "applied_rule_category_id": category.id,
                "category_id": category.id,
                "normalized_description": "оплата живая",
                "skeleton": "оплата живая",
            },
        )

        monkeypatch.setattr(script, "SessionLocal", lambda: _NoCloseSession(db))
        script.run(execute=True, session_filter=None)

        db.refresh(row)
        assert row.status == "ready"
        assert row.normalized_data_json["applied_rule_id"] == live_rule.id

    def test_committed_and_terminal_rows_skipped(
        self, db, user, category, session, monkeypatch,
    ):
        from scripts import rebuild_decisions_for_orphans as script

        orphan = _make_rule(
            db, user, category,
            scope="legacy_pattern", is_active=False,
            normalized_description="оплата чтото",
        )
        # Row in committed status — must be skipped (terminal).
        committed_row = _make_row(
            db, session, status="committed",
            normalized={
                "applied_rule_id": orphan.id,
                "category_id": category.id,
                "normalized_description": "оплата чтото",
            },
        )
        # Row in error status — out of scope of cleanup.
        error_row = ImportRow(
            session_id=session.id, row_index=99, status="error",
            raw_data_json={}, normalized_data_json={
                "applied_rule_id": orphan.id, "category_id": category.id,
                "normalized_description": "оплата чтото",
            },
        )
        db.add(error_row); db.commit(); db.refresh(error_row)

        monkeypatch.setattr(script, "SessionLocal", lambda: _NoCloseSession(db))
        script.run(execute=True, session_filter=None)

        db.refresh(committed_row); db.refresh(error_row)
        assert committed_row.status == "committed"
        assert committed_row.normalized_data_json["applied_rule_id"] == orphan.id
        assert error_row.status == "error"
