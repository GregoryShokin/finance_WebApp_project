"""Simplified matcher: pair active rows by (date, amount, opposite direction,
different accounts) AND require at least one side to contain a transfer
keyword like «перевод» in the description / skeleton.

Rationale: the previous, more elaborate matcher generated false positives
on amount coincidences (round-number cashbacks, refunds, scheduled
payments), and the committed-tx mirror experiment broke cross-session
pairing entirely by injecting synthetic candidates that competed with
real active rows. The user's chosen contract: only these four criteria.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.models.account import Account
from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.services.transfer_matcher_service import TransferMatcherService


@pytest.fixture
def second_account(db, user):
    acc = Account(
        user_id=user.id,
        name="Тинькоф Дебет",
        account_type="regular",
        balance=Decimal("50000"),
        currency="RUB",
        is_active=True,
        is_credit=False,
    )
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


@pytest.fixture
def matcher(db):
    return TransferMatcherService(db)


def _session(db, user, account):
    s = ImportSession(
        user_id=user.id, account_id=account.id,
        filename=f"sess-{account.id}.csv",
        file_content="", file_hash=f"h-{account.id}",
        source_type="csv", status="preview_ready",
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


_row_index_counter: dict[int, int] = {}


def _row(db, session, *, direction, amount, when, description):
    idx = _row_index_counter.get(session.id, 0)
    _row_index_counter[session.id] = idx + 1
    row = ImportRow(
        session_id=session.id, row_index=idx, status="ready",
        raw_data_json={},
        normalized_data_json={
            "operation_type": "transfer" if "перевод" in description.lower() else "regular",
            "account_id": session.account_id,
            "direction": direction,
            "amount": str(amount),
            "date": when.isoformat(),
            "description": description,
            "normalized_description": description.lower(),
            "skeleton": description.lower(),
            "fingerprint": f"fp-{session.account_id}-{direction}-{amount}-{idx}",
        },
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


class TestSimpleKeywordFilter:
    def test_pair_with_keyword_on_both_sides_is_matched(
        self, db, user, regular_account, second_account, matcher,
    ):
        """Both descriptions contain «перевод» — pair must match."""
        when = datetime(2026, 1, 22, 15, 5, tzinfo=timezone.utc)
        sess_a = _session(db, user, regular_account)
        sess_b = _session(db, user, second_account)
        expense = _row(
            db, sess_a, direction="expense", amount="15000.00", when=when,
            description="Внутренний перевод на договор 5452737298",
        )
        income = _row(
            db, sess_b, direction="income", amount="15000.00", when=when,
            description="Внутрибанковский перевод с договора 0504603705",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(expense); db.refresh(income)
        assert (expense.normalized_data_json or {}).get("operation_type") == "transfer"
        assert (income.normalized_data_json or {}).get("operation_type") == "transfer"
        # Income is the secondary side of an active-active pair → duplicate.
        assert income.status == "duplicate"
        # Expense is the primary side → ready, with target pointing at income's account.
        assert expense.status == "ready"
        assert (expense.normalized_data_json or {}).get("target_account_id") == second_account.id

    def test_pair_with_keyword_on_one_side_is_matched(
        self, db, user, regular_account, second_account, matcher,
    ):
        """Only one side contains «перевод» — still matched (one-sided
        keyword is enough)."""
        when = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)
        sess_a = _session(db, user, regular_account)
        sess_b = _session(db, user, second_account)
        # expense side has the keyword
        expense = _row(
            db, sess_a, direction="expense", amount="5000.00", when=when,
            description="Перевод между своими счетами",
        )
        # income side describes generically (no «перевод» word)
        income = _row(
            db, sess_b, direction="income", amount="5000.00", when=when,
            description="Поступление",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(expense); db.refresh(income)
        assert expense.status == "ready"
        assert income.status == "duplicate"

    def test_pair_without_keyword_anywhere_is_not_matched(
        self, db, user, regular_account, second_account, matcher,
    ):
        """Neither side mentions «перевод» — the matcher must NOT pair them
        on amount + date alone. Prevents amount-coincidence false positives
        like cashback + refund happening to share a round number."""
        when = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
        sess_a = _session(db, user, regular_account)
        sess_b = _session(db, user, second_account)
        expense = _row(
            db, sess_a, direction="expense", amount="2466.00", when=when,
            description="Оплата в магазине",
        )
        income = _row(
            db, sess_b, direction="income", amount="2466.00", when=when,
            description="Кэшбэк за покупки",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(expense); db.refresh(income)
        # Both stay non-transfer — no false positive.
        assert (expense.normalized_data_json or {}).get("operation_type") != "transfer"
        assert (income.normalized_data_json or {}).get("operation_type") != "transfer"

    def test_same_account_pair_is_rejected(
        self, db, user, regular_account, matcher,
    ):
        """Even with the keyword and matching amount/date, two rows on
        the same account cannot be a transfer (no source≠target)."""
        when = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)
        sess = _session(db, user, regular_account)
        a = _row(
            db, sess, direction="expense", amount="100.00", when=when,
            description="Перевод 1",
        )
        b = _row(
            db, sess, direction="income", amount="100.00", when=when,
            description="Перевод 2",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(a); db.refresh(b)
        # Stays non-paired — different sessions / different accounts required.
        assert (a.normalized_data_json or {}).get("target_account_id") in (None, "", 0)
        assert (b.normalized_data_json or {}).get("target_account_id") in (None, "", 0)

    def test_amount_mismatch_is_not_matched(
        self, db, user, regular_account, second_account, matcher,
    ):
        when = datetime(2026, 1, 22, 15, 5, tzinfo=timezone.utc)
        sess_a = _session(db, user, regular_account)
        sess_b = _session(db, user, second_account)
        expense = _row(
            db, sess_a, direction="expense", amount="15000.00", when=when,
            description="Перевод между своими",
        )
        income = _row(
            db, sess_b, direction="income", amount="14999.00", when=when,
            description="Перевод между своими",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(expense); db.refresh(income)
        assert (expense.normalized_data_json or {}).get("target_account_id") in (None, "", 0)
        assert (income.normalized_data_json or {}).get("target_account_id") in (None, "", 0)

    def test_same_direction_is_not_matched(
        self, db, user, regular_account, second_account, matcher,
    ):
        """Two expense-direction rows can't be transfer halves."""
        when = datetime(2026, 1, 22, 15, 5, tzinfo=timezone.utc)
        sess_a = _session(db, user, regular_account)
        sess_b = _session(db, user, second_account)
        a = _row(
            db, sess_a, direction="expense", amount="15000.00", when=when,
            description="Перевод между своими",
        )
        b = _row(
            db, sess_b, direction="expense", amount="15000.00", when=when,
            description="Перевод между своими",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(a); db.refresh(b)
        assert (a.normalized_data_json or {}).get("target_account_id") in (None, "", 0)
        assert (b.normalized_data_json or {}).get("target_account_id") in (None, "", 0)

    def test_orphan_transfer_error_row_can_still_be_paired(
        self, db, user, regular_account, second_account, matcher,
    ):
        """A previous matcher pass left an orphan-transfer row in `error`
        (operation_type=transfer + no target_account_id). When the counter-side
        arrives in a later session, the matcher must still consider that row
        and pair it — not skip it because of the leftover error status.

        Real-world case: T-Bank PDF describes outgoing C2A as «Операция в
        других кредитных организациях YandexBank_C2A …» with no «перевод»
        keyword on its own side. The classifier still picks operation_type=
        transfer (via skeleton patterns), but with target unknown the gate
        marks the row `error`. When the Yandex Bank statement is imported
        later, its «Входящий перевод с карты *1232» income row provides the
        keyword + counter-account — the pair must complete.
        """
        when = datetime(2026, 3, 13, 23, 14, tzinfo=timezone.utc)
        sess_a = _session(db, user, regular_account)
        sess_b = _session(db, user, second_account)
        # The "error" T-Bank-side row: classified transfer, no target, no keyword.
        expense = _row(
            db, sess_a, direction="expense", amount="2000.00", when=when,
            description="Операция в других кредитных организациях YandexBank_C2A g. Moskva RUS",
        )
        # Override default operation_type=regular (set by _row when description
        # lacks "перевод") and force the orphan-transfer error scenario.
        nd = dict(expense.normalized_data_json or {})
        nd["operation_type"] = "transfer"
        nd["target_account_id"] = None
        expense.normalized_data_json = nd
        expense.status = "error"
        expense.error_message = "Перевод определён, но счёт получателя не распознан."
        db.add(expense); db.commit(); db.refresh(expense)

        # The counter-side from Yandex Bank — has the «перевод» keyword.
        income = _row(
            db, sess_b, direction="income", amount="2000.00", when=when,
            description="Входящий перевод с карты *1232",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(expense); db.refresh(income)
        # The orphan-transfer error row got paired and rehabilitated.
        assert expense.status == "ready"
        assert expense.error_message is None
        assert (expense.normalized_data_json or {}).get("target_account_id") == second_account.id
        # Income side becomes the secondary half of the pair.
        assert income.status == "duplicate"

    def test_pair_across_adjacent_calendar_days_is_matched(
        self, db, user, regular_account, second_account, matcher,
    ):
        """One side at 23:50 МСК, other at 02:10 МСК next day. Same logical
        transfer, but in different calendar days. Window must accept it.

        Post-v1.10 guard: rows with different skeletons that are hours apart
        also need a shared identifier (contract_number) — otherwise they
        could be unrelated coincident events. We add a shared contract via
        the session's parse_settings to satisfy the guard."""
        from datetime import timedelta
        when_a = datetime(2026, 4, 1, 23, 50, tzinfo=ZoneInfo("Europe/Moscow"))
        when_b = when_a + timedelta(hours=4, minutes=20)  # 02.04 04:10 МСК
        sess_a = _session(db, user, regular_account)
        sess_b = _session(db, user, second_account)
        # Shared contract — a real cross-bank transfer pair almost always
        # mentions the same contract / IBAN somewhere; the matcher reads it
        # from the session's parse_settings as well as per-row tokens.
        sess_a.parse_settings = {"contract_number": "5452737298"}
        sess_b.parse_settings = {"contract_number": "5452737298"}
        db.add(sess_a); db.add(sess_b); db.commit()
        expense = _row(
            db, sess_a, direction="expense", amount="3000.00", when=when_a,
            description="Перевод между своими",
        )
        income = _row(
            db, sess_b, direction="income", amount="3000.00", when=when_b,
            description="Входящий перевод с карты *1232",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(expense); db.refresh(income)
        assert expense.status == "ready"
        assert income.status == "duplicate"
        assert (expense.normalized_data_json or {}).get("target_account_id") == second_account.id

    def test_unrelated_skeletons_hours_apart_no_identifier_rejected(
        self, db, user, regular_account, second_account, matcher,
    ):
        """Real-world false positive (sessions 267/270 on 2025-12-21):
        T-Bank +600 ₽ «Пополнение. Система быстрых платежей» at 19:43,
        Ozon −600 ₽ «Перевод b53552138318280b…» at 22:38. Same day, same
        amount, both contain a transfer-keyword, but skeletons are
        unrelated and no shared identifier — must NOT pair (otherwise the
        income side gets stuck as duplicate forever and never commits)."""
        from datetime import timedelta
        when_a = datetime(2025, 12, 21, 19, 43, tzinfo=ZoneInfo("Europe/Moscow"))
        when_b = when_a + timedelta(hours=2, minutes=55)
        sess_a = _session(db, user, regular_account)
        sess_b = _session(db, user, second_account)
        income = _row(
            db, sess_a, direction="income", amount="600.00", when=when_a,
            description="Пополнение. Система быстрых платежей",
        )
        expense = _row(
            db, sess_b, direction="expense", amount="600.00", when=when_b,
            description="Перевод b53552138318280b0000110011661101 через",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(expense); db.refresh(income)
        # Neither side should have been paired.
        assert (expense.normalized_data_json or {}).get("target_account_id") in (None, "", 0)
        assert (income.normalized_data_json or {}).get("target_account_id") in (None, "", 0)

    def test_pair_two_calendar_days_apart_is_rejected(
        self, db, user, regular_account, second_account, matcher,
    ):
        """48+ hours / 2 calendar days apart — outside the window, even with
        the keyword and matching amount."""
        from datetime import timedelta
        when_a = datetime(2026, 4, 1, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))
        when_b = when_a + timedelta(days=2)  # exactly 2 calendar days later
        sess_a = _session(db, user, regular_account)
        sess_b = _session(db, user, second_account)
        expense = _row(
            db, sess_a, direction="expense", amount="3000.00", when=when_a,
            description="Перевод между своими",
        )
        income = _row(
            db, sess_b, direction="income", amount="3000.00", when=when_b,
            description="Входящий перевод с карты *1232",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(expense); db.refresh(income)
        assert (expense.normalized_data_json or {}).get("target_account_id") in (None, "", 0)
        assert (income.normalized_data_json or {}).get("target_account_id") in (None, "", 0)

    def test_non_transfer_error_row_is_not_paired(
        self, db, user, regular_account, second_account, matcher,
    ):
        """An `error` row whose error is unrelated to orphan transfer (e.g.
        unknown account, broken amount) must NOT be silently rehabilitated
        by the matcher. Only orphan-transfer errors get a second chance."""
        when = datetime(2026, 3, 13, 23, 14, tzinfo=timezone.utc)
        sess_a = _session(db, user, regular_account)
        sess_b = _session(db, user, second_account)
        expense = _row(
            db, sess_a, direction="expense", amount="2000.00", when=when,
            description="Перевод между своими",
        )
        # Make it a non-transfer error: unknown account, regular operation.
        nd = dict(expense.normalized_data_json or {})
        nd["operation_type"] = "regular"  # not a transfer
        expense.normalized_data_json = nd
        expense.status = "error"
        expense.error_message = "Не указан счёт."
        db.add(expense); db.commit(); db.refresh(expense)

        income = _row(
            db, sess_b, direction="income", amount="2000.00", when=when,
            description="Входящий перевод с карты *1232",
        )

        matcher.match_transfers_for_user(user_id=user.id)

        db.refresh(expense); db.refresh(income)
        # Still error — matcher didn't touch it.
        assert expense.status == "error"
        assert (expense.normalized_data_json or {}).get("target_account_id") in (None, "", 0)
