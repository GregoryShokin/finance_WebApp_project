"""Token extraction, skeleton normalization, and fingerprinting for import rows.

Pure functions — no DB, no ORM. Consumed by ImportService in Phase 1.3.

The three public functions form the Phase 1 pipeline:

    tokens   = extract_tokens(description)
    skeleton = normalize_skeleton(description, tokens)
    fp       = fingerprint(bank, account_id, direction, skeleton, tokens.contract)

Two rows with the same fingerprint are considered the same cluster (Phase 3).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation


# ---------------------------------------------------------------------------
# Regex constants
# ---------------------------------------------------------------------------

# Russian mobile numbers. Examples: +79161234567, 89161234567, +7 (916) 123-45-67,
# 8 916 123-45-67. Three-digit operator code always starts with 9 for mobile.
PHONE_RX = re.compile(
    r"(?:\+7|8)\s*\(?\s*9\d{2}\s*\)?[\s\-]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}"
)

# Contract/agreement number. Examples: "№1234567", "№ 1234567", "договор 1234567",
# "договор №1234567", "договора ABC-1234", "contract_id=1234567".
# Allows digits, latin/cyrillic letters, hyphens and slashes (up to 20 chars).
CONTRACT_RX = re.compile(
    r"(?:договор[ауе]?\s*(?:№\s*)?|№\s*|contract[_\s]*id\s*[=:]\s*)"
    r"([A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9\-/]{3,19})",
    re.IGNORECASE,
)

# IBAN: two uppercase letters + two digits + 10..30 alphanumerics (no separators).
# Pre-stripping internal spaces is caller's job if needed.
IBAN_RX = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")

# Masked card: "**** 1234", "*1234", "**** **** **** 1234", "·· 1234".
CARD_MASKED_RX = re.compile(r"(?:[*•·]{1,4}[\s\-]*){1,4}\d{4}\b")

# Full PAN: 16 digits in 4x4 groups. "1234 5678 9012 3456" / "1234-5678-9012-3456".
CARD_FULL_RX = re.compile(r"\b\d{4}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{4}\b")

# Person name — Russian. Handles:
#   "Иванов И.И.", "И.И. Иванов", "И. И. Иванов",
#   "Иванов Иван Иванович", "Иванов Иван".
# Tight to minimize bleeding into org names; still imperfect (see plan risks).
PERSON_NAME_RX = re.compile(
    r"(?:"
    r"[А-Я][а-я]{2,}\s+[А-Я]\.\s*[А-Я]\.?"                                 # Иванов И.И.
    r"|[А-Я]\.\s*[А-Я]\.?\s+[А-Я][а-я]{2,}"                                 # И.И. Иванов
    r"|[А-Я][а-я]{2,}\s+[А-Я][а-я]{2,}\s+[А-Я][а-я]{2,}"                    # Иванов Иван Иванович
    r"|[А-Я][а-я]{2,}\s+[А-Я][а-я]{2,}"                                     # Иванов Иван
    r")"
)

# Organization / legal form. "ООО Ромашка", 'ООО "Рога и копыта"', "ИП Иванов А.А.",
# "ПАО Сбербанк". Captures the legal form + up to a short name fragment.
ORG_RX = re.compile(
    r"(?:ООО|ОАО|ЗАО|ПАО|АО|ИП|НКО|ГУП|МУП)"
    r'(?:\s+"[^"]{1,60}"|\s+[А-ЯA-Z][\wА-Яа-я\-&]{0,40}(?:\s+[А-ЯA-Z][\wА-Яа-я\-&]{0,40}){0,2})?'
)

# Amounts: "1 234,56", "1234.56", "1\xa0000,00". Requires the 2-digit fraction
# so we don't swallow card fragments or contract numbers.
AMOUNT_RX = re.compile(r"\b\d{1,3}(?:[\s\xa0]\d{3})*[.,]\d{2}\b|\b\d+[.,]\d{2}\b")

# Dates. "15.03.2026" (dd.mm.yyyy) and "2026-03-15" (ISO).
DATE_DOT_RX = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
DATE_ISO_RX = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


# Minimal stop-word list. Start narrow — widen only when golden dataset shows need.
STOPWORDS: frozenset[str] = frozenset({
    "руб", "rub", "rur", "р",
    "от", "на", "по", "для", "через", "за", "из",
})


# Keywords that mark a row as "transfer-like" for fingerprint purposes — meaning
# the identifier (phone/contract/card) should participate in the fingerprint in
# its raw form instead of being swallowed by a placeholder.
#
# Kept narrow on purpose: anything matching here pulls the row into the
# identifier-aware branch, which splits one broad cluster ("Внешний перевод по
# номеру телефона") into per-recipient sub-clusters. False positives are
# cheap (over-splitting into smaller clusters), false negatives are
# expensive (all recipients merged into one undistinguishable group).
_TRANSFER_KEYWORDS: tuple[str, ...] = (
    "перевод",
    "transfer",
    "с карты на карту",
    "c2c",
    "внутрибанковский",
    "внешний перевод",
    "внутренний перевод",
)


def is_transfer_like(description: str, operation_type: str | None = None) -> bool:
    """Return True if the row should use identifier-aware fingerprinting.

    Two signals:
      1. `operation_type == "transfer"` — set upstream by the enrichment service
         when bank mechanics or history classify the row as an internal move.
      2. Transfer keyword in the description — catches rows that haven't been
         enriched yet (e.g. cross-session matcher runs before enrichment).
    """
    if (operation_type or "").strip().lower() == "transfer":
        return True
    if not description:
        return False
    lowered = description.lower()
    return any(kw in lowered for kw in _TRANSFER_KEYWORDS)


def pick_transfer_identifier(tokens: ExtractedTokens) -> tuple[str, str] | None:
    """Pick the best identifier to split a transfer cluster by.

    Priority: phone → contract → card → iban. The first present wins — all of
    them uniquely identify the counterparty, and banks typically provide only
    one. `None` means "no identifier available" — caller should fall back to
    plain fingerprint (which will over-merge, but there's nothing to split on).
    """
    if tokens.phone:
        return ("phone", tokens.phone)
    if tokens.contract:
        return ("contract", tokens.contract)
    if tokens.card:
        return ("card", tokens.card)
    if tokens.iban:
        return ("iban", tokens.iban)
    return None


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractedTokens:
    """Structured identifiers lifted out of a free-form description."""

    phone: str | None = None
    contract: str | None = None
    iban: str | None = None
    card: str | None = None
    person_name: str | None = None
    counterparty_org: str | None = None
    amounts: tuple[Decimal, ...] = field(default_factory=tuple)
    dates: tuple[date, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# extract_tokens
# ---------------------------------------------------------------------------


def extract_tokens(description: str) -> ExtractedTokens:
    """Scan `description` for structured identifiers. First match wins per field."""
    if not description:
        return ExtractedTokens()

    description = _prepare(description)

    phone_m = PHONE_RX.search(description)
    contract_m = CONTRACT_RX.search(description)
    iban_m = IBAN_RX.search(description)
    card_m = CARD_MASKED_RX.search(description) or CARD_FULL_RX.search(description)
    person_m = PERSON_NAME_RX.search(description)
    org_m = ORG_RX.search(description)

    amounts: list[Decimal] = []
    for m in AMOUNT_RX.finditer(description):
        raw = m.group(0).replace("\xa0", "").replace(" ", "").replace(",", ".")
        try:
            amounts.append(Decimal(raw))
        except InvalidOperation:
            continue

    dates: list[date] = []
    for m in DATE_DOT_RX.finditer(description):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dates.append(date(y, mo, d))
        except ValueError:
            continue
    for m in DATE_ISO_RX.finditer(description):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dates.append(date(y, mo, d))
        except ValueError:
            continue

    return ExtractedTokens(
        phone=_normalize_phone(phone_m.group(0)) if phone_m else None,
        contract=contract_m.group(1) if contract_m else None,
        iban=iban_m.group(0) if iban_m else None,
        card=card_m.group(0).strip() if card_m else None,
        person_name=person_m.group(0) if person_m else None,
        counterparty_org=org_m.group(0) if org_m else None,
        amounts=tuple(amounts),
        dates=tuple(dates),
    )


def _normalize_phone(raw: str) -> str:
    """Strip separators; keep a single leading '+' if present."""
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("8") and len(digits) == 11:
        digits = "+7" + digits[1:]
    return digits


# ---------------------------------------------------------------------------
# normalize_skeleton
# ---------------------------------------------------------------------------

_PLACEHOLDER_RESTORE_RX = re.compile(
    r"<(phone|contract|iban|card|person|org|amount|date)>"
)
_PUNCT_RX = re.compile(r"[^\w\s<>]", re.UNICODE)
_WHITESPACE_RX = re.compile(r"\s+")


def _prepare(description: str) -> str:
    """Collapse all whitespace (incl. NBSP/tabs/newlines) to single spaces.

    Lets token regexes work on IBAN-with-spaces, multi-line descriptions,
    and PDF-extracted text without embedding \\s+ in every pattern.
    """
    return _WHITESPACE_RX.sub(" ", description).strip()


def normalize_skeleton(description: str, extracted: ExtractedTokens) -> str:
    """Return a lowercased, placeholder-anchored skeleton for fingerprinting.

    Steps (fixed order):
      1. replace extracted tokens with uppercase placeholders
      2. lowercase the rest
      3. restore placeholders back to uppercase
      4. drop punctuation (keeps word chars, whitespace, angle brackets)
      5. drop minimal stop-words
      6. collapse whitespace, strip

    Passing `extracted` is forward-looking: current implementation re-runs the
    same regexes for substitution. In Phase 1.4 we may switch to span-based
    replacement driven by `extracted` if regex duplication costs bite.
    """
    if not description:
        return ""

    text = _prepare(description)

    # Order matters: longer / more specific patterns first so they consume
    # substrings before narrower patterns see them.
    text = CARD_FULL_RX.sub("<CARD>", text)
    text = CARD_MASKED_RX.sub("<CARD>", text)
    text = IBAN_RX.sub("<IBAN>", text)
    text = PHONE_RX.sub("<PHONE>", text)
    text = DATE_DOT_RX.sub("<DATE>", text)
    text = DATE_ISO_RX.sub("<DATE>", text)
    text = CONTRACT_RX.sub("<CONTRACT>", text)
    text = ORG_RX.sub("<ORG>", text)
    text = PERSON_NAME_RX.sub("<PERSON>", text)
    text = AMOUNT_RX.sub("<AMOUNT>", text)

    text = text.lower()

    text = _PLACEHOLDER_RESTORE_RX.sub(lambda m: f"<{m.group(1).upper()}>", text)

    text = _PUNCT_RX.sub(" ", text)

    words = [w for w in text.split() if w not in STOPWORDS]

    return _WHITESPACE_RX.sub(" ", " ".join(words)).strip()


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------


def fingerprint(
    bank: str,
    account_id: int,
    direction: str,
    skeleton: str,
    contract: str | None = None,
    transfer_identifier: tuple[str, str] | None = None,
) -> str:
    """Deterministic 16-hex-char hash over the cluster-defining inputs.

    `contract` is included only when present — None values would otherwise
    cross-pollute rows that genuinely share the other four inputs.

    `transfer_identifier` is a `(kind, value)` pair (e.g. `("phone", "+79…")`)
    that participates in the payload in raw form. Use this for transfer-like
    rows so that `Внешний перевод на +79161111111` and `Внешний перевод на
    +79162222222` end up in different clusters — the skeleton masks the phone
    as `<PHONE>`, which would otherwise merge all transfers into one.

    When `transfer_identifier` is given **and** its `kind == "contract"`, the
    separate `contract` positional arg is ignored to avoid double-including
    the same value.
    """
    parts = [bank, str(account_id), direction, skeleton]
    if transfer_identifier is not None:
        kind, value = transfer_identifier
        parts.append(f"transfer:{kind}:{value}")
        if kind == "contract":
            # Identifier already carries the contract; don't double-append.
            contract = None
    if contract:
        parts.append(contract)
    payload = "|".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]
