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
from app.services.llm_service import LLMService

NON_WORD_RX = re.compile(r"[^a-zа-яёА-ЯЁ0-9]+", re.I)
MULTISPACE_RX = re.compile(r"\s+")
LAST4_RX = re.compile(r"(?<!\d)(\d{4})(?!\d)")
DIGITS_TOKEN_RX = re.compile(r"\b\d+\b")
PHONE_TOKEN_RX = re.compile(r"(?<!\d)(?:\+7|7|8)\d{10}(?!\d)")
ACCOUNT20_RX = re.compile(r"(?<!\d)(\d{20})(?!\d)")

# Р В Р’В Р РЋРЎвЂєР В Р’В Р РЋРІР‚СћР В Р’В Р РЋРІР‚СњР В Р’В Р вЂ™Р’ВµР В Р’В Р В РІР‚В¦Р В Р Р‹Р Р†Р вЂљРІвЂћвЂ“, Р В Р’В Р РЋРІР‚СњР В Р’В Р РЋРІР‚СћР В Р Р‹Р Р†Р вЂљРЎв„ўР В Р’В Р РЋРІР‚СћР В Р Р‹Р В РІР‚С™Р В Р Р‹Р Р†Р вЂљРІвЂћвЂ“Р В Р’В Р вЂ™Р’Вµ Р В Р’В Р РЋРІР‚ВР В Р’В Р СћРІР‚ВР В Р’В Р вЂ™Р’ВµР В Р’В Р В РІР‚В¦Р В Р Р‹Р Р†Р вЂљРЎв„ўР В Р’В Р РЋРІР‚ВР В Р Р‹Р Р†Р вЂљРЎвЂєР В Р’В Р РЋРІР‚ВР В Р Р‹Р Р†Р вЂљР’В Р В Р’В Р РЋРІР‚ВР В Р Р‹Р В РІР‚С™Р В Р Р‹Р РЋРІР‚СљР В Р Р‹Р В РІР‚в„–Р В Р Р‹Р Р†Р вЂљРЎв„ў Р В Р Р‹Р В РЎвЂњР В Р Р‹Р Р†Р вЂљРЎв„ўР В Р Р‹Р В РІР‚С™Р В Р’В Р вЂ™Р’В°Р В Р’В Р В РІР‚В¦Р В Р Р‹Р РЋРІР‚Сљ, Р В Р’В Р В РІР‚В Р В Р’В Р вЂ™Р’В°Р В Р’В Р вЂ™Р’В»Р В Р Р‹Р В РІР‚в„–Р В Р Р‹Р Р†Р вЂљРЎв„ўР В Р Р‹Р РЋРІР‚Сљ Р В Р’В Р РЋРІР‚ВР В Р’В Р вЂ™Р’В»Р В Р’В Р РЋРІР‚В Р В Р’В Р РЋРІР‚вЂќР В Р’В Р вЂ™Р’В»Р В Р’В Р вЂ™Р’В°Р В Р Р‹Р Р†Р вЂљРЎв„ўР В Р Р‹Р Р†Р вЂљР’ВР В Р’В Р вЂ™Р’В¶Р В Р’В Р В РІР‚В¦Р В Р Р‹Р Р†Р вЂљРІвЂћвЂ“Р В Р’В Р Р†РІР‚С›РІР‚вЂњ Р В Р Р‹Р В РІР‚С™Р В Р’В Р вЂ™Р’ВµР В Р’В Р Р†РІР‚С›РІР‚вЂњР В Р’В Р вЂ™Р’В»,
# Р В Р’В Р В РІР‚В¦Р В Р’В Р РЋРІР‚Сћ Р В Р’В Р В РІР‚В¦Р В Р’В Р вЂ™Р’Вµ Р В Р’В Р РЋР’ВР В Р’В Р вЂ™Р’ВµР В Р Р‹Р В РІР‚С™Р В Р Р‹Р Р†Р вЂљР Р‹Р В Р’В Р вЂ™Р’В°Р В Р’В Р В РІР‚В¦Р В Р Р‹Р Р†Р вЂљРЎв„ўР В Р’В Р вЂ™Р’В° Р В Р вЂ Р В РІР‚С™Р Р†Р вЂљРЎСљ Р В Р’В Р РЋРІР‚СћР В Р Р‹Р Р†Р вЂљРЎв„ўР В Р Р‹Р Р†Р вЂљРЎвЂєР В Р’В Р РЋРІР‚ВР В Р’В Р вЂ™Р’В»Р В Р Р‹Р В Р вЂ°Р В Р Р‹Р Р†Р вЂљРЎв„ўР В Р Р‹Р В РІР‚С™Р В Р’В Р РЋРІР‚СћР В Р’В Р В РІР‚В Р В Р Р‹Р Р†Р вЂљРІвЂћвЂ“Р В Р’В Р В РІР‚В Р В Р’В Р вЂ™Р’В°Р В Р’В Р вЂ™Р’ВµР В Р’В Р РЋР’В Р В Р’В Р РЋРІР‚вЂќР В Р Р‹Р В РІР‚С™Р В Р’В Р РЋРІР‚В Р В Р’В Р РЋРІР‚вЂќР В Р’В Р РЋРІР‚СћР В Р Р‹Р В РЎвЂњР В Р Р‹Р Р†Р вЂљРЎв„ўР В Р Р‹Р В РІР‚С™Р В Р’В Р РЋРІР‚СћР В Р’В Р вЂ™Р’ВµР В Р’В Р В РІР‚В¦Р В Р’В Р РЋРІР‚ВР В Р’В Р РЋРІР‚В Р В Р’В Р РЋРІР‚СњР В Р’В Р вЂ™Р’В»Р В Р Р‹Р В РІР‚в„–Р В Р Р‹Р Р†Р вЂљР Р‹Р В Р’В Р вЂ™Р’В° Р В Р’В Р РЋРІР‚вЂќР В Р Р‹Р В РІР‚С™Р В Р’В Р вЂ™Р’В°Р В Р’В Р В РІР‚В Р В Р’В Р РЋРІР‚ВР В Р’В Р вЂ™Р’В»Р В Р’В Р вЂ™Р’В°.
GEO_CURRENCY_NOISE: frozenset[str] = frozenset({
    # Р В Р’В Р В Р вЂ№Р В Р Р‹Р Р†Р вЂљРЎв„ўР В Р Р‹Р В РІР‚С™Р В Р’В Р вЂ™Р’В°Р В Р’В Р В РІР‚В¦Р В Р’В Р РЋРІР‚СћР В Р’В Р В РІР‚В Р В Р Р‹Р Р†Р вЂљРІвЂћвЂ“Р В Р’В Р вЂ™Р’Вµ Р В Р’В Р РЋРІР‚СњР В Р’В Р РЋРІР‚СћР В Р’В Р СћРІР‚ВР В Р Р‹Р Р†Р вЂљРІвЂћвЂ“
    "rus", "ru", "ukr", "kaz",
    # Р В Р’В Р Р†Р вЂљРЎС™Р В Р’В Р РЋРІР‚СћР В Р Р‹Р В РІР‚С™Р В Р’В Р РЋРІР‚СћР В Р’В Р СћРІР‚ВР В Р’В Р вЂ™Р’В° (Р В Р Р‹Р Р†Р вЂљРЎв„ўР В Р Р‹Р В РІР‚С™Р В Р’В Р вЂ™Р’В°Р В Р’В Р В РІР‚В¦Р В Р Р‹Р В РЎвЂњР В Р’В Р вЂ™Р’В»Р В Р’В Р РЋРІР‚ВР В Р Р‹Р Р†Р вЂљРЎв„ў)
    "moscow", "msc", "spb", "krd", "ekb", "nsk", "nnd", "kzn", "rnd",
    "volgodonsk", "volgograd", "krasnodar", "novosibirsk",
    # Р В Р’В Р РЋРІвЂћСћР В Р’В Р РЋРІР‚СћР В Р’В Р СћРІР‚ВР В Р Р‹Р Р†Р вЂљРІвЂћвЂ“ Р В Р’В Р В РІР‚В Р В Р’В Р вЂ™Р’В°Р В Р’В Р вЂ™Р’В»Р В Р Р‹Р В РІР‚в„–Р В Р Р‹Р Р†Р вЂљРЎв„ў
    "rub", "rur", "usd", "eur", "gbp", "cny", "mop", "kzt",
    # Р В Р’В Р РЋРЎСџР В Р’В Р вЂ™Р’В»Р В Р’В Р вЂ™Р’В°Р В Р Р‹Р Р†Р вЂљРЎв„ўР В Р Р‹Р Р†Р вЂљР’ВР В Р’В Р вЂ™Р’В¶Р В Р’В Р В РІР‚В¦Р В Р Р‹Р Р†Р вЂљРІвЂћвЂ“Р В Р’В Р вЂ™Р’Вµ Р В Р Р‹Р В РЎвЂњР В Р’В Р РЋРІР‚ВР В Р Р‹Р В РЎвЂњР В Р Р‹Р Р†Р вЂљРЎв„ўР В Р’В Р вЂ™Р’ВµР В Р’В Р РЋР’ВР В Р Р‹Р Р†Р вЂљРІвЂћвЂ“ / Р В Р Р‹Р В РІР‚С™Р В Р’В Р вЂ™Р’ВµР В Р’В Р Р†РІР‚С›РІР‚вЂњР В Р’В Р вЂ™Р’В»Р В Р Р‹Р Р†Р вЂљРІвЂћвЂ“ (Р В Р’В Р В РІР‚В¦Р В Р’В Р вЂ™Р’Вµ Р В Р’В Р РЋР’ВР В Р’В Р вЂ™Р’ВµР В Р Р‹Р В РІР‚С™Р В Р Р‹Р Р†Р вЂљР Р‹Р В Р’В Р вЂ™Р’В°Р В Р’В Р В РІР‚В¦Р В Р Р‹Р Р†Р вЂљРЎв„ў)
    "mir", "visa", "mastercard",
})

ALLOWED_OPERATION_TYPES = {
    "regular",
    "transfer",
    "investment_buy",
    "investment_sell",
    "credit_disbursement",
    "debt",
    "refund",
    "adjustment",
}

# DEPRECATED 2026-05-03: keyword-based category fallback removed from
# `_resolve_category`. This mapping is no longer consulted at runtime.
# Kept temporarily so out-of-tree callers / tests don't crash on import.
# Safe to delete in a follow-up cleanup pass.
CATEGORY_KEYWORD_LIBRARY: dict[str, tuple[str, ...]] = {
    'продукт': (
        "pyaterochka", 'пятерочка', "magnit", 'магнит', "perekrestok", 'перекресток', 'лента',
        'ашан', "auchan", "spar", 'дикси', 'верный', "vprok", 'самокат', 'вкусвилл', "lavka",
        "grocery", "market", 'еда', "food",
    ),
    'супермаркет': (
        "pyaterochka", 'пятерочка', "magnit", 'магнит', "perekrestok", 'перекресток', 'лента', 'ашан',
        "auchan", "spar", 'дикси', 'верный', "market", "grocery",
    ),
    'каф': ("restaurant", "cafe", "coffee", 'кофе', 'шаверм', 'шаурм', "burger", "pizza", 'ролл', "sushi", 'еда'),
    'ресторан': ("restaurant", "cafe", "coffee", 'кофе', "burger", "pizza", 'ролл', "sushi", 'еда'),
    'достав': ("delivery", 'самокат', "yandex lavka", 'яндекс еда', "delivery club", 'доставка'),
    'транспорт': ("metro", 'метро', 'автобус', "taxi", "uber", "yandex go", 'яндекс go', 'такси', 'бензин', "fuel"),
    'такси': ("taxi", "uber", "yandex go", 'яндекс go', 'ситимобил', "drivee"),
    'авто': ("fuel", "azs", 'газпром', 'лукойл', 'роснефть', "shell", 'бензин', 'топливо', 'парковка'),
    'бензин': ("fuel", "azs", 'газпром', 'лукойл', 'роснефть', "shell", 'бензин', 'топливо'),
    'аптек': ("apteka", 'аптека', 'аптеки', "36 6", "rigla", 'еаптека', 'фарм'),
    'здоров': ("medical", "clinic", 'доктор', 'медицина', 'аптека', "apteka", 'стомат', 'анализ'),
    'связ': ("mts", 'мтс', "megafon", 'мегафон', "beeline", 'билайн', "tele2", "yota", "internet", 'интернет'),
    'интернет': ("internet", "wifi", 'дом ру', 'ростелеком', 'мтс', 'билайн', 'мегафон'),
    'коммун': ("gkh", 'жкх', "mosenergo", "water", "electricity", 'квартплата', 'электроэнерг', 'газ', 'вода'),
    'аренд': ("rent", 'аренда', "landlord", 'квартира'),
    'развлеч': ("cinema", "movie", "steam", "playstation", "netflix", "ivi", "spotify", "concert", 'игр'),
    'подпис': ("subscription", "netflix", "spotify", "youtube", "icloud", "google one", "yandex plus", 'подписка'),
    'маркетплейс': ("wildberries", "wb", "ozon", 'яндекс маркет', "marketplace", "aliexpress", "avito"),
    'одеж': ("lamoda", "zara", "uniqlo", "wildberries", "wb", "ozon", 'одеж', 'обув'),
    'перевод': ('перевод', 'система быстрых платежей', 'сбп'),
    'налог': ("nalog", "fns", 'фнс', 'налог'),
    'зарплат': ("salary", 'зарплата', 'аванс', "payroll"),
    'кэшбэк': ("cashback", 'кэшбэк'),
    'процент': ("interest", 'процент', "deposit interest", 'вклад'),
}

STOP_WORDS = {
    "oplata", "payment", "card", "pokupka", "purchase", "perevod", "operaciya", "operatsiya", "tranzakciya",
    "transaction", "sbp", "mir", "visa", "mastercard", "schet", "scheta", "account", "rur", "rub", "pokupki",
    "pos", "retail", "sale", "spisanie", "zachislenie", "perechislenie", "perevodom", "oplatauslug",
}

ACCOUNT_MATCH_NOISE = {
    "bank", "debet", "debit", "credit", "bankovskij", "bankovskii",
    'банк', 'дебет', 'дебетовый', 'кредит', 'кредитный', 'карта', 'карточка', 'счет', 'счёт',
}


class TransactionEnrichmentService:
    def __init__(self, db: Session):
        self.db = db
        self.account_repo = AccountRepository(db)
        self.category_repo = CategoryRepository(db)
        self.transaction_repo = TransactionRepository(db)
        self.llm_service = LLMService()

    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        'Базовая нормализация: lowercase + убрать спецсимволы. Цифры сохраняются.'
        text = str(value or "").lower().replace('ё', 'е').strip()
        if not text:
            return None
        text = text.replace('сбп', 'система быстрых платежей')
        text = NON_WORD_RX.sub(" ", text)
        text = MULTISPACE_RX.sub(" ", text).strip()
        return text or None

    @classmethod
    def normalize_for_rule(cls, value: str | None) -> str | None:
        'Агрессивная нормализация для ключа правила и поля normalized_description.\n\n        Отбрасывает переменные части, которые меняются от операции к операции\n        и не идентифицируют мерчанта:\n          • все цифровые токены (даты, последние 4 цифры карты, ID терминала)\n          • гео/валютные шумовые токены (RUS, EUR, Volgodonsk и т.п.)\n          • стоп-слова платёжной индустрии (payment, card, sbp и т.п.)\n          • «система быстрых платежей» — идентификатор рейла, не мерчанта\n          • токены короче 3 символов\n\n        Примеры:\n          "POPLAVO Volgodonsk RUS 28.03"  →  "poplavo"\n          "Яндекс Еда 12345"              →  "яндекс еда"\n          "26033 MOP SBP 0387 28.03"      →  None  (мерчант не определяется)\n          "Поплавок"                       →  "поплавок"\n        '
        text = cls.normalize_description(value)
        if not text:
            return None

        # Р В Р в‚¬Р В Р’В±Р В РЎвЂР РЋР вЂљР В Р’В°Р В Р’ВµР В РЎВ Р В РЎвЂ”Р В Р’В»Р В Р’В°Р РЋРІР‚С™Р РЋРІР‚ВР В Р’В¶Р В Р вЂ¦Р РЋРІР‚в„–Р В РІвЂћвЂ“ Р РЋР вЂљР В Р’ВµР В РІвЂћвЂ“Р В Р’В» Р Р†Р вЂљРІР‚Сњ Р В РЎвЂўР В Р вЂ¦ Р В Р вЂ¦Р В Р’Вµ Р В РЎвЂўР В РЎвЂ”Р В РЎвЂР РЋР С“Р РЋРІР‚в„–Р В Р вЂ Р В Р’В°Р В Р’ВµР РЋРІР‚С™ Р В РЎВР В Р’ВµР РЋР вЂљР РЋРІР‚РЋР В Р’В°Р В Р вЂ¦Р РЋРІР‚С™Р В Р’В°
        text = text.replace('система быстрых платежей', " ")

        # Р В Р Р‹Р В РЎвЂўР РЋРІР‚В¦Р РЋР вЂљР В Р’В°Р В Р вЂ¦Р РЋР РЏР В Р’ВµР В РЎВ Р РЋРІР‚С™Р В Р’ВµР В Р’В»Р В Р’ВµР РЋРІР‚С›Р В РЎвЂўР В Р вЂ¦ Р В РЎвЂќР В Р’В°Р В РЎвЂќ Р РЋРЎвЂњР РЋР С“Р РЋРІР‚С™Р В РЎвЂўР В РІвЂћвЂ“Р РЋРІР‚РЋР В РЎвЂР В Р вЂ Р РЋРІР‚в„–Р В РІвЂћвЂ“ Р РЋРІР‚С™Р В РЎвЂўР В РЎвЂќР В Р’ВµР В Р вЂ¦ Р В РЎвЂ”Р РЋР вЂљР В Р’В°Р В Р вЂ Р В РЎвЂР В Р’В»Р В Р’В°: Р В РЎвЂўР В Р вЂ¦ Р В Р вЂ Р В Р’В°Р В Р’В¶Р В Р’ВµР В Р вЂ¦ Р В РўвЂР В Р’В»Р РЋР РЏ Р В Р’В°Р РЋР вЂљР В Р’ВµР В Р вЂ¦Р В РўвЂР В Р вЂ¦Р РЋРІР‚в„–Р РЋРІР‚В¦,
        # Р В РЎвЂќР В РЎвЂўР В РЎВР В РЎВР РЋРЎвЂњР В Р вЂ¦Р В Р’В°Р В Р’В»Р РЋР Р‰Р В Р вЂ¦Р РЋРІР‚в„–Р РЋРІР‚В¦ Р В РЎвЂ Р В РўвЂР РЋР вЂљР РЋРЎвЂњР В РЎвЂ“Р В РЎвЂР РЋРІР‚В¦ Р В РЎвЂ”Р В Р’В»Р В Р’В°Р РЋРІР‚С™Р В Р’ВµР В Р’В¶Р В Р’ВµР В РІвЂћвЂ“ Р В РЎвЂ”Р В РЎвЂў Р В Р вЂ¦Р В РЎвЂўР В РЎВР В Р’ВµР РЋР вЂљР РЋРЎвЂњ Р РЋРІР‚С™Р В Р’ВµР В Р’В»Р В Р’ВµР РЋРІР‚С›Р В РЎвЂўР В Р вЂ¦Р В Р’В°, Р В Р вЂ¦Р В РЎвЂў Р В Р вЂ¦Р В Р’Вµ Р В РўвЂР В РЎвЂўР В Р’В»Р В Р’В¶Р В Р’ВµР В Р вЂ¦ Р РЋР С“Р В РЎВР В Р’ВµР РЋРІвЂљВ¬Р В РЎвЂР В Р вЂ Р В Р’В°Р РЋРІР‚С™Р РЋР Р‰Р РЋР С“Р РЋР РЏ
        # Р РЋР С“ Р В РЎвЂ”Р РЋР вЂљР В РЎвЂўР РЋРІР‚РЋР В РЎвЂР В РЎВ Р РЋРІР‚В Р В РЎвЂР РЋРІР‚С›Р РЋР вЂљР В РЎвЂўР В Р вЂ Р РЋРІР‚в„–Р В РЎВ Р РЋРІвЂљВ¬Р РЋРЎвЂњР В РЎВР В РЎвЂўР В РЎВ Р В РЎвЂР В Р’В· Р В РЎвЂўР В РЎвЂ”Р В РЎвЂР РЋР С“Р В Р’В°Р В Р вЂ¦Р В РЎвЂР РЋР РЏ.
        phone_tokens = []
        for match in PHONE_TOKEN_RX.findall(text):
            digits = re.sub(r"\D", "", match)
            if len(digits) == 11:
                phone_tokens.append(f"phone_{digits}")
        text = PHONE_TOKEN_RX.sub(" ", text)

        # Р В Р в‚¬Р В Р’В±Р В РЎвЂР РЋР вЂљР В Р’В°Р В Р’ВµР В РЎВ Р В РЎвЂ”Р РЋР вЂљР В РЎвЂўР РЋРІР‚РЋР В РЎвЂР В Р’Вµ Р РЋРІР‚В Р В РЎвЂР РЋРІР‚С›Р РЋР вЂљР В РЎвЂўР В Р вЂ Р РЋРІР‚в„–Р В Р’Вµ Р РЋРІР‚С™Р В РЎвЂўР В РЎвЂќР В Р’ВµР В Р вЂ¦Р РЋРІР‚в„–: Р В РўвЂР В Р’В°Р РЋРІР‚С™Р РЋРІР‚в„–, terminal id, reference id Р В РЎвЂ Р РЋРІР‚С™.Р В РЎвЂ”.
        text = DIGITS_TOKEN_RX.sub(" ", text)
        text = MULTISPACE_RX.sub(" ", text).strip()

        # Р В Р’В¤Р В РЎвЂР В Р’В»Р РЋР Р‰Р РЋРІР‚С™Р РЋР вЂљР РЋРЎвЂњР В Р’ВµР В РЎВ Р РЋРІР‚С™Р В РЎвЂўР В РЎвЂќР В Р’ВµР В Р вЂ¦Р РЋРІР‚в„–
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
        accounts_cache: list | None = None,
        categories_cache: list | None = None,
        history_sample_cache: list | None = None,
        skip_llm: bool = True,
    ) -> dict[str, Any]:
        description = str(normalized_payload.get("description") or "").strip()
        raw_type = str(normalized_payload.get("operation_type") or normalized_payload.get("type") or "").strip()
        counterparty = str(normalized_payload.get("counterparty") or normalized_payload.get("merchant") or "").strip()
        account_hint = str(normalized_payload.get("account_hint") or normalized_payload.get("account_number") or "").strip()
        # join description + counterparty so rule lookup sees both fields
        normalized_description = self.normalize_for_rule(" ".join(filter(None, [description, counterparty])))

        history = self._find_history(
            user_id=user_id,
            normalized_description=normalized_description,
            history_sample=history_sample_cache,
        )
        accounts = accounts_cache if accounts_cache is not None else self.account_repo.list_by_user(user_id)
        categories = categories_cache if categories_cache is not None else self.category_repo.list(user_id=user_id)

        operation_type, operation_confidence, operation_reason = self._resolve_operation_type(
            description=description,
            raw_type=raw_type,
            history=history,
        )
        if operation_type not in ALLOWED_OPERATION_TYPES:
            operation_type = "regular"
            operation_confidence = max(operation_confidence, 0.7)
            operation_reason = 'Неизвестный тип операции заменён на regular'


        # Auto-detect inter-account transfer: if we did not yet identify a transfer
        # by keywords, check whether any of the user accounts is mentioned in the
        # description / counterparty.  This covers cross-bank transfers where the
        # source bank names the destination bank or its account number in the row.
        if operation_type not in ("transfer", "credit_disbursement", "investment_buy", "investment_sell"):
            _detected_transfer_target = self._find_account_in_text(
                accounts=accounts,
                text=" ".join(filter(None, [description, counterparty])),
                exclude_account_id=session_account_id,
            )
            if _detected_transfer_target is not None:
                operation_type = "transfer"
                operation_confidence = 0.85
                operation_reason = "определён перевод: в описании найдены реквизиты другого счёта"

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

        # §12.1 + §5.2 v1.1: a transfer without a resolved target is an
        # integrity problem — NOT a reason to silently downgrade to regular.
        # Downgrading hid the row as a valid regular expense and prevented
        # the cross-session transfer matcher from pairing it (matcher only
        # looks at op=transfer candidates). The correct response is to leave
        # op=transfer and let _gate_transfer_integrity escalate status to
        # warning (preview) → error (post-matcher / commit guard).
        # The old demotion code is removed; the gate is already wired.


        category_id, category_confidence, category_reason = self._resolve_category(
            categories=categories,
            history=history,
            normalized_description=normalized_description,
            operation_type=operation_type,
            transaction_type=transaction_type,
            description=description,
            counterparty=counterparty,
            skip_llm=skip_llm,
        )

        review_reasons: list[str] = []
        if account_id is None:
            review_reasons.append('Не удалось определить счёт операции')

        if operation_type == "transfer":
            if account_id is None:
                review_reasons.append('Для перевода не найден счёт списания')
            if target_account_id is None:
                review_reasons.append('Для перевода не найден счёт назначения')
            elif account_id == target_account_id:
                review_reasons.append('Для перевода счёт списания совпал со счётом назначения')

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
        # Keyword-based detection runs FIRST — explicit signals override history.
        haystack = self.normalize_description(" ".join([description, raw_type])) or ""

        # Transfer keywords — только переводы между СВОИМИ счетами.
        # "Внешний перевод по номеру телефона" — это платёж другому человеку,
        # он остаётся regular с категорией (врач, аренда и т.д.).
        #
        # STRONG (confidence 0.92): явно между своими счетами → keeper даже без target.
        # Банковские термины «внутренний/внутрибанковский/межбанковский перевод»
        # — это семантически тоже движение между счетами, эквивалентны явным
        # фразам выше. До фикса они лежали в WEAK (0.70) и валились ниже порога
        # 0.88 в caller, из-за чего одна сторона перевода (например, Тинькофф
        # Дебет: «Внутренний перевод на договор …») классифицировалась как
        # regular, а вторая (например, Тинькофф Сплит: «Внутрибанковский
        # перевод с договора …») — как transfer. Matcher не мог свести их,
        # потому что match идёт на уже размеченных операциях.
        if any(t in haystack for t in [
            "перевод между счетами",
            "перевод на свой счет",
            "перевод на свой счёт",
            "пополнение своего счета",
            "пополнение своего счёта",
            "внутрибанковский перевод",
            "внутренний перевод",
            "межбанковский перевод",
        ]):
            return "transfer", 0.92, "перевод по ключевым словам (явно между своими счетами)"

        # WEAK (confidence 0.70): банковский термин — может быть договор/кредит/ссуда.
        # Если target_account_id не найден → downgrade до regular (порог 0.88 в caller).
        if any(t in haystack for t in [
            "зачислено по договору",
            # C2A (Card-to-Account) — межбанковский перевод через протокол C2A.
            # Т-Банк отображает как "Операция в других кредитных организациях YandexBank_C2A...".
            # Если пользователь импортировал вторую сторону (Яндекс Банк) — transfer matcher найдёт пару.
            "c2a",
        ]):
            return "transfer", 0.70, "возможный перевод по ключевым словам (требует подтверждения счёта)"

        # Credit card / loan repayment from a debit account → transfer to credit account.
        if any(t in haystack for t in [
            "погашение кредита",
            "погашение задолженности",
            "погашение основного долга",
            "погашение долга",
            "погашение по договору",
            "оплата кредита",
            "платеж по кредиту",
            "платёж по кредиту",
        ]):
            return "transfer", 0.90, "погашение кредита: перевод на кредитный счёт"

        # Refund
        if any(t in haystack for t in [
            "возврат покупки",
            "возврат средств",
            "возврат платежа",
            "возврат денег",
            "возврат по операции",
            "возврат товара",
        ]):
            return "refund", 0.88, "возврат по ключевым словам"

        # Credit disbursement
        if any(t in haystack for t in [
            "зачисление кредита",
            "выдача кредита",
            "кредитные средства",
        ]):
            return "credit_disbursement", 0.88, "выдача кредита по ключевым словам"

        # Investment buy/sell
        if any(t in haystack for t in [
            "покупка ценных бумаг",
            "покупка бумаг биржа",
            "активов биржа",
        ]) and "продажа" not in haystack:
            return "investment_buy", 0.84, "инвестиции покупка по ключевым словам"
        if any(t in haystack for t in [
            "продажа ценных бумаг",
            "продажа бумаг",
            "продажа активов",
        ]):
            return "investment_sell", 0.84, "инвестиции продажа по ключевым словам"

        # History-based detection — only used when keywords give no signal.
        pair_counter = Counter((item.operation_type, item.type) for item in history)
        if pair_counter:
            (op_type, _), count = pair_counter.most_common(1)[0]
            # Require stronger signal for non-regular types to avoid false positives
            threshold = 3 if op_type == "transfer" else 2
            if count >= threshold and op_type in ALLOWED_OPERATION_TYPES:
                return op_type, 0.88, f"из истории транзакций ({count} совпад.)"

        return "regular", 0.65, "не распознано явно, ставим regular по умолчанию"


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
                    return matched.id, 0.95, f"Счёт определён по маске {last4} из выписки"

        # Text matching is only used to find the SOURCE of an INCOME transfer
        # (i.e. who sent the money to this account). For EXPENSE transfers the
        # source is always session_account_id — that is a §4.1 fact (the bank
        # statement belongs to the session's account, so every row in it was
        # paid FROM that account). Overwriting session_account_id with a
        # text-matched account for expense transfers puts the TARGET account
        # in the source field, which then causes _resolve_target_account to
        # find nothing (it already excluded the wrong "source") and triggers
        # the transfer→regular demotion — breaking matcher pairing.
        if operation_type == "transfer" and transaction_type == "income":
            transfer_related_account = self._find_account_in_text(
                accounts=accounts,
                text=" ".join(filter(None, [description, counterparty])),
                exclude_account_id=session_account_id,
            )
            if transfer_related_account is not None:
                return transfer_related_account.id, 0.9, "matched account name in description (transfer)"

        if session_account_id is not None:
            return session_account_id, 0.78, 'Использован счёт, выбранный в мастере импорта'
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
            return session_account_id, 0.96, 'Счёт назначения взят из счёта, выбранного в мастере импорта'


        # For credit repayments: prefer is_credit=True accounts that are not the source.
        haystack_lower = description.lower()
        is_credit_repayment = any(kw in haystack_lower for kw in [
            "погашение кредита",
            "погашение задолженности",
            "погашение основного долга",
            "погашение долга",
            "погашение по договору",
            "оплата кредита",
            "платеж по кредиту",
            "платёж по кредиту",
        ])
        if is_credit_repayment:
            # Credit-target accounts include credit cards, loans, and installment cards.
            # "КК" (кредитная карта) in description → prefer credit_card type specifically.
            credit_type_values = {"credit_card", "credit", "installment_card"}
            has_kk_marker = " кк" in haystack_lower or "-кк" in haystack_lower or "кк " in haystack_lower

            all_credit_targets = [
                a for a in accounts
                if getattr(a, "account_type", "regular") in credit_type_values
                and a.id != source_account_id
            ]

            # If description explicitly mentions КК, narrow to credit cards only
            if has_kk_marker:
                card_only = [a for a in all_credit_targets if getattr(a, "account_type", "") == "credit_card"]
                if card_only:
                    all_credit_targets = card_only

            # Prefer same-bank: extract first token from source name (e.g. "Озон Дебет" → "озон")
            source_account = next((a for a in accounts if a.id == source_account_id), None)
            if source_account and all_credit_targets:
                source_tokens = [t for t in (source_account.name or "").lower().split() if len(t) >= 3]
                source_prefix = source_tokens[0] if source_tokens else None
                if source_prefix:
                    same_bank = [a for a in all_credit_targets if source_prefix in (a.name or "").lower()]
                    if len(same_bank) == 1:
                        return same_bank[0].id, 0.92, f"кредитный счёт того же банка ({source_prefix})"
                    if len(same_bank) > 1:
                        all_credit_targets = same_bank

            if len(all_credit_targets) == 1:
                return all_credit_targets[0].id, 0.82, "единственный подходящий кредитный счёт"
            if len(all_credit_targets) > 1:
                matched_credit = self._find_account_in_text(
                    accounts=all_credit_targets,
                    text=description,
                    exclude_account_id=source_account_id,
                )
                if matched_credit is not None:
                    return matched_credit.id, 0.90, "кредитный счёт найден в описании"

        matched = self._find_account_in_text(
            accounts=accounts,
            text=" ".join(filter(None, [description, counterparty])),
            exclude_account_id=source_account_id,
        )
        if matched is not None:
            return matched.id, 0.9, 'Счёт назначения найден в описании перевода'

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
            return matched.id, 0.9, 'Счёт списания найден в описании входящего перевода'

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
        skip_llm: bool = False,
    ) -> tuple[int | None, float, str]:
        # Transfers never need a category — they are not spending.
        if operation_type == "transfer":
            return None, 0.0, ""
        # Refunds are income rows that compensate past expenses at the same
        # counterparty — they must land in the *expense-side* category of
        # that counterparty (e.g. a KOFEMOLOKO refund → «Кафе и рестораны»)
        # so analytics can subtract them from the category total. Here we
        # short-circuit the normal expense flow: if history at this
        # counterparty has a dominant expense category, use it. Otherwise
        # fall through with None — the cluster will sit in attention until
        # the user assigns a category manually.
        if operation_type == "refund":
            refund_category_counter = Counter(
                item.category_id for item in history
                if item.category_id is not None and item.type == "expense"
            )
            if refund_category_counter:
                category_id, count = refund_category_counter.most_common(1)[0]
                category = next((item for item in categories if item.id == category_id), None)
                if category and category.kind == "expense":
                    return category.id, 0.92, f"возврат → категория из истории расходов ({count} совпад.)"
            return None, 0.0, ""
        if transaction_type != "expense":
            return None, 0.0, ""

        # Loan interest: bank-specific phrase that enricher can't infer from
        # history on first import. Resolve directly to the system category
        # «Проценты по кредитам» (created for every user by CategoryService).
        _haystack = self.normalize_description(description) or ""
        if any(t in _haystack for t in [
            "погашение процентов",
            "проценты за пользование",
            "проценты по кредиту",
            "проценты по договору",
            "проценты по кредитному",
        ]):
            _interest_cat = next(
                (c for c in categories if getattr(c, "is_system", False) and c.name == "Проценты по кредитам"),
                None,
            )
            if _interest_cat is not None:
                return _interest_cat.id, 0.92, "проценты по кредиту: системная категория"

        category_counter = Counter(item.category_id for item in history if item.category_id is not None)
        if category_counter:
            category_id, count = category_counter.most_common(1)[0]
            category = next((item for item in categories if item.id == category_id), None)
            if category and category.kind == transaction_type:
                return category.id, 0.96, f"Категория взята из истории похожих транзакций ({count} совп.)"

        normalized_description = normalized_description or self.normalize_description(" ".join(filter(None, [description, counterparty]))) or ""
        history_based = self._resolve_category_from_description_history(
            categories=categories,
            normalized_description=normalized_description,
            transaction_type=transaction_type,
            history=history,
        )
        if history_based is not None:
            return history_based

        # Decision 2026-05-03: keyword-based category fallback removed.
        # Раньше CATEGORY_KEYWORD_LIBRARY (e.g. 'продукт' → "market", "grocery")
        # автоматически назначал категорию по совпадению одного токена в описании
        # — например YANDEX*5399*MARKET → "Продукты" из-за подстроки "market".
        # Это создавало иллюзию "LLM-модерации" даже после её отключения и
        # приводило к ложным категориям, которые пользователь должен был переучивать.
        # Категория теперь резолвится только из:
        #   - явных правил (transaction_category_rules)
        #   - истории транзакций пользователя (Counter по counterparty)
        #   - истории по нормализованному описанию (_resolve_category_from_description_history)
        #   - системных категорий ("Проценты по кредитам") по точному keyword-маркеру
        # Если ничего не нашли — None, строка идёт в attention для ручного выбора.
        # LLM-fallback также удалён — модерация выключена в imports API (см. 2026-05-03).
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
        return category.id, confidence, 'Категория определена по похожим описаниям из истории'

    def _find_history(self, *, user_id: int, normalized_description: str | None, history_sample: list | None = None) -> list[Transaction]:
        if not normalized_description:
            return []

        sample = history_sample if history_sample is not None else self.transaction_repo.list_transactions(
            user_id=user_id,
        )[:300]

        # Р В Р’В Р В Р вЂ№Р В Р Р‹Р В РІР‚С™Р В Р’В Р вЂ™Р’В°Р В Р’В Р В РІР‚В Р В Р’В Р В РІР‚В¦Р В Р’В Р РЋРІР‚ВР В Р’В Р В РІР‚В Р В Р’В Р вЂ™Р’В°Р В Р’В Р вЂ™Р’ВµР В Р’В Р РЋР’В Р В Р Р‹Р Р†Р вЂљР Р‹Р В Р’В Р вЂ™Р’ВµР В Р Р‹Р В РІР‚С™Р В Р’В Р вЂ™Р’ВµР В Р’В Р вЂ™Р’В· normalize_for_rule: Р В Р Р‹Р В Р Р‰Р В Р Р‹Р Р†Р вЂљРЎв„ўР В Р’В Р РЋРІР‚Сћ Р В Р’В Р РЋРІР‚вЂќР В Р’В Р РЋРІР‚СћР В Р’В Р вЂ™Р’В·Р В Р’В Р В РІР‚В Р В Р’В Р РЋРІР‚СћР В Р’В Р вЂ™Р’В»Р В Р Р‹Р В Р РЏР В Р’В Р вЂ™Р’ВµР В Р Р‹Р Р†Р вЂљРЎв„ў Р В Р’В Р В РІР‚В¦Р В Р’В Р вЂ™Р’В°Р В Р’В Р Р†РІР‚С›РІР‚вЂњР В Р Р‹Р Р†Р вЂљРЎв„ўР В Р’В Р РЋРІР‚В Р В Р Р‹Р В РЎвЂњР В Р’В Р РЋРІР‚СћР В Р’В Р В РІР‚В Р В Р’В Р РЋРІР‚вЂќР В Р’В Р вЂ™Р’В°Р В Р’В Р СћРІР‚ВР В Р’В Р вЂ™Р’ВµР В Р’В Р В РІР‚В¦Р В Р’В Р РЋРІР‚ВР В Р Р‹Р В Р РЏ
        # Р В Р’В Р СћРІР‚ВР В Р’В Р вЂ™Р’В°Р В Р’В Р вЂ™Р’В¶Р В Р’В Р вЂ™Р’Вµ Р В Р’В Р вЂ™Р’ВµР В Р Р‹Р В РЎвЂњР В Р’В Р вЂ™Р’В»Р В Р’В Р РЋРІР‚В Р В Р Р‹Р Р†Р вЂљРЎв„ўР В Р Р‹Р В РІР‚С™Р В Р’В Р вЂ™Р’В°Р В Р’В Р В РІР‚В¦Р В Р’В Р вЂ™Р’В·Р В Р’В Р вЂ™Р’В°Р В Р’В Р РЋРІР‚СњР В Р Р‹Р Р†Р вЂљР’В Р В Р’В Р РЋРІР‚ВР В Р Р‹Р В Р РЏ Р В Р Р‹Р Р†Р вЂљР’В¦Р В Р Р‹Р В РІР‚С™Р В Р’В Р вЂ™Р’В°Р В Р’В Р В РІР‚В¦Р В Р’В Р РЋРІР‚ВР В Р Р‹Р Р†Р вЂљРЎв„ў Р В Р Р‹Р В РЎвЂњР В Р Р‹Р Р†Р вЂљРЎв„ўР В Р’В Р вЂ™Р’В°Р В Р Р‹Р В РІР‚С™Р В Р Р‹Р Р†Р вЂљРІвЂћвЂ“Р В Р’В Р Р†РІР‚С›РІР‚вЂњ normalized_description Р В Р Р‹Р В РЎвЂњ Р В Р’В Р СћРІР‚ВР В Р’В Р вЂ™Р’В°Р В Р Р‹Р Р†Р вЂљРЎв„ўР В Р’В Р РЋРІР‚СћР В Р’В Р Р†РІР‚С›РІР‚вЂњ/Р В Р Р‹Р Р†РІР‚С™Р’В¬Р В Р Р‹Р РЋРІР‚СљР В Р’В Р РЋР’ВР В Р’В Р РЋРІР‚СћР В Р’В Р РЋР’В.
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

    def _account_match_tokens(self, account_name: str | None) -> set[str]:
        normalized_name = self.normalize_description(account_name) or ""
        return {
            token
            for token in self._tokenize(normalized_name)
            if token not in ACCOUNT_MATCH_NOISE
        }

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

        haystack_tokens = self._tokenize(haystack)
        best_account: Account | None = None
        best_score = 0.0

        for account in accounts:
            if exclude_account_id is not None and account.id == exclude_account_id:
                continue

            last4 = self._extract_last4(account.name)
            normalized_name = self.normalize_description(account.name) or ""
            # Use word-boundary check: last4 must appear as a standalone 4-digit number,
            # not embedded inside a longer digit sequence (e.g. SBP reference Р В Р’В Р РЋРІР‚в„ў60782014520590).
            if last4 and re.search(r"(?<!\d)" + last4 + r"(?!\d)", haystack):
                return account
            if normalized_name and re.search(r"(?<!\w)" + re.escape(normalized_name) + r"(?!\w)", haystack):
                return account

            # Match by contract_number / statement_account_number stored on the account.
            # Covers the case where the description contains the full 20-digit Russian
            # account number or the contract number recorded when the user linked their statement.
            for acct_num in filter(None, [account.contract_number, account.statement_account_number]):
                if re.search(r"(?<!\d)" + re.escape(acct_num) + r"(?!\d)", haystack):
                    return account
                if len(acct_num) >= 4 and acct_num[-4:].isdigit():
                    num_last4 = acct_num[-4:]
                    if re.search(r"(?<!\d)" + num_last4 + r"(?!\d)", haystack):
                        return account

            account_tokens = self._account_match_tokens(account.name)
            if not account_tokens:
                continue

            overlap = haystack_tokens & account_tokens
            if not overlap:
                continue

            score = sum(max(len(token), 4) for token in overlap)
            if overlap == account_tokens:
                score += 4
            elif len(overlap) >= 2:
                score += 2

            if score > best_score:
                best_account = account
                best_score = score

        return best_account if best_score >= 5 else None

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
        """DEPRECATED 2026-05-03 — see CATEGORY_KEYWORD_LIBRARY note. No longer
        called from `_resolve_category`. Kept to avoid breaking external callers.
        """
        normalized_name = self.normalize_description(category.name) or ""
        tokens = self._tokenize(normalized_name)
        keywords = set(tokens)
        for marker, aliases in CATEGORY_KEYWORD_LIBRARY.items():
            if marker in normalized_name:
                keywords.update(self.normalize_description(alias) or alias for alias in aliases)
        return {keyword for keyword in keywords if keyword}
