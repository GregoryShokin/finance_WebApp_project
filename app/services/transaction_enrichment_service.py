from __future__ import annotations

import re
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction
from app.repositories.account_repository import AccountRepository
from app.repositories.category_repository import CategoryRepository
from app.repositories.transaction_repository import TransactionRepository

NON_WORD_RX = re.compile(r"[^a-zР В°-РЎРЏРЎвЂ0-9]+", re.I)
MULTISPACE_RX = re.compile(r"\s+")
LAST4_RX = re.compile(r"(?<!\d)(\d{4})(?!\d)")
DIGITS_TOKEN_RX = re.compile(r"\b\d+\b")
PHONE_TOKEN_RX = re.compile(r"(?<!\d)(?:\+7|7|8)\d{10}(?!\d)")

# Р СћР С•Р С”Р ВµР Р…РЎвЂ№, Р С”Р С•РЎвЂљР С•РЎР‚РЎвЂ№Р Вµ Р С‘Р Т‘Р ВµР Р…РЎвЂљР С‘РЎвЂћР С‘РЎвЂ Р С‘РЎР‚РЎС“РЎР‹РЎвЂљ РЎРѓРЎвЂљРЎР‚Р В°Р Р…РЎС“, Р Р†Р В°Р В»РЎР‹РЎвЂљРЎС“ Р С‘Р В»Р С‘ Р С—Р В»Р В°РЎвЂљРЎвЂР В¶Р Р…РЎвЂ№Р в„– РЎР‚Р ВµР в„–Р В»,
# Р Р…Р С• Р Р…Р Вµ Р СР ВµРЎР‚РЎвЂЎР В°Р Р…РЎвЂљР В° РІР‚вЂќ Р С•РЎвЂљРЎвЂћР С‘Р В»РЎРЉРЎвЂљРЎР‚Р С•Р Р†РЎвЂ№Р Р†Р В°Р ВµР С Р С—РЎР‚Р С‘ Р С—Р С•РЎРѓРЎвЂљРЎР‚Р С•Р ВµР Р…Р С‘Р С‘ Р С”Р В»РЎР‹РЎвЂЎР В° Р С—РЎР‚Р В°Р Р†Р С‘Р В»Р В°.
GEO_CURRENCY_NOISE: frozenset[str] = frozenset({
    # Р РЋРЎвЂљРЎР‚Р В°Р Р…Р С•Р Р†РЎвЂ№Р Вµ Р С”Р С•Р Т‘РЎвЂ№
    "rus", "ru", "ukr", "kaz",
    # Р вЂњР С•РЎР‚Р С•Р Т‘Р В° (РЎвЂљРЎР‚Р В°Р Р…РЎРѓР В»Р С‘РЎвЂљ)
    "moscow", "msc", "spb", "krd", "ekb", "nsk", "nnd", "kzn", "rnd",
    "volgodonsk", "volgograd", "krasnodar", "novosibirsk",
    # Р С™Р С•Р Т‘РЎвЂ№ Р Р†Р В°Р В»РЎР‹РЎвЂљ
    "rub", "rur", "usd", "eur", "gbp", "cny", "mop", "kzt",
    # Р СџР В»Р В°РЎвЂљРЎвЂР В¶Р Р…РЎвЂ№Р Вµ РЎРѓР С‘РЎРѓРЎвЂљР ВµР СРЎвЂ№ / РЎР‚Р ВµР в„–Р В»РЎвЂ№ (Р Р…Р Вµ Р СР ВµРЎР‚РЎвЂЎР В°Р Р…РЎвЂљ)
    "mir", "visa", "mastercard",
})

ALLOWED_OPERATION_TYPES = {
    "regular",
    "transfer",
    "investment_buy",
    "investment_sell",
    "credit_disbursement",
    "credit_payment",
    "debt",
    "refund",
    "adjustment",
}

CATEGORY_KEYWORD_LIBRARY: dict[str, tuple[str, ...]] = {
    "Р С—РЎР‚Р С•Р Т‘РЎС“Р С”РЎвЂљ": (
        "pyaterochka", "Р С—РЎРЏРЎвЂљР ВµРЎР‚Р С•РЎвЂЎР С”Р В°", "magnit", "Р СР В°Р С–Р Р…Р С‘РЎвЂљ", "perekrestok", "Р С—Р ВµРЎР‚Р ВµР С”РЎР‚Р ВµРЎРѓРЎвЂљР С•Р С”", "Р В»Р ВµР Р…РЎвЂљР В°",
        "Р В°РЎв‚¬Р В°Р Р…", "auchan", "spar", "Р Т‘Р С‘Р С”РЎРѓР С‘", "Р Р†Р ВµРЎР‚Р Р…РЎвЂ№Р в„–", "vprok", "РЎРѓР В°Р СР С•Р С”Р В°РЎвЂљ", "Р Р†Р С”РЎС“РЎРѓР Р†Р С‘Р В»Р В»", "lavka",
        "grocery", "market", "Р ВµР Т‘Р В°", "food",
    ),
    "РЎРѓРЎС“Р С—Р ВµРЎР‚Р СР В°РЎР‚Р С”Р ВµРЎвЂљ": (
        "pyaterochka", "Р С—РЎРЏРЎвЂљР ВµРЎР‚Р С•РЎвЂЎР С”Р В°", "magnit", "Р СР В°Р С–Р Р…Р С‘РЎвЂљ", "perekrestok", "Р С—Р ВµРЎР‚Р ВµР С”РЎР‚Р ВµРЎРѓРЎвЂљР С•Р С”", "Р В»Р ВµР Р…РЎвЂљР В°", "Р В°РЎв‚¬Р В°Р Р…",
        "auchan", "spar", "Р Т‘Р С‘Р С”РЎРѓР С‘", "Р Р†Р ВµРЎР‚Р Р…РЎвЂ№Р в„–", "market", "grocery",
    ),
    "Р С”Р В°РЎвЂћ": ("restaurant", "cafe", "coffee", "Р С”Р С•РЎвЂћР Вµ", "РЎв‚¬Р В°Р Р†Р ВµРЎР‚Р С", "РЎв‚¬Р В°РЎС“РЎР‚Р С", "burger", "pizza", "РЎР‚Р С•Р В»Р В»", "sushi", "Р ВµР Т‘Р В°"),
    "РЎР‚Р ВµРЎРѓРЎвЂљР С•РЎР‚Р В°Р Р…": ("restaurant", "cafe", "coffee", "Р С”Р С•РЎвЂћР Вµ", "burger", "pizza", "РЎР‚Р С•Р В»Р В»", "sushi", "Р ВµР Т‘Р В°"),
    "Р Т‘Р С•РЎРѓРЎвЂљР В°Р Р†": ("delivery", "РЎРѓР В°Р СР С•Р С”Р В°РЎвЂљ", "yandex lavka", "РЎРЏР Р…Р Т‘Р ВµР С”РЎРѓ Р ВµР Т‘Р В°", "delivery club", "Р Т‘Р С•РЎРѓРЎвЂљР В°Р Р†Р С”Р В°"),
    "РЎвЂљРЎР‚Р В°Р Р…РЎРѓР С—Р С•РЎР‚РЎвЂљ": ("metro", "Р СР ВµРЎвЂљРЎР‚Р С•", "Р В°Р Р†РЎвЂљР С•Р В±РЎС“РЎРѓ", "taxi", "uber", "yandex go", "РЎРЏР Р…Р Т‘Р ВµР С”РЎРѓ go", "РЎвЂљР В°Р С”РЎРѓР С‘", "Р В±Р ВµР Р…Р В·Р С‘Р Р…", "fuel"),
    "РЎвЂљР В°Р С”РЎРѓР С‘": ("taxi", "uber", "yandex go", "РЎРЏР Р…Р Т‘Р ВµР С”РЎРѓ go", "РЎРѓР С‘РЎвЂљР С‘Р СР С•Р В±Р С‘Р В»", "drivee"),
    "Р В°Р Р†РЎвЂљР С•": ("fuel", "azs", "Р С–Р В°Р В·Р С—РЎР‚Р С•Р С", "Р В»РЎС“Р С”Р С•Р в„–Р В»", "РЎР‚Р С•РЎРѓР Р…Р ВµРЎвЂћРЎвЂљРЎРЉ", "shell", "Р В±Р ВµР Р…Р В·Р С‘Р Р…", "РЎвЂљР С•Р С—Р В»Р С‘Р Р†Р С•", "Р С—Р В°РЎР‚Р С”Р С•Р Р†Р С”Р В°"),
    "Р В±Р ВµР Р…Р В·Р С‘Р Р…": ("fuel", "azs", "Р С–Р В°Р В·Р С—РЎР‚Р С•Р С", "Р В»РЎС“Р С”Р С•Р в„–Р В»", "РЎР‚Р С•РЎРѓР Р…Р ВµРЎвЂћРЎвЂљРЎРЉ", "shell", "Р В±Р ВµР Р…Р В·Р С‘Р Р…", "РЎвЂљР С•Р С—Р В»Р С‘Р Р†Р С•"),
    "Р В°Р С—РЎвЂљР ВµР С”": ("apteka", "Р В°Р С—РЎвЂљР ВµР С”Р В°", "Р В°Р С—РЎвЂљР ВµР С”Р С‘", "36 6", "rigla", "Р ВµР В°Р С—РЎвЂљР ВµР С”Р В°", "РЎвЂћР В°РЎР‚Р С"),
    "Р В·Р Т‘Р С•РЎР‚Р С•Р Р†": ("medical", "clinic", "Р Т‘Р С•Р С”РЎвЂљР С•РЎР‚", "Р СР ВµР Т‘Р С‘РЎвЂ Р С‘Р Р…Р В°", "Р В°Р С—РЎвЂљР ВµР С”Р В°", "apteka", "РЎРѓРЎвЂљР С•Р СР В°РЎвЂљ", "Р В°Р Р…Р В°Р В»Р С‘Р В·"),
    "РЎРѓР Р†РЎРЏР В·": ("mts", "Р СРЎвЂљРЎРѓ", "megafon", "Р СР ВµР С–Р В°РЎвЂћР С•Р Р…", "beeline", "Р В±Р С‘Р В»Р В°Р в„–Р Р…", "tele2", "yota", "internet", "Р С‘Р Р…РЎвЂљР ВµРЎР‚Р Р…Р ВµРЎвЂљ"),
    "Р С‘Р Р…РЎвЂљР ВµРЎР‚Р Р…Р ВµРЎвЂљ": ("internet", "wifi", "Р Т‘Р С•Р С РЎР‚РЎС“", "РЎР‚Р С•РЎРѓРЎвЂљР ВµР В»Р ВµР С”Р С•Р С", "Р СРЎвЂљРЎРѓ", "Р В±Р С‘Р В»Р В°Р в„–Р Р…", "Р СР ВµР С–Р В°РЎвЂћР С•Р Р…"),
    "Р С”Р С•Р СР СРЎС“Р Р…": ("gkh", "Р В¶Р С”РЎвЂ¦", "mosenergo", "water", "electricity", "Р С”Р Р†Р В°РЎР‚РЎвЂљР С—Р В»Р В°РЎвЂљР В°", "РЎРЊР В»Р ВµР С”РЎвЂљРЎР‚Р С•РЎРЊР Р…Р ВµРЎР‚Р С–", "Р С–Р В°Р В·", "Р Р†Р С•Р Т‘Р В°"),
    "Р В°РЎР‚Р ВµР Р…Р Т‘": ("rent", "Р В°РЎР‚Р ВµР Р…Р Т‘Р В°", "landlord", "Р С”Р Р†Р В°РЎР‚РЎвЂљР С‘РЎР‚Р В°"),
    "РЎР‚Р В°Р В·Р Р†Р В»Р ВµРЎвЂЎ": ("cinema", "movie", "steam", "playstation", "netflix", "ivi", "spotify", "concert", "Р С‘Р С–РЎР‚"),
    "Р С—Р С•Р Т‘Р С—Р С‘РЎРѓ": ("subscription", "netflix", "spotify", "youtube", "icloud", "google one", "yandex plus", "Р С—Р С•Р Т‘Р С—Р С‘РЎРѓР С”Р В°"),
    "Р СР В°РЎР‚Р С”Р ВµРЎвЂљР С—Р В»Р ВµР в„–РЎРѓ": ("wildberries", "wb", "ozon", "РЎРЏР Р…Р Т‘Р ВµР С”РЎРѓ Р СР В°РЎР‚Р С”Р ВµРЎвЂљ", "marketplace", "aliexpress", "avito"),
    "Р С•Р Т‘Р ВµР В¶": ("lamoda", "zara", "uniqlo", "wildberries", "wb", "ozon", "Р С•Р Т‘Р ВµР В¶", "Р С•Р В±РЎС“Р Р†"),
    "Р С—Р ВµРЎР‚Р ВµР Р†Р С•Р Т‘": ("Р С—Р ВµРЎР‚Р ВµР Р†Р С•Р Т‘", "РЎРѓР С‘РЎРѓРЎвЂљР ВµР СР В° Р В±РЎвЂ№РЎРѓРЎвЂљРЎР‚РЎвЂ№РЎвЂ¦ Р С—Р В»Р В°РЎвЂљР ВµР В¶Р ВµР в„–", "РЎРѓР В±Р С—"),
    "Р Р…Р В°Р В»Р С•Р С–": ("nalog", "fns", "РЎвЂћР Р…РЎРѓ", "Р Р…Р В°Р В»Р С•Р С–"),
    "Р В·Р В°РЎР‚Р С—Р В»Р В°РЎвЂљ": ("salary", "Р В·Р В°РЎР‚Р С—Р В»Р В°РЎвЂљР В°", "Р В°Р Р†Р В°Р Р…РЎРѓ", "payroll"),
    "Р С”РЎРЊРЎв‚¬Р В±РЎРЊР С”": ("cashback", "Р С”РЎРЊРЎв‚¬Р В±РЎРЊР С”"),
    "Р С—РЎР‚Р С•РЎвЂ Р ВµР Р…РЎвЂљ": ("interest", "Р С—РЎР‚Р С•РЎвЂ Р ВµР Р…РЎвЂљ", "deposit interest", "Р Р†Р С”Р В»Р В°Р Т‘"),
}

STOP_WORDS = {
    "oplata", "payment", "card", "pokupka", "purchase", "perevod", "operaciya", "operatsiya", "tranzakciya",
    "transaction", "sbp", "mir", "visa", "mastercard", "schet", "scheta", "account", "rur", "rub", "pokupki",
    "pos", "retail", "sale", "spisanie", "zachislenie", "perechislenie", "perevodom", "oplatauslug",
}


class TransactionEnrichmentService:
    def __init__(self, db: Session):
        self.db = db
        self.account_repo = AccountRepository(db)
        self.category_repo = CategoryRepository(db)
        self.transaction_repo = TransactionRepository(db)

    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        """Р вЂР В°Р В·Р С•Р Р†Р В°РЎРЏ Р Р…Р С•РЎР‚Р СР В°Р В»Р С‘Р В·Р В°РЎвЂ Р С‘РЎРЏ: lowercase + РЎС“Р В±РЎР‚Р В°РЎвЂљРЎРЉ РЎРѓР С—Р ВµРЎвЂ РЎРѓР С‘Р СР Р†Р С•Р В»РЎвЂ№. Р В¦Р С‘РЎвЂћРЎР‚РЎвЂ№ РЎРѓР С•РЎвЂ¦РЎР‚Р В°Р Р…РЎРЏРЎР‹РЎвЂљРЎРѓРЎРЏ."""
        text = str(value or "").lower().replace("РЎвЂ", "Р Вµ").strip()
        if not text:
            return None
        text = text.replace("РЎРѓР В±Р С—", "РЎРѓР С‘РЎРѓРЎвЂљР ВµР СР В° Р В±РЎвЂ№РЎРѓРЎвЂљРЎР‚РЎвЂ№РЎвЂ¦ Р С—Р В»Р В°РЎвЂљР ВµР В¶Р ВµР в„–")
        text = NON_WORD_RX.sub(" ", text)
        text = MULTISPACE_RX.sub(" ", text).strip()
        return text or None

    @classmethod
    def normalize_for_rule(cls, value: str | None) -> str | None:
        """Р С’Р С–РЎР‚Р ВµРЎРѓРЎРѓР С‘Р Р†Р Р…Р В°РЎРЏ Р Р…Р С•РЎР‚Р СР В°Р В»Р С‘Р В·Р В°РЎвЂ Р С‘РЎРЏ Р Т‘Р В»РЎРЏ Р С”Р В»РЎР‹РЎвЂЎР В° Р С—РЎР‚Р В°Р Р†Р С‘Р В»Р В° Р С‘ Р С—Р С•Р В»РЎРЏ normalized_description.

        Р С›РЎвЂљР В±РЎР‚Р В°РЎРѓРЎвЂ№Р Р†Р В°Р ВµРЎвЂљ Р С—Р ВµРЎР‚Р ВµР СР ВµР Р…Р Р…РЎвЂ№Р Вµ РЎвЂЎР В°РЎРѓРЎвЂљР С‘, Р С”Р С•РЎвЂљР С•РЎР‚РЎвЂ№Р Вµ Р СР ВµР Р…РЎРЏРЎР‹РЎвЂљРЎРѓРЎРЏ Р С•РЎвЂљ Р С•Р С—Р ВµРЎР‚Р В°РЎвЂ Р С‘Р С‘ Р С” Р С•Р С—Р ВµРЎР‚Р В°РЎвЂ Р С‘Р С‘
        Р С‘ Р Р…Р Вµ Р С‘Р Т‘Р ВµР Р…РЎвЂљР С‘РЎвЂћР С‘РЎвЂ Р С‘РЎР‚РЎС“РЎР‹РЎвЂљ Р СР ВµРЎР‚РЎвЂЎР В°Р Р…РЎвЂљР В°:
          РІР‚Сћ Р Р†РЎРѓР Вµ РЎвЂ Р С‘РЎвЂћРЎР‚Р С•Р Р†РЎвЂ№Р Вµ РЎвЂљР С•Р С”Р ВµР Р…РЎвЂ№ (Р Т‘Р В°РЎвЂљРЎвЂ№, Р С—Р С•РЎРѓР В»Р ВµР Т‘Р Р…Р С‘Р Вµ 4 РЎвЂ Р С‘РЎвЂћРЎР‚РЎвЂ№ Р С”Р В°РЎР‚РЎвЂљРЎвЂ№, ID РЎвЂљР ВµРЎР‚Р СР С‘Р Р…Р В°Р В»Р В°)
          РІР‚Сћ Р С–Р ВµР С•/Р Р†Р В°Р В»РЎР‹РЎвЂљР Р…РЎвЂ№Р Вµ РЎв‚¬РЎС“Р СР С•Р Р†РЎвЂ№Р Вµ РЎвЂљР С•Р С”Р ВµР Р…РЎвЂ№ (RUS, EUR, Volgodonsk Р С‘ РЎвЂљ.Р С—.)
          РІР‚Сћ РЎРѓРЎвЂљР С•Р С—-РЎРѓР В»Р С•Р Р†Р В° Р С—Р В»Р В°РЎвЂљРЎвЂР В¶Р Р…Р С•Р в„– Р С‘Р Р…Р Т‘РЎС“РЎРѓРЎвЂљРЎР‚Р С‘Р С‘ (payment, card, sbp Р С‘ РЎвЂљ.Р С—.)
          РІР‚Сћ Р’В«РЎРѓР С‘РЎРѓРЎвЂљР ВµР СР В° Р В±РЎвЂ№РЎРѓРЎвЂљРЎР‚РЎвЂ№РЎвЂ¦ Р С—Р В»Р В°РЎвЂљР ВµР В¶Р ВµР в„–Р’В» РІР‚вЂќ Р С‘Р Т‘Р ВµР Р…РЎвЂљР С‘РЎвЂћР С‘Р С”Р В°РЎвЂљР С•РЎР‚ РЎР‚Р ВµР в„–Р В»Р В°, Р Р…Р Вµ Р СР ВµРЎР‚РЎвЂЎР В°Р Р…РЎвЂљР В°
          РІР‚Сћ РЎвЂљР С•Р С”Р ВµР Р…РЎвЂ№ Р С”Р С•РЎР‚Р С•РЎвЂЎР Вµ 3 РЎРѓР С‘Р СР Р†Р С•Р В»Р С•Р Р†

        Р СџРЎР‚Р С‘Р СР ВµРЎР‚РЎвЂ№:
          "POPLAVO Volgodonsk RUS 28.03"  РІвЂ вЂ™  "poplavo"
          "Р Р‡Р Р…Р Т‘Р ВµР С”РЎРѓ Р вЂўР Т‘Р В° 12345"              РІвЂ вЂ™  "РЎРЏР Р…Р Т‘Р ВµР С”РЎРѓ Р ВµР Т‘Р В°"
          "26033 MOP SBP 0387 28.03"      РІвЂ вЂ™  None  (Р СР ВµРЎР‚РЎвЂЎР В°Р Р…РЎвЂљ Р Р…Р Вµ Р С•Р С—РЎР‚Р ВµР Т‘Р ВµР В»РЎРЏР ВµРЎвЂљРЎРѓРЎРЏ)
          "Р СџР С•Р С—Р В»Р В°Р Р†Р С•Р С”"                       РІвЂ вЂ™  "Р С—Р С•Р С—Р В»Р В°Р Р†Р С•Р С”"
        """
        text = cls.normalize_description(value)
        if not text:
            return None

        # РЈР±РёСЂР°РµРј РїР»Р°С‚С‘Р¶РЅС‹Р№ СЂРµР№Р» вЂ” РѕРЅ РЅРµ РѕРїРёСЃС‹РІР°РµС‚ РјРµСЂС‡Р°РЅС‚Р°
        text = text.replace("СЃРёСЃС‚РµРјР° Р±С‹СЃС‚СЂС‹С… РїР»Р°С‚РµР¶РµР№", " ")

        # РЎРѕС…СЂР°РЅСЏРµРј С‚РµР»РµС„РѕРЅ РєР°Рє СѓСЃС‚РѕР№С‡РёРІС‹Р№ С‚РѕРєРµРЅ РїСЂР°РІРёР»Р°: РѕРЅ РІР°Р¶РµРЅ РґР»СЏ Р°СЂРµРЅРґРЅС‹С…,
        # РєРѕРјРјСѓРЅР°Р»СЊРЅС‹С… Рё РґСЂСѓРіРёС… РїР»Р°С‚РµР¶РµР№ РїРѕ РЅРѕРјРµСЂСѓ С‚РµР»РµС„РѕРЅР°, РЅРѕ РЅРµ РґРѕР»Р¶РµРЅ СЃРјРµС€РёРІР°С‚СЊСЃСЏ
        # СЃ РїСЂРѕС‡РёРј С†РёС„СЂРѕРІС‹Рј С€СѓРјРѕРј РёР· РѕРїРёСЃР°РЅРёСЏ.
        phone_tokens = []
        for match in PHONE_TOKEN_RX.findall(text):
            digits = re.sub(r"\D", "", match)
            if len(digits) == 11:
                phone_tokens.append(f"phone_{digits}")
        text = PHONE_TOKEN_RX.sub(" ", text)

        # РЈР±РёСЂР°РµРј РїСЂРѕС‡РёРµ С†РёС„СЂРѕРІС‹Рµ С‚РѕРєРµРЅС‹: РґР°С‚С‹, terminal id, reference id Рё С‚.Рї.
        text = DIGITS_TOKEN_RX.sub(" ", text)
        text = MULTISPACE_RX.sub(" ", text).strip()

        # Р¤РёР»СЊС‚СЂСѓРµРј С‚РѕРєРµРЅС‹
        tokens = [
            t for t in text.split()
            if len(t) >= 3
            and t not in STOP_WORDS
            and t not in GEO_CURRENCY_NOISE
        ]

        tokens.extend(phone_tokens)
        deduped_tokens = list(dict.fromkeys(tokens))
        return " ".join(deduped_tokens) or None

    def enrich_import_row(
        self,
        *,
        user_id: int,
        session_account_id: int | None,
        normalized_payload: dict[str, Any],
    ) -> dict[str, Any]:
        description = str(normalized_payload.get("description") or "").strip()
        raw_type = str(normalized_payload.get("operation_type") or normalized_payload.get("type") or "").strip()
        counterparty = str(normalized_payload.get("counterparty") or normalized_payload.get("merchant") or "").strip()
        account_hint = str(normalized_payload.get("account_hint") or normalized_payload.get("account_number") or "").strip()
        # normalize_for_rule Р С•РЎвЂљР В±РЎР‚Р В°РЎРѓРЎвЂ№Р Р†Р В°Р ВµРЎвЂљ Р Т‘Р В°РЎвЂљРЎвЂ№, Р Р…Р С•Р СР ВµРЎР‚Р В° РЎвЂљР ВµРЎР‚Р СР С‘Р Р…Р В°Р В»Р С•Р Р† Р С‘ Р С–Р ВµР С•-РЎв‚¬РЎС“Р С,
        # Р С•РЎРѓРЎвЂљР В°Р Р†Р В»РЎРЏРЎРЏ РЎвЂљР С•Р В»РЎРЉР С”Р С• РЎРѓРЎвЂљР В°Р В±Р С‘Р В»РЎРЉР Р…Р С•Р Вµ РЎРЏР Т‘РЎР‚Р С• Р СР ВµРЎР‚РЎвЂЎР В°Р Р…РЎвЂљР В° РІР‚вЂќ Р С‘РЎРѓР С—Р С•Р В»РЎРЉР В·РЎС“Р ВµРЎвЂљРЎРѓРЎРЏ Р С”Р В°Р С” Р С”Р В»РЎР‹РЎвЂЎ Р С—РЎР‚Р В°Р Р†Р С‘Р В»Р В°
        # Р С‘ Р С”Р В°Р С” Р В·Р Р…Р В°РЎвЂЎР ВµР Р…Р С‘Р Вµ normalized_description Р Т‘Р В»РЎРЏ РЎвЂ¦РЎР‚Р В°Р Р…Р ВµР Р…Р С‘РЎРЏ Р Р† РЎвЂљРЎР‚Р В°Р Р…Р В·Р В°Р С”РЎвЂ Р С‘Р С‘.
        normalized_description = self.normalize_for_rule(" ".join(filter(None, [description, counterparty])))

        history = self._find_history(
            user_id=user_id,
            normalized_description=normalized_description,
        )
        accounts = self.account_repo.list_by_user(user_id)
        categories = self.category_repo.list(user_id=user_id)

        operation_type, operation_confidence, operation_reason = self._resolve_operation_type(
            description=description,
            raw_type=raw_type,
            history=history,
        )
        if operation_type not in ALLOWED_OPERATION_TYPES:
            operation_type = "regular"
            operation_confidence = max(operation_confidence, 0.7)
            operation_reason = "Р СњР ВµР С‘Р В·Р Р†Р ВµРЎРѓРЎвЂљР Р…РЎвЂ№Р в„– РЎвЂљР С‘Р С— Р С•Р С—Р ВµРЎР‚Р В°РЎвЂ Р С‘Р С‘ Р В·Р В°Р СР ВµР Р…РЎвЂР Р… Р Р…Р В° regular"

        transaction_type = self._resolve_transaction_type(
            direction=normalized_payload.get("direction"),
            operation_type=operation_type,
            history=history,
        )

        account_id, account_confidence, account_reason = self._resolve_account(
            accounts=accounts,
            session_account_id=session_account_id,
            account_hint=account_hint,
            description=description,
            counterparty=counterparty,
            operation_type=operation_type,
            transaction_type=transaction_type,
        )
        target_account_id, target_confidence, target_reason = self._resolve_target_account(
            accounts=accounts,
            session_account_id=session_account_id,
            source_account_id=account_id,
            operation_type=operation_type,
            transaction_type=transaction_type,
            description=description,
            counterparty=counterparty,
        )

        if operation_type == "transfer" and transaction_type == "income" and target_account_id is not None:
            if account_id is None or account_id == target_account_id:
                inferred_source_id, inferred_source_confidence, inferred_source_reason = self._resolve_other_account_for_income_transfer(
                    accounts=accounts,
                    session_account_id=session_account_id,
                    description=description,
                    counterparty=counterparty,
                    target_account_id=target_account_id,
                )
                if inferred_source_id is not None:
                    account_id = inferred_source_id
                    account_confidence = max(account_confidence, inferred_source_confidence)
                    account_reason = inferred_source_reason

        category_id, category_confidence, category_reason = self._resolve_category(
            categories=categories,
            history=history,
            normalized_description=normalized_description,
            operation_type=operation_type,
            transaction_type=transaction_type,
            description=description,
            counterparty=counterparty,
        )

        review_reasons: list[str] = []
        if account_id is None:
            review_reasons.append("Р СњР Вµ РЎС“Р Т‘Р В°Р В»Р С•РЎРѓРЎРЉ Р С•Р С—РЎР‚Р ВµР Т‘Р ВµР В»Р С‘РЎвЂљРЎРЉ РЎРѓРЎвЂЎРЎвЂРЎвЂљ Р С•Р С—Р ВµРЎР‚Р В°РЎвЂ Р С‘Р С‘")

        if operation_type == "transfer":
            if account_id is None:
                review_reasons.append("Р вЂќР В»РЎРЏ Р С—Р ВµРЎР‚Р ВµР Р†Р С•Р Т‘Р В° Р Р…Р Вµ Р Р…Р В°Р в„–Р Т‘Р ВµР Р… РЎРѓРЎвЂЎРЎвЂРЎвЂљ РЎРѓР С—Р С‘РЎРѓР В°Р Р…Р С‘РЎРЏ")
            if target_account_id is None:
                review_reasons.append("Р вЂќР В»РЎРЏ Р С—Р ВµРЎР‚Р ВµР Р†Р С•Р Т‘Р В° Р Р…Р Вµ Р Р…Р В°Р в„–Р Т‘Р ВµР Р… РЎРѓРЎвЂЎРЎвЂРЎвЂљ Р Р…Р В°Р В·Р Р…Р В°РЎвЂЎР ВµР Р…Р С‘РЎРЏ")
            elif account_id == target_account_id:
                review_reasons.append("Р вЂќР В»РЎРЏ Р С—Р ВµРЎР‚Р ВµР Р†Р С•Р Т‘Р В° РЎРѓРЎвЂЎРЎвЂРЎвЂљ РЎРѓР С—Р С‘РЎРѓР В°Р Р…Р С‘РЎРЏ РЎРѓР С•Р Р†Р С—Р В°Р В» РЎРѓР С• РЎРѓРЎвЂЎРЎвЂРЎвЂљР С•Р С Р Р…Р В°Р В·Р Р…Р В°РЎвЂЎР ВµР Р…Р С‘РЎРЏ")

        auto_confidence = round(
            max(
                0.0,
                min(
                    1.0,
                    (
                        operation_confidence
                        + account_confidence
                        + max(category_confidence, target_confidence)
                    ) / 3,
                ),
            ),
            4,
        )

        return {
            "normalized_description": normalized_description,
            "suggested_account_id": account_id,
            "suggested_target_account_id": target_account_id,
            "suggested_category_id": category_id,
            "suggested_operation_type": operation_type,
            "suggested_type": transaction_type,
            "assignment_confidence": auto_confidence,
            "assignment_reasons": [
                reason
                for reason in [operation_reason, account_reason, target_reason, category_reason]
                if reason
            ],
            "review_reasons": review_reasons,
            "needs_manual_review": bool(review_reasons),
        }

    def _resolve_operation_type(self, *, description: str, raw_type: str, history: list[Transaction]) -> tuple[str, float, str]:
        pair_counter = Counter((item.operation_type, item.type) for item in history)
        if pair_counter:
            (op_type, _), count = pair_counter.most_common(1)[0]
            if count >= 2 and op_type in ALLOWED_OPERATION_TYPES:
                return op_type, 0.96, f"Р СћР С‘Р С— Р С•Р С—Р ВµРЎР‚Р В°РЎвЂ Р С‘Р С‘ Р Р†Р В·РЎРЏРЎвЂљ Р С‘Р В· Р С‘РЎРѓРЎвЂљР С•РЎР‚Р С‘Р С‘ Р С—Р С•РЎвЂ¦Р С•Р В¶Р С‘РЎвЂ¦ РЎвЂљРЎР‚Р В°Р Р…Р В·Р В°Р С”РЎвЂ Р С‘Р в„– ({count} РЎРѓР С•Р Р†Р С—.)"

        haystack = self.normalize_description(" ".join([description, raw_type])) or ""
        if any(token in haystack for token in ["Р С—Р С•Р С–Р В°РЎв‚¬Р ВµР Р…Р С‘Р Вµ РЎвЂљР ВµР В»Р В° Р С”РЎР‚Р ВµР Т‘Р С‘РЎвЂљР В°", "Р С•РЎРѓР Р…Р С•Р Р†Р Р…Р С•Р С–Р С• Р Т‘Р С•Р В»Р С–Р В°", "РЎвЂљР ВµР В»Р С• Р С”РЎР‚Р ВµР Т‘Р С‘РЎвЂљР В°"]):
            return "credit_payment", 0.88, "Р С›Р С—РЎР‚Р ВµР Т‘Р ВµР В»Р ВµР Р…Р С• Р С”Р В°Р С” Р С—Р С•Р С–Р В°РЎв‚¬Р ВµР Р…Р С‘Р Вµ РЎвЂљР ВµР В»Р В° Р С”РЎР‚Р ВµР Т‘Р С‘РЎвЂљР В°"
        if any(token in haystack for token in ["Р С—Р С•Р С–Р В°РЎв‚¬Р ВµР Р…Р С‘Р Вµ", "Р В·Р В°Р Т‘Р С•Р В»Р В¶Р ВµР Р…"]):
            return "credit_payment", 0.84, "Р С›Р С—РЎР‚Р ВµР Т‘Р ВµР В»Р ВµР Р…Р С• Р С”Р В°Р С” Р С—Р С•Р С–Р В°РЎв‚¬Р ВµР Р…Р С‘Р Вµ Р С”РЎР‚Р ВµР Т‘Р С‘РЎвЂљР В°"
        if any(token in haystack for token in ["Р Р†РЎвЂ№Р Т‘Р В°РЎвЂЎР В° Р С”РЎР‚Р ВµР Т‘Р С‘РЎвЂљР В°", "Р С”РЎР‚Р ВµР Т‘Р С‘РЎвЂљ Р Р†РЎвЂ№Р Т‘Р В°Р Р…", "Р С”РЎР‚Р ВµР Т‘Р С‘РЎвЂљР Р…РЎвЂ№Р Вµ РЎРѓРЎР‚Р ВµР Т‘РЎРѓРЎвЂљР Р†Р В°"]):
            return "credit_disbursement", 0.88, "Р С›Р С—РЎР‚Р ВµР Т‘Р ВµР В»Р ВµР Р…Р С• Р С”Р В°Р С” Р Р†РЎвЂ№Р Т‘Р В°РЎвЂЎР В° Р С”РЎР‚Р ВµР Т‘Р С‘РЎвЂљР В°"
        if any(token in haystack for token in ["Р С—Р ВµРЎР‚Р ВµР Р†Р С•Р Т‘", "РЎРѓР С‘РЎРѓРЎвЂљР ВµР СР В° Р В±РЎвЂ№РЎРѓРЎвЂљРЎР‚РЎвЂ№РЎвЂ¦ Р С—Р В»Р В°РЎвЂљР ВµР В¶Р ВµР в„–", "РЎРѓР В±Р С—", "Р СР ВµР В¶Р Т‘РЎС“ РЎРѓР Р†Р С•Р С‘Р СР С‘ РЎРѓРЎвЂЎР ВµРЎвЂљР В°Р СР С‘"]):
            return "transfer", 0.82, "Р С›Р С—РЎР‚Р ВµР Т‘Р ВµР В»Р ВµР Р…Р С• Р С”Р В°Р С” Р С—Р ВµРЎР‚Р ВµР Р†Р С•Р Т‘"
        if any(token in haystack for token in ["Р С—Р С•Р С”РЎС“Р С—Р С”Р В° РЎвЂ Р ВµР Р…Р Р…РЎвЂ№РЎвЂ¦ Р В±РЎС“Р СР В°Р С–", "Р С—Р С•Р С”РЎС“Р С—Р С”Р В° Р В°Р С”РЎвЂ Р С‘Р в„–", "Р С‘Р Р…Р Р†Р ВµРЎРѓРЎвЂљР С‘РЎвЂ Р С‘"]) and "Р С—РЎР‚Р С•Р Т‘Р В°Р В¶" not in haystack:
            return "investment_buy", 0.84, "Р С›Р С—РЎР‚Р ВµР Т‘Р ВµР В»Р ВµР Р…Р С• Р С”Р В°Р С” Р С‘Р Р…Р Р†Р ВµРЎРѓРЎвЂљР С‘РЎвЂ Р С‘Р С•Р Р…Р Р…Р В°РЎРЏ Р С—Р С•Р С”РЎС“Р С—Р С”Р В°"
        if any(token in haystack for token in ["Р С—РЎР‚Р С•Р Т‘Р В°Р В¶Р В° РЎвЂ Р ВµР Р…Р Р…РЎвЂ№РЎвЂ¦ Р В±РЎС“Р СР В°Р С–", "Р С—РЎР‚Р С•Р Т‘Р В°Р В¶Р В° Р В°Р С”РЎвЂ Р С‘Р в„–", "Р С—РЎР‚Р С•Р Т‘Р В°Р В¶"]):
            return "investment_sell", 0.84, "Р С›Р С—РЎР‚Р ВµР Т‘Р ВµР В»Р ВµР Р…Р С• Р С”Р В°Р С” Р С‘Р Р…Р Р†Р ВµРЎРѓРЎвЂљР С‘РЎвЂ Р С‘Р С•Р Р…Р Р…Р В°РЎРЏ Р С—РЎР‚Р С•Р Т‘Р В°Р В¶Р В°"
        return "regular", 0.65, "Р ВРЎРѓР С—Р С•Р В»РЎРЉР В·Р С•Р Р†Р В°Р Р… РЎвЂљР С‘Р С— regular Р С—Р С• РЎС“Р СР С•Р В»РЎвЂЎР В°Р Р…Р С‘РЎР‹"

    def _resolve_transaction_type(self, *, direction: Any, operation_type: str, history: list[Transaction]) -> str:
        direction_value = str(direction or "").strip().lower()
        if direction_value in {"income", "expense"}:
            return direction_value
        if history:
            type_counter = Counter(item.type for item in history)
            if type_counter:
                resolved = type_counter.most_common(1)[0][0]
                if resolved in {"income", "expense"}:
                    return resolved
        defaults = {
            "investment_buy": "expense",
            "investment_sell": "income",
            "credit_disbursement": "income",
            "credit_payment": "expense",
            "refund": "income",
            "adjustment": "expense",
        }
        return defaults.get(operation_type, "expense")

    def _resolve_account(
        self,
        *,
        accounts: list[Account],
        session_account_id: int | None,
        account_hint: str,
        description: str,
        counterparty: str,
        operation_type: str,
        transaction_type: str,
    ) -> tuple[int | None, float, str]:
        if account_hint:
            last4 = self._extract_last4(account_hint)
            if last4:
                matched = self._find_account_by_last4(accounts, last4)
                if matched is not None:
                    return matched.id, 0.95, f"Р РЋРЎвЂЎРЎвЂРЎвЂљ Р С•Р С—РЎР‚Р ВµР Т‘Р ВµР В»РЎвЂР Р… Р С—Р С• Р СР В°РЎРѓР С”Р Вµ {last4} Р С‘Р В· Р Р†РЎвЂ№Р С—Р С‘РЎРѓР С”Р С‘"

        transfer_related_account = self._find_account_in_text(
            accounts=accounts,
            text=" ".join(filter(None, [description, counterparty])),
            exclude_account_id=session_account_id if operation_type == "transfer" and transaction_type == "income" else None,
        )
        if transfer_related_account is not None and operation_type == "transfer" and transaction_type == "income":
            return transfer_related_account.id, 0.9, "Р РЋРЎвЂЎРЎвЂРЎвЂљ РЎРѓР С—Р С‘РЎРѓР В°Р Р…Р С‘РЎРЏ Р Т‘Р В»РЎРЏ Р Р†РЎвЂ¦Р С•Р Т‘РЎРЏРЎвЂ°Р ВµР С–Р С• Р С—Р ВµРЎР‚Р ВµР Р†Р С•Р Т‘Р В° Р Р…Р В°Р в„–Р Т‘Р ВµР Р… Р Р† Р С•Р С—Р С‘РЎРѓР В°Р Р…Р С‘Р С‘"

        normalized_description = self.normalize_description(description) or ""
        for account in accounts:
            account_name = self.normalize_description(account.name) or ""
            if account_name and account_name in normalized_description:
                return account.id, 0.86, "Р РЋРЎвЂЎРЎвЂРЎвЂљ Р Р…Р В°Р в„–Р Т‘Р ВµР Р… Р С—Р С• Р Р…Р В°Р В·Р Р†Р В°Р Р…Р С‘РЎР‹ Р Р† Р С•Р С—Р С‘РЎРѓР В°Р Р…Р С‘Р С‘"

        if session_account_id is not None:
            return session_account_id, 0.78, "Р ВРЎРѓР С—Р С•Р В»РЎРЉР В·Р С•Р Р†Р В°Р Р… РЎРѓРЎвЂЎРЎвЂРЎвЂљ, Р Р†РЎвЂ№Р В±РЎР‚Р В°Р Р…Р Р…РЎвЂ№Р в„– Р Р† Р СР В°РЎРѓРЎвЂљР ВµРЎР‚Р Вµ Р С‘Р СР С—Р С•РЎР‚РЎвЂљР В°"
        return None, 0.0, ""

    def _resolve_target_account(
        self,
        *,
        accounts: list[Account],
        session_account_id: int | None,
        source_account_id: int | None,
        operation_type: str,
        transaction_type: str,
        description: str,
        counterparty: str,
    ) -> tuple[int | None, float, str]:
        if operation_type != "transfer":
            return None, 0.0, ""

        if session_account_id is not None and transaction_type == "income":
            return session_account_id, 0.96, "Р РЋРЎвЂЎРЎвЂРЎвЂљ Р Р…Р В°Р В·Р Р…Р В°РЎвЂЎР ВµР Р…Р С‘РЎРЏ Р Р†Р В·РЎРЏРЎвЂљ Р С‘Р В· РЎРѓРЎвЂЎРЎвЂРЎвЂљР В°, Р Р†РЎвЂ№Р В±РЎР‚Р В°Р Р…Р Р…Р С•Р С–Р С• Р Р† Р СР В°РЎРѓРЎвЂљР ВµРЎР‚Р Вµ Р С‘Р СР С—Р С•РЎР‚РЎвЂљР В°"

        matched = self._find_account_in_text(
            accounts=accounts,
            text=" ".join(filter(None, [description, counterparty])),
            exclude_account_id=source_account_id,
        )
        if matched is not None:
            return matched.id, 0.9, "Р РЋРЎвЂЎРЎвЂРЎвЂљ Р Р…Р В°Р В·Р Р…Р В°РЎвЂЎР ВµР Р…Р С‘РЎРЏ Р Р…Р В°Р в„–Р Т‘Р ВµР Р… Р Р† Р С•Р С—Р С‘РЎРѓР В°Р Р…Р С‘Р С‘ Р С—Р ВµРЎР‚Р ВµР Р†Р С•Р Т‘Р В°"

        return None, 0.0, ""

    def _resolve_other_account_for_income_transfer(
        self,
        *,
        accounts: list[Account],
        session_account_id: int | None,
        description: str,
        counterparty: str,
        target_account_id: int,
    ) -> tuple[int | None, float, str]:
        matched = self._find_account_in_text(
            accounts=accounts,
            text=" ".join(filter(None, [description, counterparty])),
            exclude_account_id=target_account_id,
        )
        if matched is not None:
            return matched.id, 0.9, "Р РЋРЎвЂЎРЎвЂРЎвЂљ РЎРѓР С—Р С‘РЎРѓР В°Р Р…Р С‘РЎРЏ Р Р…Р В°Р в„–Р Т‘Р ВµР Р… Р Р† Р С•Р С—Р С‘РЎРѓР В°Р Р…Р С‘Р С‘ Р Р†РЎвЂ¦Р С•Р Т‘РЎРЏРЎвЂ°Р ВµР С–Р С• Р С—Р ВµРЎР‚Р ВµР Р†Р С•Р Т‘Р В°"

        for account in accounts:
            if account.id not in {target_account_id, session_account_id}:
                return account.id, 0.35, "Р ВРЎРѓРЎвЂљР С•РЎвЂЎР Р…Р С‘Р С” Р С—Р ВµРЎР‚Р ВµР Р†Р С•Р Т‘Р В° Р С—Р С•Р Т‘Р С•Р В±РЎР‚Р В°Р Р… Р С”Р В°Р С” РЎР‚Р ВµР В·Р ВµРЎР‚Р Р†Р Р…РЎвЂ№Р в„– РЎРѓРЎвЂЎРЎвЂРЎвЂљ; РЎвЂљРЎР‚Р ВµР В±РЎС“Р ВµРЎвЂљРЎРѓРЎРЏ Р С—РЎР‚Р С•Р Р†Р ВµРЎР‚Р С”Р В°"
        return None, 0.0, ""

    def _resolve_category(
        self,
        *,
        categories: list[Category],
        history: list[Transaction],
        normalized_description: str | None,
        operation_type: str,
        transaction_type: str,
        description: str,
        counterparty: str,
    ) -> tuple[int | None, float, str]:
        # ??? expense-?????????? ????????? ????????? ???? ???? ???? ??????? ?? ??? transfer:
        # ?????? ?? ???/?????? ???????? ????? ???? ???????? ???????? ? ?????? ????????? ?? ???????.
        if transaction_type != "expense":
            return None, 0.0, ""

        category_counter = Counter(item.category_id for item in history if item.category_id is not None)
        if category_counter:
            category_id, count = category_counter.most_common(1)[0]
            category = next((item for item in categories if item.id == category_id), None)
            if category and category.kind == transaction_type:
                return category.id, 0.96, f"Р С™Р В°РЎвЂљР ВµР С–Р С•РЎР‚Р С‘РЎРЏ Р Р†Р В·РЎРЏРЎвЂљР В° Р С‘Р В· Р С‘РЎРѓРЎвЂљР С•РЎР‚Р С‘Р С‘ Р С—Р С•РЎвЂ¦Р С•Р В¶Р С‘РЎвЂ¦ РЎвЂљРЎР‚Р В°Р Р…Р В·Р В°Р С”РЎвЂ Р С‘Р в„– ({count} РЎРѓР С•Р Р†Р С—.)"

        normalized_description = normalized_description or self.normalize_description(" ".join(filter(None, [description, counterparty]))) or ""
        history_based = self._resolve_category_from_description_history(
            categories=categories,
            normalized_description=normalized_description,
            transaction_type=transaction_type,
            history=history,
        )
        if history_based is not None:
            return history_based

        best_category: Category | None = None
        best_score = 0.0
        description_tokens = self._tokenize(normalized_description)
        for category in categories:
            if category.kind != transaction_type:
                continue
            keywords = self._build_category_keywords(category)
            if not keywords:
                continue
            hits = sum(1 for keyword in keywords if keyword in normalized_description)
            token_hits = sum(1 for token in description_tokens if token in keywords)
            score = hits * 1.2 + token_hits * 0.6
            if score > best_score:
                best_score = score
                best_category = category

        if best_category is not None and best_score >= 1.2:
            confidence = 0.8 if best_score >= 2.4 else 0.72
            return best_category.id, confidence, "Р С™Р В°РЎвЂљР ВµР С–Р С•РЎР‚Р С‘РЎРЏ Р Р…Р В°Р в„–Р Т‘Р ВµР Р…Р В° Р С—Р С• Р С”Р В»РЎР‹РЎвЂЎР ВµР Р†РЎвЂ№Р С РЎРѓР В»Р С•Р Р†Р В°Р С Р С‘ Р Р…Р В°Р В·Р Р†Р В°Р Р…Р С‘РЎР‹ Р С•Р С—Р ВµРЎР‚Р В°РЎвЂ Р С‘Р С‘"
        return None, 0.0, ""

    def _resolve_category_from_description_history(
        self,
        *,
        categories: list[Category],
        normalized_description: str,
        transaction_type: str,
        history: list[Transaction],
    ) -> tuple[int | None, float, str] | None:
        if not normalized_description:
            return None

        current_tokens = self._tokenize(normalized_description)
        category_by_id = {category.id: category for category in categories if category.kind == transaction_type}
        candidate_scores: Counter[int] = Counter()
        for item in history:
            if item.category_id is None or item.category_id not in category_by_id:
                continue
            history_description = self.normalize_description(item.normalized_description or item.description)
            if not history_description:
                continue
            history_tokens = self._tokenize(history_description)
            overlap = len(current_tokens & history_tokens)
            exact_match = history_description == normalized_description
            single_token_match = bool(current_tokens) and current_tokens == history_tokens and len(current_tokens) == 1
            if overlap >= 2 or exact_match or single_token_match:
                candidate_scores[item.category_id] += max(overlap, 2 if exact_match or single_token_match else overlap)

        if not candidate_scores:
            return None

        category_id, overlap_score = candidate_scores.most_common(1)[0]
        if overlap_score < 2:
            return None

        category = category_by_id.get(category_id)
        if category is None:
            return None
        confidence = 0.86 if overlap_score >= 4 else 0.78
        return category.id, confidence, "Р С™Р В°РЎвЂљР ВµР С–Р С•РЎР‚Р С‘РЎРЏ Р С•Р С—РЎР‚Р ВµР Т‘Р ВµР В»Р ВµР Р…Р В° Р С—Р С• Р С—Р С•РЎвЂ¦Р С•Р В¶Р С‘Р С Р С•Р С—Р С‘РЎРѓР В°Р Р…Р С‘РЎРЏР С Р С‘Р В· Р С‘РЎРѓРЎвЂљР С•РЎР‚Р С‘Р С‘"

    def _find_history(self, *, user_id: int, normalized_description: str | None) -> list[Transaction]:
        if not normalized_description:
            return []

        sample = self.transaction_repo.list_transactions(
            user_id=user_id,
        )[:300]

        # Р РЋРЎР‚Р В°Р Р†Р Р…Р С‘Р Р†Р В°Р ВµР С РЎвЂЎР ВµРЎР‚Р ВµР В· normalize_for_rule: РЎРЊРЎвЂљР С• Р С—Р С•Р В·Р Р†Р С•Р В»РЎРЏР ВµРЎвЂљ Р Р…Р В°Р в„–РЎвЂљР С‘ РЎРѓР С•Р Р†Р С—Р В°Р Т‘Р ВµР Р…Р С‘РЎРЏ
        # Р Т‘Р В°Р В¶Р Вµ Р ВµРЎРѓР В»Р С‘ РЎвЂљРЎР‚Р В°Р Р…Р В·Р В°Р С”РЎвЂ Р С‘РЎРЏ РЎвЂ¦РЎР‚Р В°Р Р…Р С‘РЎвЂљ РЎРѓРЎвЂљР В°РЎР‚РЎвЂ№Р в„– normalized_description РЎРѓ Р Т‘Р В°РЎвЂљР С•Р в„–/РЎв‚¬РЎС“Р СР С•Р С.
        exact_matches = [
            item for item in sample
            if self.normalize_for_rule(item.normalized_description or item.description) == normalized_description
        ]
        if exact_matches:
            return exact_matches

        current_tokens = self._tokenize(normalized_description)
        fuzzy_matches: list[Transaction] = []
        for item in sample:
            candidate_description = self.normalize_for_rule(item.normalized_description or item.description)
            if not candidate_description:
                continue
            candidate_tokens = self._tokenize(candidate_description)
            overlap = len(current_tokens & candidate_tokens)
            exact_match = candidate_description == normalized_description
            single_token_match = bool(current_tokens) and current_tokens == candidate_tokens and len(current_tokens) == 1
            if overlap >= 2 or exact_match or single_token_match:
                fuzzy_matches.append(item)
        return fuzzy_matches[:25]

    @staticmethod
    def _extract_last4(value: str | None) -> str | None:
        if not value:
            return None
        match = LAST4_RX.search(value)
        return match.group(1) if match else None

    def _find_account_by_last4(self, accounts: list[Account], last4: str) -> Account | None:
        for account in accounts:
            account_last4 = self._extract_last4(account.name)
            if account_last4 == last4:
                return account
        return None

    def _find_account_in_text(
        self,
        *,
        accounts: list[Account],
        text: str,
        exclude_account_id: int | None = None,
    ) -> Account | None:
        haystack = self.normalize_description(text) or ""
        if not haystack:
            return None

        for account in accounts:
            if exclude_account_id is not None and account.id == exclude_account_id:
                continue
            last4 = self._extract_last4(account.name)
            normalized_name = self.normalize_description(account.name) or ""
            # Use word-boundary check: last4 must appear as a standalone 4-digit number,
            # not embedded inside a longer digit sequence (e.g. SBP reference Р С’60782014520590).
            if last4 and re.search(r"(?<!\d)" + last4 + r"(?!\d)", haystack):
                return account
            if normalized_name and normalized_name in haystack:
                return account
        return None

    @staticmethod
    def _tokenize(value: str | None) -> set[str]:
        normalized = value or ""
        tokens: set[str] = set()
        for token in normalized.split():
            token = token.strip()
            if len(token) < 3 or token in STOP_WORDS or token.isdigit():
                continue
            tokens.add(token)
        return tokens

    def _build_category_keywords(self, category: Category) -> set[str]:
        normalized_name = self.normalize_description(category.name) or ""
        tokens = self._tokenize(normalized_name)
        keywords = set(tokens)
        for marker, aliases in CATEGORY_KEYWORD_LIBRARY.items():
            if marker in normalized_name:
                keywords.update(self.normalize_description(alias) or alias for alias in aliases)
        return {keyword for keyword in keywords if keyword}
