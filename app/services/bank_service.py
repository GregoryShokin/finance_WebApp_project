"""Whitelist sync for bank extractor support (Этап 1 MVP launch).

The list of banks for which we have a tested extractor lives as a constant
here, not in a migration — promoting a bank from 'pending' to 'supported'
is a code change in this file, not a schema change. ensure_extractor_status_baseline
is called on FastAPI startup and reconciles the table with the constant.

Manual statuses ('in_review' for parsers in active development, 'broken' for
extractors that regressed after a bank changed format) are preserved across
reconciliations — only the 'pending' ↔ 'supported' transitions are managed
automatically.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.bank import Bank


# Bank codes (matches `banks.code` column from migration 0045) that have a
# tested import extractor as of the latest sync.
#
# Notes for each entry live in `Bank.extractor_notes` after baseline runs —
# below is the audit trail used at sync time. When you add a bank here,
# also bump `_EXTRACTOR_NOTES` so the auto-populated note matches reality.
SUPPORTED_BANK_CODES: frozenset[str] = frozenset({"sber", "tbank", "ozon", "yandex"})


_EXTRACTOR_NOTES: dict[str, str] = {
    "sber":   "PDF (sber_pdf_v1)",
    "tbank":  "PDF (generic block parser; TBANK_START_RX)",
    "ozon":   "PDF (generic block parser + ozon datetime merge)",
    "yandex": "PDF (yandex_bank_pdf_v1, yandex_credit_pdf_v1)",
}


class BankService:
    def __init__(self, db: Session):
        self.db = db

    def ensure_extractor_status_baseline(self) -> dict[str, int]:
        """Reconcile `banks.extractor_status` with `SUPPORTED_BANK_CODES`.

        Idempotent. Returns a counter dict for logging/tests:
        `{"promoted": N, "demoted": M, "untouched_manual": K, "noop": L}`.

        Rules:
          - code in SUPPORTED_BANK_CODES, status == 'pending'   → 'supported' (promote)
          - code NOT in SUPPORTED_BANK_CODES, status == 'supported' → 'pending' (demote, symmetric)
          - status in {'in_review', 'broken'} → never touched (manual override)
          - everything else → noop

        `extractor_notes` is set on promote so future grep tells you which
        parser handles the bank. On demote the note is cleared.
        """
        counters = {"promoted": 0, "demoted": 0, "untouched_manual": 0, "noop": 0}
        banks = self.db.query(Bank).all()
        for bank in banks:
            in_whitelist = bank.code in SUPPORTED_BANK_CODES
            status = bank.extractor_status

            if status in ("in_review", "broken"):
                counters["untouched_manual"] += 1
                continue

            if in_whitelist and status == "pending":
                bank.extractor_status = "supported"
                bank.extractor_notes = _EXTRACTOR_NOTES.get(bank.code)
                counters["promoted"] += 1
            elif not in_whitelist and status == "supported":
                bank.extractor_status = "pending"
                bank.extractor_notes = None
                counters["demoted"] += 1
            else:
                counters["noop"] += 1

        if counters["promoted"] or counters["demoted"]:
            self.db.commit()
        return counters
