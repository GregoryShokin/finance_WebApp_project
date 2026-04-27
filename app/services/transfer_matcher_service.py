"""
Cross-session transfer matcher.

After each build_preview, this service scans all active (uncommitted) ImportRow
records for the user and finds pairs that represent two sides of the same transfer.
It also checks already-committed transactions so that when the second half of a
transfer arrives in a new session it is immediately flagged.

Matching criteria (all required):
  1. Amounts are exactly equal.
  2. Directions are opposite (expense ↔ income).
  3. Calendar-day difference in МСК ≤ 1 (same day or adjacent day).
  4. Rows belong to different sessions (different accounts).

Scoring (within the day-window):
  • time_diff == 0 s        → 1.00
  • time_diff ≤ 60 s        → 0.97
  • time_diff ≤ 1 h         → 0.93
  • same calendar day, > 1h → 0.88
  • adjacent calendar day   → 0.80
  Bonus +0.05 if both sides share the same contract_number.

Pairs with score < MIN_SCORE are discarded.
Greedy 1-to-1 assignment (highest score first).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.transaction import Transaction as TransactionModel
from app.repositories.account_repository import AccountRepository
from app.repositories.import_repository import ImportRepository
from app.repositories.transaction_repository import TransactionRepository

MIN_SCORE = 0.60
# Календарный допуск окна — ±1 день в банковской TZ (см. _BANK_TZ).
# Раньше использовался час-бюджет (12ч), но это не покрывало кейс «операция
# 23:50 одного дня → списание контрагентом 02:00 следующего», где две стороны
# одной transfer-пары попадают в соседние календарные дни даже после TZ-фикса
# в нормализаторе. Сравнение по .date() в МСК надёжнее, чем по часам.
MAX_DATE_DIFF_DAYS = 1
_BANK_TZ = ZoneInfo("Europe/Moscow")

# Keywords that strongly indicate a payment/purchase — NOT an internal transfer.
# If either candidate contains one of these, the pair score is penalized.
_ANTI_TRANSFER_KEYWORDS = frozenset({
    # Кредитные/регулярные платежи
    "регулярный платёж",
    "регулярный платеж",
    "оплата кредита",
    "погашение кредита",
    "ежемесячный платёж",
    "ежемесячный платеж",
    "оплата задолженности",
    "оплата покупки",
    "минимальный платёж",
    "минимальный платеж",
    # Оплата услуг — общий маркер платёжки. Без него Megafon/MTS/Beeline и
    # любые «Оплата услуг X» легко спариваются как «перевод» по совпадению
    # суммы — они ведь такие же expense, просто другая сессия имеет income
    # 500 ₽ той же датой, и matcher делает ложно-положительную пару.
    "оплата услуг",
    "оплата товаров",
    # Мобильные операторы и популярные сервисы
    "mbank",
    "м.банк",
    "megafon",
    "мегафон",
    "mts",
    "мтс",
    "beeline",
    "билайн",
    "tele2",
    "теле2",
    "yota",
    "йота",
    # Магазины / маркетплейсы — только если явно платёж, не перевод
    # НЕ добавляй сюда "яндекс"/"ozon" — это банки, переводы между ними легитимны.
    "wildberries",
    "вайлдберриз",
    "spbu",
    # Подписки и сервисы
    "подписк",
    "subscription",
    "spotify",
    "youtube",
    "netflix",
    "apple",
    "google",
})

# Keywords that strongly indicate an internal transfer between the user's own
# accounts. If BOTH sides of a candidate pair contain one of these, we add a
# small bonus to the score. Applied BEFORE anti-penalty — a scheduled payment
# that happens to have "перевод" in the description still gets cut by ×0.4.
_PRO_TRANSFER_KEYWORDS = frozenset({
    "перевод",
    "transfer",
    "между счетами",
    "между своими",
    "с карты на карту",
    "card to card",
    "card-to-card",
    "own transfer",
    "own account",
    "c2c",
})


@dataclass
class _Candidate:
    row_id: int | None       # ImportRow.id  (None for committed TX)
    tx_id: int | None        # Transaction.id (None for import rows)
    session_id: int | None   # ImportSession.id (None for committed TX)
    account_id: int
    amount: Decimal
    date: datetime
    direction: str           # "income" | "expense"
    contract_number: str | None = None
    description: str | None = None
    row_skeleton: str | None = None  # nd.get('skeleton') — для §8.1 проверки в _detect_committed_duplicates

    @property
    def key(self) -> tuple:
        if self.row_id is not None:
            return ("row", self.row_id)
        if self.tx_id is not None:
            return ("tx", self.tx_id)
        # Analyzed session candidate: keyed by (session_id, amount, date) for dedup
        return ("analyzed", self.session_id, str(self.amount), str(self.date))


class TransferMatcherService:
    def __init__(self, db: Session):
        self.db = db
        self.import_repo = ImportRepository(db)
        self.transaction_repo = TransactionRepository(db)
        self.account_repo = AccountRepository(db)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def match_transfers_for_user(self, *, user_id: int) -> None:
        """Re-runs cross-session transfer matching for all active sessions.

        Called automatically after every build_preview.  Rows where the user
        manually set transfer_match_locked=True are left untouched.

        Matching pool:
          1. ImportRows from preview_ready sessions (fully normalized).
          2. Raw rows from analyzed sessions (not yet previewed) — parsed
             directly from parse_settings so they participate in matching
             even before the user opens them.
          3. Committed transactions within the date range.
        """
        # Reset rows that were marked duplicate by the old cross-session matcher
        # logic (income side = secondary). With the new logic both sides are
        # primary (status='ready'). Old rows still carry status='duplicate' +
        # match_source='cross_session', so they're invisible to the candidate
        # loader below. Clear them first so the re-run picks them up.
        self._reset_cross_session_secondary_duplicates(user_id=user_id)

        active_candidates = self._load_active_row_candidates(user_id)
        analyzed_candidates = self._load_analyzed_session_candidates(user_id)

        # For date-range scoping of committed transactions, use all candidates.
        all_uncommitted = active_candidates + analyzed_candidates
        date_range = self._date_range_of(all_uncommitted)
        committed_candidates: list[_Candidate] = []
        if date_range:
            committed_candidates = self._load_committed_candidates(user_id, *date_range)

        # Active (previewed) rows are matched against everything.
        all_candidates = active_candidates + analyzed_candidates + committed_candidates

        if not all_candidates:
            return

        pairs = self._find_candidate_pairs(active_candidates, all_candidates)
        assignments = self._greedy_assign(pairs)
        self._apply_assignments(assignments, user_id)

        # Second pass: mark import rows as duplicates when a committed transaction
        # already covers the same account/direction/amount (e.g. phantom income
        # created when the other side of a transfer was committed earlier).
        already_assigned = {
            row_id
            for a, b, _ in assignments
            for row_id in [a.row_id, b.row_id]
            if row_id is not None
        }
        if date_range:
            self._detect_committed_duplicates(
                user_id=user_id,
                active_candidates=active_candidates,
                date_from=date_range[0],
                date_to=date_range[1],
                skip_row_ids=already_assigned,
            )

        # Post-matcher §12.1 cleanup: any remaining row that is
        # operation_type='transfer' AND target_account_id IS None has had
        # its last automated chance to find a pair. Escalate to `error` via
        # the same gate the moderator UI uses (final=True). This restores
        # §5.2 trigger 6 — orphan transfer is a data-integrity error — but
        # only AFTER the matcher had a fair chance to fill in target.
        self._escalate_orphan_transfers(user_id=user_id)

    def _reset_cross_session_secondary_duplicates(self, *, user_id: int) -> None:
        """Clear stale cross-session-secondary duplicate rows before re-matching.

        Old matcher logic always made the income side of a cross-session pair
        status='duplicate' (is_secondary=True). The new logic makes both sides
        status='ready'. Rows from previous matcher runs still carry the old
        status in the DB and are invisible to _load_active_row_candidates.
        Reset them to 'warning' (needs re-review) and clear their transfer_match
        so the fresh matcher pass re-classifies them correctly.

        Only resets rows with match_source='cross_session' — never touches rows
        from _detect_committed_duplicates (match_source='committed_tx_duplicate')
        which are real duplicates of already-committed transactions.
        """
        rows = (
            self.db.query(ImportRow)
            .join(ImportSession, ImportRow.session_id == ImportSession.id)
            .filter(
                ImportSession.user_id == user_id,
                ImportSession.status != "committed",
                ImportRow.status == "duplicate",
            )
            .all()
        )
        touched = 0
        for row in rows:
            nd: dict = dict(row.normalized_data_json or {})
            match = nd.get("transfer_match") or {}
            if match.get("match_source") != "cross_session":
                continue
            # Strip matcher-assigned fields so the fresh pass starts clean.
            nd.pop("transfer_match", None)
            nd.pop("target_account_id", None)
            nd.pop("operation_type", None)
            row.normalized_data_json = nd
            row.status = "warning"
            row.error_message = None
            self.db.add(row)
            touched += 1
        if touched:
            self.db.flush()

    def _escalate_orphan_transfers(self, *, user_id: int) -> None:
        """Demote post-matcher orphan transfers to `regular`.

        A row qualifies if:
          * status IN ('ready', 'warning')  (not committed/duplicate/excluded)
          * operation_type == 'transfer'
          * target_account_id is None (or empty)

        v1.9 — semantics flip vs v1.0–v1.8: previously we promoted such rows
        to `error` (§5.2 trigger 6). UX feedback (2026-04-26): «Внешний
        перевод по номеру телефона …» without a matched pair is almost
        always a regular outflow (gift / debt / payment to a person), NOT
        an inter-account transfer. Showing it as a transfer with «Куда
        перевод…» empty selector forced the user to either fix the row or
        live with an error — neither matches the actual semantic.

        Now: switch operation_type → 'regular', clear transfer-side fields,
        flag `was_orphan_transfer=true` so the user can flip it back to
        transfer manually if it really was inter-account, set status to
        warning (because category_id is almost always null at this point
        and the user must pick one). The original §12.1 invariant — a
        transfer must have both accounts known — is still enforced for
        rows the user *explicitly* keeps as transfer (handled in the
        moderator's apply-time validation, not here).
        """
        rows = (
            self.db.query(ImportRow)
            .join(ImportSession, ImportRow.session_id == ImportSession.id)
            .filter(
                ImportSession.user_id == user_id,
                ImportSession.status != "committed",
                ImportRow.status.in_(("ready", "warning", "error")),
            )
            .all()
        )
        touched = 0
        for row in rows:
            nd: dict = dict(row.normalized_data_json or {})
            if str(nd.get("operation_type") or "") != "transfer":
                continue
            if nd.get("target_account_id") not in (None, "", 0):
                continue
            # Skip rows the user already touched — once they've picked
            # transfer + a counter-account explicitly, we shouldn't undo it.
            # If user_confirmed_at is set with operation_type=transfer and
            # no target, that's a manual choice we honor (the apply-time
            # validator catches it separately).
            if nd.get("user_confirmed_at"):
                continue
            nd["operation_type"] = "regular"
            nd["was_orphan_transfer"] = True
            nd.pop("transfer_match", None)
            row.normalized_data_json = nd
            row.error_message = None
            row.status = "warning"
            self.db.add(row)
            touched += 1
        if touched:
            self.db.flush()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_active_row_candidates(self, user_id: int) -> list[_Candidate]:
        # Include `error` rows whose error is specifically "orphan transfer"
        # (operation_type=transfer + no target_account_id + no transfer_match yet).
        # Without them the matcher hits a chicken-and-egg: §5.2 trigger 6 escalates
        # orphan transfers to `error` *after* a fruitless matcher pass, but a later
        # session bringing the counter-side never gets paired because the matcher
        # would skip the error-rows from the previous pass. If the matcher now
        # finds a partner, `_apply_assignments` rewrites status to ready/duplicate
        # and clears error_message; if not, status stays `error` — same result.
        rows_with_sessions = (
            self.db.query(ImportSession, ImportRow)
            .join(ImportRow, ImportRow.session_id == ImportSession.id)
            .filter(
                ImportSession.user_id == user_id,
                ImportSession.status != "committed",
                ImportSession.account_id.isnot(None),
                ImportRow.status.in_(["ready", "warning", "error"]),
            )
            .all()
        )

        candidates: list[_Candidate] = []
        for session, row in rows_with_sessions:
            nd: dict = row.normalized_data_json or {}

            if nd.get("transfer_match_locked"):
                continue

            if str(row.status or "") == "error":
                is_orphan_transfer = (
                    str(nd.get("operation_type") or "") == "transfer"
                    and nd.get("target_account_id") in (None, "", 0)
                    and not nd.get("transfer_match")
                )
                if not is_orphan_transfer:
                    continue

            amount = self._parse_decimal(nd.get("amount"))
            date = self._parse_datetime(nd.get("transaction_date") or nd.get("date"))
            direction = str(nd.get("direction") or nd.get("type") or "").lower()

            if direction not in ("income", "expense") or amount is None or date is None:
                continue

            parse_settings: dict = session.parse_settings or {}
            contract = (
                self._extract_contract(nd)
                or parse_settings.get("contract_number")
                or parse_settings.get("statement_account_number")
            )

            candidates.append(_Candidate(
                row_id=row.id,
                tx_id=None,
                session_id=session.id,
                account_id=int(session.account_id),
                amount=amount,
                date=date,
                direction=direction,
                contract_number=contract,
                description=str(nd.get("description") or nd.get("raw_description") or "").lower(),
                row_skeleton=str(nd.get("skeleton") or "") or None,
            ))

        return candidates

    def _load_analyzed_session_candidates(self, user_id: int) -> list[_Candidate]:
        """Load lightweight candidates from sessions that are 'analyzed' (not yet
        previewed).  Raw rows are stored in parse_settings['tables'][0]['rows'].
        These candidates are read-only — they participate in scoring but are never
        updated (we can't update them since there are no ImportRow records yet).
        """
        sessions = (
            self.db.query(ImportSession)
            .filter(
                ImportSession.user_id == user_id,
                ImportSession.status == "analyzed",
                ImportSession.account_id.isnot(None),
            )
            .all()
        )

        candidates: list[_Candidate] = []
        for session in sessions:
            ps: dict = session.parse_settings or {}
            tables = ps.get("tables") or []
            if not tables:
                continue
            primary_table = tables[0]
            rows = primary_table.get("rows") or []
            contract = (
                ps.get("contract_number")
                or ps.get("statement_account_number")
            )

            for raw_row in rows:
                amount = self._parse_decimal(
                    str(raw_row.get("amount") or "").replace("+", "").replace(",", ".")
                )
                # Raw date format from extractors: "DD.MM.YYYY HH:MM[:SS]" or ISO
                date = self._parse_raw_date(raw_row.get("date") or raw_row.get("posted_date"))
                direction = str(raw_row.get("direction") or "").lower()

                if amount is None or date is None or direction not in ("income", "expense"):
                    continue
                if amount <= 0:
                    continue

                # Raw description for pro/anti keyword scoring. Extractors use
                # varying field names (description / purpose / raw_description),
                # so merge them into one lowered string for keyword matching.
                desc_parts = [
                    raw_row.get("description"),
                    raw_row.get("purpose"),
                    raw_row.get("raw_description"),
                    raw_row.get("details"),
                ]
                description = " ".join(
                    str(p) for p in desc_parts if p is not None and str(p).strip()
                ).lower() or None

                # row_id=None marks this as an analyzed (not-yet-imported) candidate;
                # _apply_assignments skips it, but it participates in scoring.
                candidates.append(_Candidate(
                    row_id=None,
                    tx_id=None,
                    session_id=session.id,
                    account_id=int(session.account_id),
                    amount=amount,
                    date=date,
                    direction=direction,
                    contract_number=contract,
                    description=description,
                ))

        return candidates

    def _load_committed_candidates(
        self, user_id: int, date_from: datetime, date_to: datetime
    ) -> list[_Candidate]:
        """Committed candidates for transfer-pair matching.

        Loads ALL committed transactions in the date window (not just
        transfers). Restricting to op=transfer and emitting TWO candidates
        per transfer (mirror) was experimented with but broke cross-session
        matching: synthetic mirror candidates competed with real active
        rows for greedy assignment and starved them of pairs. The
        committed-tx duplicate detection of the receiving-side input row
        is handled separately in `_detect_committed_duplicates` (second
        pass), which uses a mirror INDEX rather than mirror CANDIDATES,
        so it doesn't compete with active-row matching.
        """
        buffer = timedelta(days=2)
        from datetime import timezone as _tz
        df_aware = date_from.replace(tzinfo=_tz.utc) if date_from.tzinfo is None else date_from
        dt_aware = (date_to + buffer).replace(tzinfo=_tz.utc) if (date_to + buffer).tzinfo is None else (date_to + buffer)
        txs = (
            self.db.query(TransactionModel)
            .filter(
                TransactionModel.user_id == user_id,
                TransactionModel.transaction_date >= df_aware - buffer,
                TransactionModel.transaction_date <= dt_aware,
                TransactionModel.transfer_pair_id.is_(None),
            )
            .all()
        )
        candidates = []
        for tx in txs:
            parsed_date = self._parse_datetime(tx.transaction_date)
            if parsed_date is None:
                continue
            candidates.append(_Candidate(
                row_id=None,
                tx_id=tx.id,
                session_id=None,
                account_id=tx.account_id,
                amount=tx.amount,
                date=parsed_date,
                direction="income" if tx.type == "income" else "expense",
                description=str(tx.description or "").lower(),
            ))
        return candidates

    # ------------------------------------------------------------------
    # Pair finding & scoring
    # ------------------------------------------------------------------

    def _find_candidate_pairs(
        self,
        active_rows: list[_Candidate],
        all_candidates: list[_Candidate],
    ) -> list[tuple[_Candidate, _Candidate, float]]:
        pairs: list[tuple[_Candidate, _Candidate, float]] = []
        seen: set[frozenset] = set()

        for a in active_rows:
            for b in all_candidates:
                if a.key == b.key:
                    continue
                # Must be from different sessions / accounts
                if a.session_id is not None and a.session_id == b.session_id:
                    continue
                if a.account_id == b.account_id:
                    continue

                pair_key = frozenset([a.key, b.key])
                if pair_key in seen:
                    continue
                seen.add(pair_key)

                score = self._score_pair(a, b)
                if score >= MIN_SCORE:
                    pairs.append((a, b, score))

        return pairs

    def _score_pair(self, a: _Candidate, b: _Candidate) -> float:
        if a.direction == b.direction:
            return 0.0
        if a.amount != b.amount:
            return 0.0

        diff_seconds = abs((a.date - b.date).total_seconds())
        # Сравниваем календарные дни в банковской TZ: операция в 23:50 одного
        # дня и списание у контрагента в 02:00 следующего — это та же transfer-
        # пара (diff_days == 1), но diff_seconds может быть ~3-4ч. Конвертация
        # в _BANK_TZ нужна на случай committed-tx, у которого date в UTC.
        date_a = a.date.astimezone(_BANK_TZ).date() if a.date.tzinfo else a.date.date()
        date_b = b.date.astimezone(_BANK_TZ).date() if b.date.tzinfo else b.date.date()
        diff_days = abs((date_a - date_b).days)
        if diff_days > MAX_DATE_DIFF_DAYS:
            return 0.0

        # Required filter: at least ONE side must explicitly look like a
        # transfer (contain "перевод" / "transfer" / similar in description
        # or skeleton). Two random transactions that happen to share
        # (date, amount, opposite direction) on different accounts are not
        # a transfer pair — they are an amount coincidence. Without this
        # filter the matcher fired false positives across every dataset
        # where amounts repeat (e.g. round-number cashbacks and refunds).
        if not (
            self._has_pro_transfer_keyword(a)
            or self._has_pro_transfer_keyword(b)
        ):
            return 0.0

        # v1.10 — skeleton/identifier guard analogous to §8.6 duplicate-
        # detection. Two rows with completely unrelated skeletons that
        # only share a transfer keyword and a coincident amount are NOT
        # a pair when they're hours apart: e.g. «пополнение система
        # быстрых платежей» +600₽ on T-Bank at 19:43 and «перевод
        # b53552138318280b0000110011661101 через…» −600₽ on Ozon at 22:38
        # — same day, same amount, both contain a transfer keyword, but
        # they're independent events. Without this guard the matcher
        # silently glued them together and the income side stayed
        # `duplicate` forever.
        #
        # Real cross-bank mirror pairs share at least one of:
        #   (a) identical skeleton (banks rarely phrase mirrors identically);
        #   (b) a shared identifier (contract / phone / IBAN);
        #   (c) effectively the same timestamp — banks book both legs of a
        #       single internal transfer with the SAME timestamp (delta
        #       under one minute), which is the strongest signal we have
        #       in the absence of (a) or (b).
        #
        # If none of (a)/(b)/(c) holds — reject. This keeps legit exact-
        # twin pairs (KION / Ya-Bank case from v1.2: diff_seconds == 0,
        # different skeletons, no contract) untouched.
        skel_a = (a.row_skeleton or "").strip().lower()
        skel_b = (b.row_skeleton or "").strip().lower()
        same_skeleton = bool(skel_a) and skel_a == skel_b
        shared_contract = bool(
            a.contract_number
            and b.contract_number
            and a.contract_number == b.contract_number
        )
        nearly_simultaneous = diff_seconds <= 60
        if (
            skel_a and skel_b and not same_skeleton
            and not shared_contract
            and not nearly_simultaneous
        ):
            return 0.0

        # Часы остаются в скоринге как тай-брейкер: чем ближе по времени, тем
        # выше уверенность. Для пар в один календарный день — старая шкала.
        # Для пар в соседних днях (diff_days == 1) — отдельная ступень 0.80,
        # выше MIN_SCORE, но ниже любой пары в один день.
        if diff_seconds == 0:
            score = 1.00
        elif diff_seconds <= 60:
            score = 0.97
        elif diff_seconds <= 3600:
            score = 0.93
        elif diff_days == 0:
            score = 0.88
        else:
            score = 0.80

        if (
            a.contract_number
            and b.contract_number
            and a.contract_number == b.contract_number
        ):
            score = min(1.0, score + 0.05)

        # Pro-transfer keyword bonus: both sides contain an explicit transfer
        # keyword like "перевод" / "transfer" / "с карты на карту". Strong signal
        # that this is an internal movement, not two unrelated transactions that
        # happen to match on amount + time.
        if (
            self._has_pro_transfer_keyword(a)
            and self._has_pro_transfer_keyword(b)
        ):
            score = min(1.0, score + 0.1)

        # Penalize pairs where either side looks like a scheduled payment,
        # not an inter-account transfer. BUT: if both sides match exactly on
        # amount AND date-to-the-second (a unique fingerprint of an internal
        # transfer between two of the user's own accounts — the bank posts
        # both legs with a shared timestamp), skip the penalty. Otherwise
        # legit cross-account credit repayments ("Погашение кредита" posted
        # on both the source debit card and the target credit card with
        # matching timestamps) would score 0.40 and fall below MIN_SCORE.
        has_anti = self._has_anti_transfer_keyword(a) or self._has_anti_transfer_keyword(b)
        exact_twin = diff_seconds == 0 and a.amount == b.amount
        if has_anti and not exact_twin:
            score *= 0.4

        return round(score, 4)

    @staticmethod
    def _has_anti_transfer_keyword(c: _Candidate) -> bool:
        if not c.description:
            return False
        return any(kw in c.description for kw in _ANTI_TRANSFER_KEYWORDS)

    @staticmethod
    def _has_pro_transfer_keyword(c: _Candidate) -> bool:
        if not c.description:
            return False
        return any(kw in c.description for kw in _PRO_TRANSFER_KEYWORDS)

    # ------------------------------------------------------------------
    # Greedy 1-to-1 assignment
    # ------------------------------------------------------------------

    def _greedy_assign(
        self, pairs: list[tuple[_Candidate, _Candidate, float]]
    ) -> list[tuple[_Candidate, _Candidate, float]]:
        pairs.sort(key=lambda x: -x[2])
        assigned: set = set()
        result: list[tuple[_Candidate, _Candidate, float]] = []

        for a, b, score in pairs:
            if a.key in assigned or b.key in assigned:
                continue
            result.append((a, b, score))
            assigned.add(a.key)
            assigned.add(b.key)

        return result

    # ------------------------------------------------------------------
    # Applying results to ImportRow records
    # ------------------------------------------------------------------

    def _apply_assignments(
        self,
        assignments: list[tuple[_Candidate, _Candidate, float]],
        user_id: int,
    ) -> None:
        # Both sides of a cross-session pair are primary entries in their respective
        # statements — neither is a "secondary/duplicate". Both get status='ready' and
        # show as active transfer arrows in the moderator UI. The second side to commit
        # uses _link_transfer_to_committed_cross_session_pair (in ImportService) to
        # avoid creating a redundant pair when the first side has already committed.
        row_updates: dict[int, tuple[_Candidate, float, bool]] = {}  # bool: is_secondary (always False for cross-session)
        for a, b, score in assignments:
            a_is_row = a.row_id is not None
            b_is_row = b.row_id is not None
            a_is_secondary = False
            b_is_secondary = False
            if a_is_row:
                row_updates[a.row_id] = (b, score, a_is_secondary)
            if b_is_row:
                row_updates[b.row_id] = (a, score, b_is_secondary)

        if not row_updates:
            return

        rows = (
            self.db.query(ImportRow)
            .filter(ImportRow.id.in_(row_updates.keys()))
            .all()
        )
        accounts = {acc.id: acc for acc in self.account_repo.list_by_user(user_id)}

        for row in rows:
            other, score, is_secondary = row_updates[row.id]
            nd: dict = dict(row.normalized_data_json or {})

            other_account = accounts.get(other.account_id)

            nd["operation_type"] = "transfer"
            nd["target_account_id"] = other.account_id
            nd["category_id"] = None  # transfers don't need a category
            nd["transfer_match"] = {
                "matched_row_id": other.row_id,
                "matched_tx_id": other.tx_id,
                "matched_account_id": other.account_id,
                "matched_account_name": other_account.name if other_account else None,
                "match_confidence": score,
                "match_source": "cross_session" if other.session_id is not None else "committed_tx",
                "is_secondary": is_secondary,
            }

            row.normalized_data_json = nd

            # Clear stale validation errors.
            row.error_message = None
            row.status = "ready"

            self.db.add(row)

        self.db.flush()

    # ------------------------------------------------------------------
    # Same-account duplicate detection
    # ------------------------------------------------------------------

    def _detect_committed_duplicates(
        self,
        *,
        user_id: int,
        active_candidates: list[_Candidate],
        date_from: datetime,
        date_to: datetime,
        skip_row_ids: set[int],
    ) -> None:
        """Mark import rows as 'duplicate' when a committed transaction on the
        SAME account covers the same amount + direction within ±2 days.

        This handles the common case where the other side of a cross-account
        transfer was already committed (e.g. account A sent money to account B;
        when account B's statement is imported, those income rows are duplicates
        of the phantom income transaction created during account A's import).
        """
        from datetime import timezone as _tz
        buffer = timedelta(days=2)
        df_aware = date_from.replace(tzinfo=_tz.utc) if date_from.tzinfo is None else date_from
        dt_aware = (date_to + buffer).replace(tzinfo=_tz.utc) if (date_to + buffer).tzinfo is None else (date_to + buffer)

        # Load ALL committed transactions in the date range, including already-paired ones.
        all_txs = (
            self.db.query(TransactionModel)
            .filter(
                TransactionModel.user_id == user_id,
                TransactionModel.transaction_date >= df_aware - buffer,
                TransactionModel.transaction_date <= dt_aware,
            )
            .all()
        )

        # Build a lookup: (account_id, direction, amount) → list of (tx, parsed_date)
        #
        # Mirror entry for transfers: a single committed `transfer` row
        # represents BOTH sides of the operation (account_id sends, target
        # receives). The bank issues two statement lines for the same
        # operation — one in each account's statement. Without the mirror
        # the receiving-side input row would never match the committed
        # transfer (lookup key (target_acc, opposite_direction, amount)
        # would not exist in the index), and a duplicate transfer would
        # be created. Observed in sessions 235/236 where Тинькоф and
        # Тинькоф Дебет statements both arrived after one side had already
        # been committed earlier.
        committed_index: dict[tuple, list[tuple[TransactionModel, datetime]]] = {}
        for tx in all_txs:
            parsed = self._parse_datetime(tx.transaction_date)
            if parsed is None:
                continue
            direction = "income" if tx.type == "income" else "expense"
            key = (tx.account_id, direction, tx.amount)
            committed_index.setdefault(key, []).append((tx, parsed))
            if (
                str(tx.operation_type or "") == "transfer"
                and tx.target_account_id is not None
            ):
                mirror_direction = "expense" if direction == "income" else "income"
                mirror_key = (tx.target_account_id, mirror_direction, tx.amount)
                committed_index.setdefault(mirror_key, []).append((tx, parsed))

        # Match each active candidate against same-account committed txs.
        # §8.1: дедуп-ключ обязан включать skeleton — без него matcher
        # ложно склеивал две независимые операции, случайно совпавшие по
        # (account_id, direction, amount, ±2 дня). Например, СБП-приход
        # 5000₽ от внешнего отправителя и внутрибанковский перевод
        # 5000₽ с другой карты в тот же день — суммы совпали, но это
        # разные операции. Skeleton'ы у них разные («входящий перевод
        # сбп <PERSON>» vs «внутренний перевод на договор <CONTRACT>»),
        # и совпадение skeleton'а — то, что отличает повторный импорт
        # от случайной коллизии сумм.
        active_row_skeletons = {
            cand.row_id: (cand.row_skeleton or "").strip()
            for cand in active_candidates
            if cand.row_id is not None
        }
        rows_to_mark: dict[int, TransactionModel] = {}
        for cand in active_candidates:
            if cand.row_id is None or cand.row_id in skip_row_ids:
                continue
            key = (cand.account_id, cand.direction, cand.amount)
            committed_matches = committed_index.get(key, [])
            row_skel = active_row_skeletons.get(cand.row_id, "")
            for tx, tx_date in committed_matches:
                diff_seconds = abs((cand.date - tx_date).total_seconds())
                if diff_seconds > buffer.total_seconds():
                    continue
                tx_skel = (tx.skeleton or "").strip()
                # Mirror match: committed tx живёт на ЧУЖОМ счёте — попал в
                # индекс через зеркальную запись (target_account_id).
                # Его skeleton отражает описание банка-ОТПРАВИТЕЛЯ, а не
                # банка-ПОЛУЧАТЕЛЯ. Два разных банка никогда не описывают
                # один СБП/внутренний перевод одинаковыми словами, поэтому
                # skeleton guard здесь неприменим — он заблокировал бы все
                # легитимные mirror-дубли (кейс: Тинькоф expense committed,
                # потом импортируется Яндекс Дебет со своим описанием той же
                # операции). Оставляем только time-window проверку.
                #
                # Для same-account re-import (is_mirror=False) skeleton guard
                # остаётся: он защищает от ложных склеек двух разных операций
                # на одном счёте с совпавшими суммой+датой (§8.6).
                is_mirror = tx.account_id != cand.account_id
                # Фантомный transfer-income: committed tx живёт на ТОМ ЖЕ
                # счёте, что и import row (is_mirror=False), но был создан
                # автоматически через _create_transfer_pair при коммите
                # противоположной стороны (дебетовый счёт → Ozon кредитка).
                # Такой phantom наследует skeleton дебетовой стороны, а не
                # описание получателя, поэтому skeleton'ы всегда различны
                # даже для одной и той же операции. Признаки phantom income:
                #   • type=income (это принимающая сторона)
                #   • operation_type=transfer (создан как пара перевода)
                # Для таких строк снимаем skeleton guard — time-window + ключ
                # (account_id, income, amount) достаточно для корректного матча.
                # Риск false-positive минимален: два несвязанных transfer-income
                # на одном счёте с одинаковой суммой в пределах ±2 дней — крайне
                # редкий кейс; при необходимости юзер исправит вручную.
                is_phantom_transfer_income = (
                    not is_mirror
                    and str(tx.type or "") == "income"
                    and str(tx.operation_type or "") == "transfer"
                )
                if (
                    not is_mirror
                    and not is_phantom_transfer_income
                    and row_skel
                    and tx_skel
                    and row_skel != tx_skel
                ):
                    continue
                rows_to_mark[cand.row_id] = tx
                break

        if not rows_to_mark:
            return

        rows = (
            self.db.query(ImportRow)
            .filter(ImportRow.id.in_(rows_to_mark.keys()))
            .all()
        )
        accounts = {acc.id: acc for acc in self.account_repo.list_by_user(user_id)}

        for row in rows:
            if str(row.status or "") in ("committed", "skipped", "parked"):
                continue
            tx = rows_to_mark[row.id]
            nd: dict = dict(row.normalized_data_json or {})

            # Различаем два типа совпадения:
            #   - mirror match: committed tx живёт на ЧУЖОМ счёте, в наш
            #     индекс попала через target_account_id (зеркало transfer'a).
            #     Это вторая сторона уже-committed пары — is_secondary=True,
            #     partner = tx.account_id (другой счёт, не наш).
            #   - real-duplicate match: committed tx живёт на НАШЕМ счёте
            #     (повторный импорт той же выписки или phantom income из
            #     `_create_transfer_pair_record`). Это «настоящий» дубликат,
            #     UI показывает как «Дубль · другая сессия». is_secondary=False
            #     (иначе UI ошибочно рисует pairLabel и получает self-loop).
            nd_account_id = nd.get("account_id")
            try:
                row_account_id = int(nd_account_id) if nd_account_id is not None else None
            except (TypeError, ValueError):
                row_account_id = None
            is_mirror = (
                row_account_id is not None
                and tx.account_id != row_account_id
            )
            if is_mirror:
                partner_account_id = tx.account_id
            else:
                partner_account_id = tx.target_account_id
            partner_account = (
                accounts.get(int(partner_account_id))
                if partner_account_id is not None
                else None
            )

            nd["transfer_match"] = {
                "matched_row_id": None,
                "matched_tx_id": tx.id,
                "matched_account_id": partner_account_id,
                "matched_account_name": partner_account.name if partner_account else None,
                "match_confidence": 0.95,
                "match_source": "committed_tx_duplicate",
                "is_secondary": is_mirror,
            }
            row.normalized_data_json = nd
            row.status = "duplicate"
            self.db.add(row)

        self.db.flush()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_raw_date(value: Any) -> datetime | None:
        """Parse dates from raw extractor output, e.g. '19.03.2026 23:15:32'."""
        if not value:
            return None
        s = str(value).strip()
        for fmt in (
            "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y %H:%M",
            "%d.%m.%Y",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        # Fallback: try fromisoformat (handles timezone offsets)
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            return None

    @staticmethod
    def _parse_decimal(value: Any) -> Decimal | None:
        try:
            return Decimal(str(value)) if value is not None else None
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            # Normalize to UTC-naive for consistent comparison
            if value.tzinfo is not None:
                return value.astimezone(timezone.utc).replace(tzinfo=None)
            return value
        if not value:
            return None
        s = str(value).strip()
        # Try ISO format first (handles +HH:MM timezone offsets)
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            pass
        # Fallback formats (date-only → treat as midnight UTC)
        for fmt in ("%Y-%m-%d",):
            try:
                return datetime.strptime(s[:10], fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _date_range_of(
        candidates: list[_Candidate],
    ) -> tuple[datetime, datetime] | None:
        dates = [c.date for c in candidates if c.date is not None]
        if not dates:
            return None
        return min(dates), max(dates)

    @staticmethod
    def _extract_contract(nd: dict) -> str | None:
        for key in ("contract_number", "source_reference"):
            val = nd.get(key)
            if val and str(val).strip():
                return str(val).strip()
        return None
