"""Fee-aware suspect-pair matcher (spec §8.10, v1.20).

Runs as a second-pass after `TransferMatcherService` on rows that did NOT
get matched in the main exact-amount transfer matcher. Detects cross-bank
transfers where the sender bank withheld a fee — the source side shows
−37 000 ₽, the destination side shows +36 943 ₽, with the same minute and
opposite directions. This is a known SBP / fast-payment pattern.

Behavior is deliberately conservative:
  • Asymmetric on direction (delta only when income < expense; the reverse
    is treated as data-quality issue, see §8.11).
  • Tight tolerance: delta ≤ min(5%, 500 ₽).
  • Tight time-window: |Δseconds| ≤ 60.
  • Both sides must contain a transfer keyword.
  • Anti-transfer keyword on either side → reject.
  • Identifier-mismatch one type (contract / phone / iban) → reject.

Output is a `fee_suspect_pair` dict written into both rows'
`normalized_data_json`. Status of either row is NOT changed automatically
— the user explicitly confirms in UI; on confirm, `TransferLinkingService`
creates a transfer pair on min(amount_a, amount_b) plus a separate expense
fee transaction in the «Банковские комиссии» system category.

The matcher is greedy 1-to-1: each row participates in at most one suspect
pair, and the pair with smallest |Δseconds| wins on conflict.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.import_row import ImportRow
from app.models.import_session import ImportSession
from app.models.account import Account as AccountModel
from app.repositories.account_repository import AccountRepository
from app.services.import_normalizer_v2 import (
    extract_tokens as _extract_tokens,
    ANTI_TRANSFER_KEYWORDS,
)


MAX_DELTA_PCT = 0.05         # 5 %
MAX_DELTA_ABS = Decimal("500.00")
MAX_TIME_DIFF_SECONDS = 60   # «то же время до минуты»
MIN_CONFIDENCE = 0.80

_TRANSFER_KEYWORDS = frozenset({
    "перевод",
    "transfer",
    "сбп",
    "fast payment",
    "пополнение",
    "с карты на карту",
    "card to card",
    "card-to-card",
    "c2c",
    "межбанковский",
    "внутрибанковский",
})


@dataclass(frozen=True)
class FeeSuspectPair:
    """Read-only view of a candidate fee-aware pair."""

    expense_row_id: int
    income_row_id: int
    expense_account_id: int
    income_account_id: int
    expense_amount: Decimal
    income_amount: Decimal
    delta_amount: Decimal
    delta_pct: float
    confidence: float
    diff_seconds: float
    reasons: tuple[str, ...]


@dataclass
class _Side:
    row_id: int
    session_id: int
    account_id: int
    direction: str
    amount: Decimal
    date: datetime
    description: str
    skeleton: str


def _has_keyword(text: str, keywords) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(kw in lowered for kw in keywords)


def _identifier_mismatch(a_desc: str, b_desc: str) -> bool:
    a_t = _extract_tokens(a_desc)
    b_t = _extract_tokens(b_desc)
    for attr in ("contract", "phone", "iban"):
        a_v = getattr(a_t, attr, None)
        b_v = getattr(b_t, attr, None)
        if a_v and b_v and a_v != b_v:
            return True
    return False


def _identifier_match_count(a_desc: str, b_desc: str) -> int:
    a_t = _extract_tokens(a_desc)
    b_t = _extract_tokens(b_desc)
    n = 0
    for attr in ("contract", "phone", "iban"):
        a_v = getattr(a_t, attr, None)
        b_v = getattr(b_t, attr, None)
        if a_v and b_v and a_v == b_v:
            n += 1
    return n


class FeeMatcherService:
    def __init__(self, db: Session):
        self.db = db
        self.account_repo = AccountRepository(db)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def detect_for_user(self, *, user_id: int) -> list[FeeSuspectPair]:
        """Find fee-aware suspect pairs across active uncommitted import rows.

        Side effect: writes `fee_suspect_pair` into both rows of each
        accepted pair. Does NOT change row.status. Returns the list of
        accepted pairs for diagnostics / future UI direct-rendering.
        """
        sides = self._load_unmatched_active_sides(user_id=user_id)
        if len(sides) < 2:
            return []

        # First clear any stale fee_suspect_pair fields — the matcher should
        # be idempotent on re-runs after the user touches preview.
        self._reset_fee_suspect_pairs(user_id=user_id)

        proposals = self._enumerate_proposals(sides)
        if not proposals:
            return []

        pairs = self._greedy_assign(proposals)
        if not pairs:
            return []

        self._write_pairs(pairs)
        return pairs

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_unmatched_active_sides(self, *, user_id: int) -> list[_Side]:
        """Active rows in non-committed sessions, NOT already matched as
        transfer (transfer_match empty), with valid amount/date/account.

        We reuse the same eligibility window as the main matcher: status
        IN ('ready','warning'), session not committed, no existing
        transfer_match. Rows with `error` status are excluded — they're
        already in a broken state and shouldn't be promoted via fee-pair.
        """
        rows_with_sessions = (
            self.db.query(ImportSession, ImportRow)
            .join(ImportRow, ImportRow.session_id == ImportSession.id)
            .filter(
                ImportSession.user_id == user_id,
                ImportSession.status != "committed",
                ImportSession.account_id.isnot(None),
                ImportRow.status.in_(("ready", "warning")),
            )
            .all()
        )

        sides: list[_Side] = []
        for session, row in rows_with_sessions:
            nd: dict = dict(row.normalized_data_json or {})
            # Skip rows that are already matched as transfer (the main
            # matcher already accepted them) — fee-pair is for unmatched
            # leftovers only.
            tm = nd.get("transfer_match")
            if tm and isinstance(tm, dict) and (
                tm.get("matched_row_id") is not None
                or tm.get("matched_tx_id") is not None
            ):
                continue
            if str(nd.get("operation_type") or "") == "transfer":
                # User or matcher already classified as transfer; don't
                # offer a fee-suspect on top.
                continue

            account_id = nd.get("account_id") or session.account_id
            if account_id is None:
                continue
            try:
                account_id = int(account_id)
            except (TypeError, ValueError):
                continue

            amount_raw = nd.get("amount")
            if amount_raw is None:
                continue
            try:
                amount = Decimal(str(amount_raw))
            except Exception:
                continue
            if amount <= 0:
                continue

            direction = str(nd.get("direction") or "").lower()
            if direction not in ("income", "expense"):
                continue

            date_raw = nd.get("date") or nd.get("transaction_date")
            if date_raw is None:
                continue
            try:
                date = datetime.fromisoformat(str(date_raw))
            except (TypeError, ValueError):
                continue

            description = str(nd.get("description") or "")
            skeleton = str(nd.get("skeleton") or "")

            sides.append(_Side(
                row_id=row.id,
                session_id=session.id,
                account_id=account_id,
                direction=direction,
                amount=amount,
                date=date,
                description=description,
                skeleton=skeleton,
            ))
        return sides

    def _reset_fee_suspect_pairs(self, *, user_id: int) -> None:
        rows = (
            self.db.query(ImportRow)
            .join(ImportSession, ImportRow.session_id == ImportSession.id)
            .filter(
                ImportSession.user_id == user_id,
                ImportSession.status != "committed",
            )
            .all()
        )
        touched = 0
        for row in rows:
            nd: dict = dict(row.normalized_data_json or {})
            if "fee_suspect_pair" in nd:
                # Preserve user-rejected flag so the same pair isn't
                # re-proposed indefinitely.
                pair = nd.get("fee_suspect_pair") or {}
                if pair.get("user_rejected"):
                    continue
                nd.pop("fee_suspect_pair", None)
                row.normalized_data_json = nd
                self.db.add(row)
                touched += 1
        if touched:
            self.db.flush()

    # ------------------------------------------------------------------
    # Enumeration
    # ------------------------------------------------------------------

    def _enumerate_proposals(self, sides: list[_Side]) -> list[FeeSuspectPair]:
        """Build all candidate (expense, income) pairs satisfying §8.10."""
        expenses = [s for s in sides if s.direction == "expense"]
        incomes = [s for s in sides if s.direction == "income"]
        proposals: list[FeeSuspectPair] = []

        for exp in expenses:
            if _has_keyword(exp.description, ANTI_TRANSFER_KEYWORDS):
                continue
            if not (
                _has_keyword(exp.description, _TRANSFER_KEYWORDS)
                or _has_keyword(exp.skeleton, _TRANSFER_KEYWORDS)
            ):
                continue

            for inc in incomes:
                if exp.account_id == inc.account_id:
                    # Same account — refund-pair territory, not fee-transfer.
                    continue
                if exp.session_id == inc.session_id:
                    # Same session — within-session expense+income pair on
                    # different accounts of the same statement is impossible
                    # by construction (one statement = one account).
                    continue
                if inc.amount >= exp.amount:
                    # §8.10 / §8.11: only b.amount < a.amount is in scope.
                    continue
                if _has_keyword(inc.description, ANTI_TRANSFER_KEYWORDS):
                    continue
                if not (
                    _has_keyword(inc.description, _TRANSFER_KEYWORDS)
                    or _has_keyword(inc.skeleton, _TRANSFER_KEYWORDS)
                ):
                    continue

                delta = exp.amount - inc.amount
                if delta > MAX_DELTA_ABS:
                    continue
                delta_pct = float(delta / exp.amount)
                if delta_pct > MAX_DELTA_PCT:
                    continue

                diff_seconds = abs((exp.date - inc.date).total_seconds())
                if diff_seconds > MAX_TIME_DIFF_SECONDS:
                    continue

                if _identifier_mismatch(exp.description, inc.description):
                    continue

                # Confidence: base 0.80; +0.10 for identifier-match;
                # +0.05 for sub-second time alignment.
                confidence = 0.80
                id_matches = _identifier_match_count(exp.description, inc.description)
                if id_matches:
                    confidence += min(0.15, 0.10 * id_matches)
                if diff_seconds <= 5:
                    confidence += 0.05
                confidence = min(0.95, confidence)

                if confidence < MIN_CONFIDENCE:
                    continue

                reasons: list[str] = ["amount_with_fee", "time_aligned"]
                if id_matches:
                    reasons.append("identifier_match")
                if diff_seconds == 0:
                    reasons.append("exact_time")

                proposals.append(FeeSuspectPair(
                    expense_row_id=exp.row_id,
                    income_row_id=inc.row_id,
                    expense_account_id=exp.account_id,
                    income_account_id=inc.account_id,
                    expense_amount=exp.amount,
                    income_amount=inc.amount,
                    delta_amount=delta,
                    delta_pct=delta_pct,
                    confidence=confidence,
                    diff_seconds=diff_seconds,
                    reasons=tuple(reasons),
                ))

        return proposals

    # ------------------------------------------------------------------
    # Greedy 1-to-1 assignment
    # ------------------------------------------------------------------

    def _greedy_assign(self, proposals: list[FeeSuspectPair]) -> list[FeeSuspectPair]:
        # Highest confidence wins; tie-break by smallest |Δseconds|.
        proposals.sort(key=lambda p: (-p.confidence, p.diff_seconds))
        used_expense: set[int] = set()
        used_income: set[int] = set()
        accepted: list[FeeSuspectPair] = []
        for p in proposals:
            if p.expense_row_id in used_expense or p.income_row_id in used_income:
                continue
            accepted.append(p)
            used_expense.add(p.expense_row_id)
            used_income.add(p.income_row_id)
        return accepted

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def _write_pairs(self, pairs: list[FeeSuspectPair]) -> None:
        if not pairs:
            return
        row_ids = {p.expense_row_id for p in pairs} | {p.income_row_id for p in pairs}
        rows = (
            self.db.query(ImportRow)
            .filter(ImportRow.id.in_(row_ids))
            .all()
        )
        rows_by_id = {row.id: row for row in rows}
        accounts: dict[int, AccountModel] = {}

        def _get_account(account_id: int) -> AccountModel | None:
            cached = accounts.get(account_id)
            if cached is not None:
                return cached
            acc = self.db.query(AccountModel).filter(AccountModel.id == account_id).first()
            if acc is not None:
                accounts[account_id] = acc
            return acc

        for p in pairs:
            for own_id, partner_id, partner_account_id, side in (
                (p.expense_row_id, p.income_row_id, p.income_account_id, "expense"),
                (p.income_row_id, p.expense_row_id, p.expense_account_id, "income"),
            ):
                row = rows_by_id.get(own_id)
                if row is None:
                    continue
                nd: dict = dict(row.normalized_data_json or {})
                # Don't overwrite a user-rejected suspect on the same partner.
                existing = nd.get("fee_suspect_pair") or {}
                if (
                    existing.get("user_rejected")
                    and existing.get("partner_row_id") == partner_id
                ):
                    continue
                partner_account = _get_account(partner_account_id)
                nd["fee_suspect_pair"] = {
                    "side": side,
                    "partner_row_id": partner_id,
                    "partner_account_id": partner_account_id,
                    "partner_account_name": partner_account.name if partner_account else None,
                    "expense_amount": str(p.expense_amount),
                    "income_amount": str(p.income_amount),
                    "delta_amount": str(p.delta_amount),
                    "delta_pct": p.delta_pct,
                    "confidence": p.confidence,
                    "diff_seconds": p.diff_seconds,
                    "reasons": list(p.reasons),
                    "suggested_action": "transfer_with_fee",
                    "user_rejected": False,
                }
                row.normalized_data_json = nd
                self.db.add(row)
        self.db.flush()
