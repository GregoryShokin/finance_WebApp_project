"""Brand key extraction for bulk-cluster grouping (И-08 Этап 2).

Pure functions — no DB, no ORM. Consumed by `ImportClusterService` to build
the second layer of cluster hierarchy: many per-TT fingerprints collapsed
into a single brand-level group.

The brand key is a lowercase bare brand name derived from the skeleton. It
is **not** stored or indexed — it is recomputed on demand during cluster
assembly. Rules are still written at the fingerprint level; brand is a UI
grouping only (see `project_bulk_clusters.md`).

Design notes:
  * False positives (two unrelated rows collapsing into one brand) are worse
    than false negatives (one real brand split across several). Be
    conservative — extract only when we're confident the first significant
    token is a brand.
  * No fuzzy matching (levenshtein). If the bank writes "ПЯТЁРОЧКА" one day
    and "ПЯТЕРОЧКА" another day, that's a fingerprint-level concern (both
    normalize to `pyaterochka` after lowercasing/transliteration in the
    skeleton pipeline).
"""
from __future__ import annotations

import re


# Filler tokens that never count as a brand. Seen on session 204:
#   "rus", "volgodonsk", "moscow" — locale/city suffixes
#   "gm", "mm" — Magnit format codes (gipermarket, mini-market)
#   "ip", "ooo", "pao" — legal forms
#   "md" — bank-internal routing code (seen on "MD.*IP DRUGOV")
#   "<org>", "<person>" — placeholders from skeleton normalization
#
# Any token consisting only of digits is also rejected (it's almost always a
# TT or receipt number, not a brand).
_FILLER_TOKENS: frozenset[str] = frozenset({
    # Legal forms
    "ooo", "ao", "pao", "oao", "zao", "ip", "nko",
    # Russian legal forms (in case skeleton preserves cyrillic)
    "ооо", "ао", "пао", "оао", "зао", "ип", "нко",
    # Locale / city tokens common in RU bank statements
    "rus", "ru", "russia", "russian", "federation",
    "moscow", "moskva", "volgodonsk", "spb", "piter",
    "rostov", "krasnodar", "sochi", "ekb", "kazan", "novosib",
    # Magnit-style format codes
    "gm", "mm", "hm",
    # Noise seen in practice
    "md", "mop", "sbp", "сбп", "qsr",
    # Generic service/utility words — not brands. Russian inflected forms of
    # "сервис" so "оплата сервиса Яндекса" resolves to "яндекс", not "сервиса".
    "сервис", "сервиса", "сервисе", "сервисов", "сервисам", "сервисами", "сервисах", "сервисы",
    # Mobile banking app prefixes — not brands
    "mbank", "мбанк",
    # Payment-method / card / transaction-type words
    "pos", "atm", "retail", "card", "payment", "visa", "mastercard", "mir",
    "оплата", "оплаты", "оплате", "оплату",
    "платёж", "платежа", "платежу", "платеж",
    "покупка", "покупки", "покупке", "покупку",
    "услуг", "услуга", "услуги", "услуге", "услугу", "услугами", "услугах",
    # Generic product/goods words — same trap as «услуг». A row like "Оплата
    # товаров и услуг yandex*5399*market" must not auto-learn «товаров» as a
    # brand text-pattern (false positive: every "Оплата товаров..." row gets
    # stamped with whatever brand the first one was confirmed under).
    "товар", "товара", "товару", "товаром", "товаре",
    "товары", "товаров", "товарам", "товарами", "товарах",
    "в",
    # Refund / reversal keywords — these describe the transaction KIND, not
    # the merchant. Required so refund rows like "Отмена операции оплаты
    # KOFEMOLOKO" resolve to brand "kofemoloko" (not "отмена") and can be
    # paired against their matching purchase.
    "возврат", "refund", "reversal", "отмена", "chargeback", "return",
    "операции", "операция",
    # Banking-statement wrapper lexicon (spec v1.27). Russian banks include
    # boilerplate like «Оплата товаров и услуг по кредитной карте 7497 сумма
    # 1266.00 в YM*vkusnoitochka MOSKVA RU дата 2026 04-18 время 17:46:23».
    # Without filtering these, `extract_brand` happily returns the first
    # noun («товаров») as a brand candidate, which then gets auto-learned
    # as a private pattern matching every future statement of the same
    # wording. The structural guard in BrandConfirmService blocks Cyrillic
    # auto-learn end-to-end; this list keeps clustering / brand-key
    # extraction off the same trap.
    "карта", "карты", "карте", "картой", "карту",
    "карт",
    "кредитной", "кредитная", "кредитному", "кредитный",
    "дебетовой", "дебетовая", "дебетовый",
    "сумма", "суммы", "суммой", "сумму",
    "дата", "даты",
    "время", "времени",
    "номер", "номера", "номеру",
    "счёт", "счета", "счёта", "счету", "счёту",
    "получатель", "получателя", "получателю",
    "отправитель", "отправителя",
    "комиссия", "комиссии", "комиссию",
    "начисление", "начисления",
    "списание", "списания",
    "заказ", "заказа", "заказу",
    "платформе", "платформа", "платформу", "платформы",
    "выписка", "выписки", "выписку",
    # Skeleton placeholders
    "<org>", "<person>", "<phone>", "<contract>", "<card>", "<iban>",
    "<amount>", "<date>",
    # Stop-words that survive normalize_skeleton
    "от", "на", "по", "для", "через", "за", "из",
})

# A token qualifies as a brand only if it has at least this many alpha
# characters. Single letters ("k", "t") are almost always noise.
_MIN_BRAND_LEN = 3

# Regex to tokenize the skeleton — we keep <placeholder> atoms intact so we
# can reject them explicitly.
_TOKEN_RX = re.compile(r"<\w+>|[A-Za-zА-Яа-яЁё]{2,}", re.UNICODE)

# Transfer-like keywords. If any appear in the skeleton, the row is a
# transfer — it has no brand to attribute. Transfer rows are already
# clustered by recipient identifier (Этап 1), so brand-level grouping is
# both unnecessary and unsafe ("перевод" → would merge all transfers).
_TRANSFER_SKELETON_TOKENS: frozenset[str] = frozenset({
    "перевод", "перевода", "переводу",
    "transfer", "c2c",
    "внешний", "внутренний", "внутрибанковский",
})


def is_personal_identifier_row(skeleton: str, tokens) -> bool:
    """True when the row identifies a personal counterparty (phone, contract,
    person name) with NO merchant signal (legal org or SBP merchant ID).

    Used to prevent personal-identifier rows from being auto-bound to Brand
    entities — one person sends money for food, debt, rent, gifts; the category
    is always different, so treating the phone/contract/name as a stable «brand
    with a category» is semantically wrong (Brand Registry §X / spec v1.26).

    Accepts either an `ExtractedTokens` dataclass or a plain dict
    (from `normalized_data_json["tokens"]`).

    Rules (all require org=None AND sbp_merchant_id=None):
      • tokens.phone is set
      • tokens.contract is set
      • tokens.person_name (or person_name_present) is set
    """
    if tokens is None:
        return False

    if isinstance(tokens, dict):
        phone = tokens.get("phone")
        contract = tokens.get("contract")
        person = tokens.get("person_name") or (
            True if tokens.get("person_name_present") else None
        )
        org = tokens.get("counterparty_org")
        sbp = tokens.get("sbp_merchant_id")
    else:
        phone = getattr(tokens, "phone", None)
        contract = getattr(tokens, "contract", None)
        person = getattr(tokens, "person_name", None)
        org = getattr(tokens, "counterparty_org", None)
        sbp = getattr(tokens, "sbp_merchant_id", None)

    # Merchant signals override — if org or SBP merchant ID is present, this
    # is a proper merchant row even if it also has a phone/contract.
    if org or sbp:
        return False

    return bool(phone or contract or person)


def extract_brand(skeleton: str) -> str | None:
    """Return a lowercase brand key, or None if nothing qualifies.

    Walks the skeleton left-to-right, skipping filler/placeholder tokens and
    digit-only fragments, and returns the first token that looks like a
    brand (≥3 alpha chars, not in the filler list).

    Example: `"оплата в pyaterochka 14130 volgodonsk rus"` → `"pyaterochka"`.
    Example: `"оплата в ip drugov ms volgodonsk rus"` → `"drugov"`.
    Example: `"внешний перевод номеру телефона <phone>"` → None (no brand).
    """
    if not skeleton:
        return None

    # Transfer rows have no brand — they're already per-recipient clusters
    # via the transfer-aware fingerprint. Return early so callers don't try
    # to merge them under a misleading "перевод"-like brand key.
    lowered = skeleton.lower()
    if any(tok in lowered for tok in _TRANSFER_SKELETON_TOKENS):
        return None

    for match in _TOKEN_RX.finditer(skeleton):
        token = match.group(0).lower()
        if token in _FILLER_TOKENS:
            continue
        # Strip non-alpha to test length (drops digits/hyphens inside words).
        alpha_chars = sum(1 for ch in token if ch.isalpha())
        if alpha_chars < _MIN_BRAND_LEN:
            continue
        return token

    return None
