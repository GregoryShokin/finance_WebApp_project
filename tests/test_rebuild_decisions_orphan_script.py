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
        script.run(execute=False, session_filter=None, mode="orphans")

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
        script.run(execute=True, session_filter=None, mode="orphans")

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
        script.run(execute=True, session_filter=None, mode="orphans")

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
        script.run(execute=True, session_filter=None, mode="orphans")

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
        script.run(execute=True, session_filter=None, mode="orphans")

        db.refresh(committed_row); db.refresh(error_row)
        assert committed_row.status == "committed"
        assert committed_row.normalized_data_json["applied_rule_id"] == orphan.id
        assert error_row.status == "error"


class TestRebuildDecisionsDemotedTransfers:
    """§12.1 + §5.2 v1.1 trigger 6 — restore silently-demoted transfers
    to (operation_type=transfer, status=error). The marker is a
    `error_message` substring «понижен до regular» left by pre-567b497
    silent demotion code."""

    def _make_demoted_row(
        self, db, session, *, status, op="regular", category_id=None, target=None,
    ):
        row = ImportRow(
            session_id=session.id, row_index=0, status=status,
            raw_data_json={},
            normalized_data_json={
                "operation_type": op,
                "account_id": session.account_id,
                "target_account_id": target,
                "category_id": category_id,
                "normalized_description": "внутренний перевод договор",
                "skeleton": "внутренний перевод договор",
                "fingerprint": "fp-demoted",
                "amount": "1000.00",
            },
            error_message="перевод без счёта получателя: понижен до regular",
        )
        db.add(row); db.commit(); db.refresh(row)
        return row

    def test_ready_demoted_transfer_restored_to_transfer_error(
        self, db, user, category, session, monkeypatch,
    ):
        from scripts import rebuild_decisions_for_orphans as script

        row = self._make_demoted_row(
            db, session, status="ready", category_id=category.id,
        )

        monkeypatch.setattr(script, "SessionLocal", lambda: _NoCloseSession(db))
        script.run(execute=True, session_filter=None, mode="demoted")

        db.refresh(row)
        norm = row.normalized_data_json
        # Restored to transfer per §12.1.
        assert norm["operation_type"] == "transfer"
        # Category dropped — transfers don't carry budget category.
        assert norm.get("category_id") is None
        # Facts preserved (§3.2).
        assert norm["fingerprint"] == "fp-demoted"
        assert norm["amount"] == "1000.00"
        # Status escalated to error per §5.2 v1.1 trigger 6.
        assert row.status == "error"
        # Issue text recorded for the moderator UI.
        assert row.error_message and "transfer" in row.error_message

    def test_warning_demoted_row_is_not_touched(
        self, db, user, category, session, monkeypatch,
    ):
        """Warning rows are already visible to the user — don't poke them."""
        from scripts import rebuild_decisions_for_orphans as script

        row = self._make_demoted_row(
            db, session, status="warning", category_id=category.id,
        )

        monkeypatch.setattr(script, "SessionLocal", lambda: _NoCloseSession(db))
        script.run(execute=True, session_filter=None, mode="demoted")

        db.refresh(row)
        assert row.status == "warning"
        assert row.normalized_data_json["operation_type"] == "regular"

    def test_row_without_demoted_marker_untouched(
        self, db, user, category, session, monkeypatch,
    ):
        """A regular ready row with no demotion marker must not be restored."""
        from scripts import rebuild_decisions_for_orphans as script

        row = ImportRow(
            session_id=session.id, row_index=0, status="ready",
            raw_data_json={},
            normalized_data_json={
                "operation_type": "regular",
                "account_id": session.account_id,
                "category_id": category.id,
                "normalized_description": "оплата кофе",
                "skeleton": "оплата кофе",
                "amount": "100.00",
            },
            error_message=None,
        )
        db.add(row); db.commit(); db.refresh(row)

        monkeypatch.setattr(script, "SessionLocal", lambda: _NoCloseSession(db))
        script.run(execute=True, session_filter=None, mode="demoted")

        db.refresh(row)
        assert row.status == "ready"
        assert row.normalized_data_json["operation_type"] == "regular"
        assert row.normalized_data_json["category_id"] == category.id

    def test_demoted_row_with_target_account_set_untouched(
        self, db, user, category, session, monkeypatch, regular_account,
    ):
        """If for some reason the target_account_id was later filled in,
        the integrity violation is gone — don't escalate to error."""
        from scripts import rebuild_decisions_for_orphans as script

        row = self._make_demoted_row(
            db, session, status="ready",
            category_id=category.id,
            target=regular_account.id,  # counter-account is set
        )

        monkeypatch.setattr(script, "SessionLocal", lambda: _NoCloseSession(db))
        script.run(execute=True, session_filter=None, mode="demoted")

        db.refresh(row)
        # Untouched — no integrity violation.
        assert row.status == "ready"
        assert row.normalized_data_json["operation_type"] == "regular"


class TestRebuildDecisionsSelfLoopTransfers:
    """§12.1 extended — transfer rows where account_id == target_account_id
    are semantically invalid (money cannot move from a single account to
    itself). Strip the bogus target and escalate to error."""

    def _make_self_loop_row(self, db, session, *, status, acc, category_id=None):
        row = ImportRow(
            session_id=session.id, row_index=0, status=status,
            raw_data_json={},
            normalized_data_json={
                "operation_type": "transfer",
                "account_id": acc,
                "target_account_id": acc,  # same as source — the bug
                "category_id": category_id,
                "normalized_description": "внутрибанковский перевод договор",
                "skeleton": "внутрибанковский перевод договор",
                "fingerprint": "fp-selfloop",
                "amount": "1000.00",
            },
        )
        db.add(row); db.commit(); db.refresh(row)
        return row

    def test_ready_self_loop_cleared_and_escalated_to_error(
        self, db, user, category, session, monkeypatch, regular_account,
    ):
        from scripts import rebuild_decisions_for_orphans as script

        row = self._make_self_loop_row(
            db, session, status="ready",
            acc=regular_account.id, category_id=category.id,
        )

        monkeypatch.setattr(script, "SessionLocal", lambda: _NoCloseSession(db))
        script.run(execute=True, session_filter=None, mode="self-loop")

        db.refresh(row)
        norm = row.normalized_data_json
        assert norm["operation_type"] == "transfer"
        assert norm.get("target_account_id") is None  # bogus tgt dropped
        assert norm.get("category_id") is None
        # Source preserved — that's a real fact.
        assert int(norm["account_id"]) == regular_account.id
        # Facts preserved (§3.2).
        assert norm["fingerprint"] == "fp-selfloop"
        assert norm["amount"] == "1000.00"
        assert row.status == "error"

    def test_warning_self_loop_untouched(
        self, db, user, category, session, monkeypatch, regular_account,
    ):
        """Like demoted-mode, only ready rows are touched."""
        from scripts import rebuild_decisions_for_orphans as script

        row = self._make_self_loop_row(
            db, session, status="warning",
            acc=regular_account.id, category_id=category.id,
        )

        monkeypatch.setattr(script, "SessionLocal", lambda: _NoCloseSession(db))
        script.run(execute=True, session_filter=None, mode="self-loop")

        db.refresh(row)
        assert row.status == "warning"
        assert int(row.normalized_data_json["target_account_id"]) == regular_account.id

    def test_distinct_account_transfer_not_touched(
        self, db, user, category, session, monkeypatch, regular_account, credit_account,
    ):
        """A real cross-account transfer must survive the self-loop pass."""
        from scripts import rebuild_decisions_for_orphans as script

        row = ImportRow(
            session_id=session.id, row_index=0, status="ready",
            raw_data_json={},
            normalized_data_json={
                "operation_type": "transfer",
                "account_id": regular_account.id,
                "target_account_id": credit_account.id,
                "amount": "5000.00",
                "fingerprint": "fp-real-xfer",
            },
        )
        db.add(row); db.commit(); db.refresh(row)

        monkeypatch.setattr(script, "SessionLocal", lambda: _NoCloseSession(db))
        script.run(execute=True, session_filter=None, mode="self-loop")

        db.refresh(row)
        assert row.status == "ready"
        assert int(row.normalized_data_json["target_account_id"]) == credit_account.id
