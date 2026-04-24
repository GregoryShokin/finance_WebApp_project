"""Refund/return pair matcher (Phase 3.8 of И-08).

Given a list of import rows (within one session), find pairs of rows where:
  - Amounts are exactly equal.
  - Directions are opposite (one expense, one income).
  - Date difference is ≤ 14 days.
  - They look like a purchase + its reversal: ideally the same counterparty or
    description skeleton.

This differs from TransferMatcherService:
  - Refunds happen within ONE account (not between two) — no anti-transfer
    keyword penalty, no cross-session matching.
  - Window is ±14 days (vs. ±36 hours for transfers).
  - Output is "this row has a refund partner" metadata on both sides — not
    a status change. The commit stays at the user's discretion (they can
    commit both with separate categories, or park the pair, etc.).

Confidence bands:
  - 0.95 — strong signal: same counterparty_org token, or same person_hash,
    or same contract_number, or matching refund keyword ("возврат", "refund").
  - 0.80 — medium: same skeleton (normalized description); no explicit
    identifier.
  - 0.60 — weak: amount+direction+window only. Below this we don't emit.

The matcher is side-effect-free: it returns candidate pairs, and the caller
decides what to write. This keeps the service testable and lets Phase 5
moderator UI surface the pairs without committing to a label.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from app.services.brand_extractor_service import extract_brand

MAX_DATE_DIFF_DAYS = 14
MIN_CONFIDENCE = 0.60

# Russian/English refund keywords that lift confidence when matched.
_REFUND_KEYWORDS = frozenset({
    "возврат",
    "refund",
    "reversal",
    "отмена",
    "chargeback",
    "return",
})


@dataclass(frozen=True)
class RefundMatch:
    """Read-only view of a candidate refund pair."""

    expense_row_id: int
    income_row_id: int
    amount: Decimal
    confidence: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "expense_row_id": self.expense_row_id,
            "income_row_id": self.income_row_id,
            "amount": str(self.amount),
            "confidence": self.confidence,
            "reasons": list(self.reasons),
        }


@dataclass
class _Candidate:
    row_id: int
    amount: Decimal
    direction: str  # "income" | "expense"
    date: datetime
    description: str
    skeleton: str
    counterparty_org: str | None
    person_hash: str | None
    contract: str | None


class RefundMatcherService:
    """Pure service: takes rows (as dicts) and returns matches. No DB writes."""

    def match(self, rows: list[dict[str, Any]]) -> list[RefundMatch]:
        """Find refund pairs among a list of normalized row dicts.

        Each input dict must contain:
          - `row_id: int`
          - `amount: Decimal | str`
          - `direction: str` (income / expense)
          - `transaction_date: datetime | str (ISO)`
          - `description: str` (optional, default "")
          - `skeleton: str` (optional, default "")
          - `tokens: dict` (optional; may contain counterparty_org / person_hash / contract)

        Rows missing any of amount/direction/date are skipped silently.
        """
        candidates = [c for c in (_to_candidate(row) for row in rows) if c is not None]

        expenses = [c for c in candidates if c.direction == "expense"]
        incomes = [c for c in candidates if c.direction == "income"]

        pairs: list[tuple[RefundMatch, float]] = []
        for exp in expenses:
            for inc in incomes:
                if exp.amount != inc.amount:
                    continue
                if abs((exp.date - inc.date).total_seconds()) > MAX_DATE_DIFF_DAYS * 86400:
                    continue
                confidence, reasons = _score(exp, inc)
                if confidence < MIN_CONFIDENCE:
                    continue
                match = RefundMatch(
                    expense_row_id=exp.row_id,
                    income_row_id=inc.row_id,
                    amount=exp.amount,
                    confidence=confidence,
                    reasons=tuple(reasons),
                )
                pairs.append((match, confidence))

        # Greedy 1-to-1: highest confidence wins; a row participates in at most
        # one pair. This prevents one refund from being claimed by two
        # candidates when amounts collide by chance.
        pairs.sort(key=lambda p: -p[1])
        used: set[int] = set()
        result: list[RefundMatch] = []
        for match, _ in pairs:
            if match.expense_row_id in used or match.income_row_id in used:
                continue
            used.add(match.expense_row_id)
            used.add(match.income_row_id)
            result.append(match)
        return result


# ---------------------------------------------------------------------------
# Helpers (module-level for testability)
# ---------------------------------------------------------------------------


def _to_candidate(row: dict[str, Any]) -> _Candidate | None:
    try:
        row_id = int(row["row_id"])
        amount = Decimal(str(row["amount"]))
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None

    direction = str(row.get("direction") or "").lower()
    if direction not in ("income", "expense"):
        return None

    raw_date = row.get("transaction_date")
    date = _coerce_datetime(raw_date)
    if date is None:
        return None

    tokens = row.get("tokens") or {}
    return _Candidate(
        row_id=row_id,
        amount=amount,
        direction=direction,
        date=date,
        description=str(row.get("description") or ""),
        skeleton=str(row.get("skeleton") or ""),
        counterparty_org=(tokens.get("counterparty_org") or None),
        person_hash=(tokens.get("person_hash") or None),
        contract=(tokens.get("contract") or None),
    )


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _score(exp: _Candidate, inc: _Candidate) -> tuple[float, list[str]]:
    """Return (confidence, list of reasons) for a matched expense/income pair.

    The highest-priority signal wins — we don't stack boosts, because double-
    boosting a noisy pair is more dangerous than under-boosting a clear one.
    """
    reasons: list[str] = []

    if exp.contract and inc.contract and exp.contract == inc.contract:
        reasons.append("same_contract")
        return 0.95, reasons

    if exp.person_hash and inc.person_hash and exp.person_hash == inc.person_hash:
        reasons.append("same_person")
        return 0.95, reasons

    if exp.counterparty_org and inc.counterparty_org and exp.counterparty_org == inc.counterparty_org:
        reasons.append("same_counterparty_org")
        return 0.95, reasons

    # Refund keyword is a strong signal, but it ONLY identifies the income side
    # as a reversal — it does NOT guarantee the expense side is the correct
    # purchase. Without a merchant/brand match, a 700₽ POPLAVO purchase can be
    # wrongly bundled with a 700₽ "Отмена оплаты KOFEMOLOKO" just because both
    # happened on the same day. Require a merchant signal on top of the keyword.
    has_refund_kw = _has_refund_keyword(inc.description) or _has_refund_keyword(exp.description)
    exp_brand = extract_brand(exp.skeleton) if exp.skeleton else None
    inc_brand = extract_brand(inc.skeleton) if inc.skeleton else None
    brands_match = bool(exp_brand and inc_brand and exp_brand == inc_brand)

    if has_refund_kw and brands_match:
        reasons.append("refund_keyword")
        reasons.append("same_brand")
        return 0.95, reasons

    if exp.skeleton and inc.skeleton and exp.skeleton == inc.skeleton:
        reasons.append("same_skeleton")
        return 0.80, reasons

    if has_refund_kw and not brands_match:
        # Keyword-only — treat as weak hint. Falls below MIN_CONFIDENCE and is
        # dropped, so accidental pairs across merchants don't auto-label.
        reasons.append("refund_keyword_no_brand")
        return 0.50, reasons

    if brands_match:
        # Same brand, no keyword — still a plausible purchase↔refund pair but
        # weaker than keyword+brand.
        reasons.append("same_brand")
        return 0.75, reasons

    # Window + amount + direction only — weak but still worth surfacing.
    reasons.append("amount_and_window")
    return 0.60, reasons


def _has_refund_keyword(description: str) -> bool:
    if not description:
        return False
    low = description.lower()
    return any(kw in low for kw in _REFUND_KEYWORDS)
