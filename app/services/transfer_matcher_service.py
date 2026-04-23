"""
Cross-session transfer matcher.

After each build_preview, this service scans all active (uncommitted) ImportRow
records for the user and finds pairs that represent two sides of the same transfer.
It also checks already-committed transactions so that when the second half of a
transfer arrives in a new session it is immediately flagged.

Matching criteria (all required):
  1. Amounts are exactly equal.
  2. Directions are opposite (expense ↔ income).
  3. Date/time difference is at most 36 hours.
  4. Rows belong to different sessions (different accounts).

Scoring:
  • time_diff == 0 s  → 1.00
  • time_diff ≤ 60 s  → 0.97
  • time_diff ≤ 1 h   → 0.93
  • time_diff ≤ 24 h  → 0.88
  • time_diff ≤ 36 h  → 0.72
  Bonus +0.05 if both sides share the same contract_number.

Pairs with score < MIN_SCORE are discarded.
Greedy 1-to-1 assignment (highest score first).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.transaction import Transaction as TransactionModel
from app.repositories.account_repository import AccountRepository
from app.repositories.import_repository import ImportRepository
from app.repositories.transaction_repository import TransactionRepository

MIN_SCORE = 0.60
MAX_DATE_DIFF_HOURS = 12

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

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_active_row_candidates(self, user_id: int) -> list[_Candidate]:
        rows_with_sessions = (
            self.db.query(ImportSession, ImportRow)
            .join(ImportRow, ImportRow.session_id == ImportSession.id)
            .filter(
                ImportSession.user_id == user_id,
                ImportSession.status != "committed",
                ImportSession.account_id.isnot(None),
                ImportRow.status.in_(["ready", "warning"]),
            )
            .all()
        )

        candidates: list[_Candidate] = []
        for session, row in rows_with_sessions:
            nd: dict = row.normalized_data_json or {}

            if nd.get("transfer_match_locked"):
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
                ))

        return candidates

    def _load_committed_candidates(
        self, user_id: int, date_from: datetime, date_to: datetime
    ) -> list[_Candidate]:
        buffer = timedelta(days=2)
        # date_from/date_to are UTC-naive; DB stores timezone-aware values.
        # Cast to UTC-aware for the DB filter to avoid comparison errors.
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
        if diff_seconds > MAX_DATE_DIFF_HOURS * 3600:
            return 0.0

        if diff_seconds == 0:
            score = 1.00
        elif diff_seconds <= 60:
            score = 0.97
        elif diff_seconds <= 3600:
            score = 0.93
        elif diff_seconds <= 86400:
            score = 0.88
        else:
            score = 0.72

        if (
            a.contract_number
            and b.contract_number
            and a.contract_number == b.contract_number
        ):
            score = min(1.0, score + 0.05)

        # Penalize pairs where either side looks like a scheduled payment,
        # not an inter-account transfer.
        if self._has_anti_transfer_keyword(a) or self._has_anti_transfer_keyword(b):
            score *= 0.4

        return round(score, 4)

    @staticmethod
    def _has_anti_transfer_keyword(c: _Candidate) -> bool:
        if not c.description:
            return False
        return any(kw in c.description for kw in _ANTI_TRANSFER_KEYWORDS)

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
        # Collect updates AND track which row is the secondary side of a cross-session pair.
        # When two active ImportRows are paired, committing the EXPENSE side creates the
        # matching INCOME side automatically via transfer-pair creation. So the INCOME
        # side must be marked "duplicate" to prevent double-commit.
        row_updates: dict[int, tuple[_Candidate, float, bool]] = {}  # bool: is_secondary
        for a, b, score in assignments:
            a_is_row = a.row_id is not None
            b_is_row = b.row_id is not None
            # Secondary side (the one that will be auto-created by the pair's other side):
            # - Always the INCOME side, IF both sides are active import rows.
            # - If only one side is an active row, it's primary (other is committed tx or analyzed session).
            both_rows = a_is_row and b_is_row
            a_is_secondary = both_rows and a.direction == "income"
            b_is_secondary = both_rows and b.direction == "income"
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
            # Secondary side (income in paired cross-session match) is marked duplicate —
            # committing the expense side auto-creates this side as the transfer pair.
            row.status = "duplicate" if is_secondary else "ready"

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
