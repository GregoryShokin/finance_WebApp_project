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

NON_WORD_RX = re.compile(r"[^a-zа-яё0-9]+", re.I)
MULTISPACE_RX = re.compile(r"\s+")
LAST4_RX = re.compile(r"(?<!\d)(\d{4})(?!\d)")

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
    "продукт": (
        "pyaterochka", "пятерочка", "magnit", "магнит", "perekrestok", "перекресток", "лента",
        "ашан", "auchan", "spar", "дикси", "верный", "vprok", "самокат", "вкусвилл", "lavka",
        "grocery", "market", "еда", "food",
    ),
    "супермаркет": (
        "pyaterochka", "пятерочка", "magnit", "магнит", "perekrestok", "перекресток", "лента", "ашан",
        "auchan", "spar", "дикси", "верный", "market", "grocery",
    ),
    "каф": ("restaurant", "cafe", "coffee", "кофе", "шаверм", "шаурм", "burger", "pizza", "ролл", "sushi", "еда"),
    "ресторан": ("restaurant", "cafe", "coffee", "кофе", "burger", "pizza", "ролл", "sushi", "еда"),
    "достав": ("delivery", "самокат", "yandex lavka", "яндекс еда", "delivery club", "доставка"),
    "транспорт": ("metro", "метро", "автобус", "taxi", "uber", "yandex go", "яндекс go", "такси", "бензин", "fuel"),
    "такси": ("taxi", "uber", "yandex go", "яндекс go", "ситимобил", "drivee"),
    "авто": ("fuel", "azs", "газпром", "лукойл", "роснефть", "shell", "бензин", "топливо", "парковка"),
    "бензин": ("fuel", "azs", "газпром", "лукойл", "роснефть", "shell", "бензин", "топливо"),
    "аптек": ("apteka", "аптека", "аптеки", "36 6", "rigla", "еаптека", "фарм"),
    "здоров": ("medical", "clinic", "доктор", "медицина", "аптека", "apteka", "стомат", "анализ"),
    "связ": ("mts", "мтс", "megafon", "мегафон", "beeline", "билайн", "tele2", "yota", "internet", "интернет"),
    "интернет": ("internet", "wifi", "дом ру", "ростелеком", "мтс", "билайн", "мегафон"),
    "коммун": ("gkh", "жкх", "mosenergo", "water", "electricity", "квартплата", "электроэнерг", "газ", "вода"),
    "аренд": ("rent", "аренда", "landlord", "квартира"),
    "развлеч": ("cinema", "movie", "steam", "playstation", "netflix", "ivi", "spotify", "concert", "игр"),
    "подпис": ("subscription", "netflix", "spotify", "youtube", "icloud", "google one", "yandex plus", "подписка"),
    "маркетплейс": ("wildberries", "wb", "ozon", "яндекс маркет", "marketplace", "aliexpress", "avito"),
    "одеж": ("lamoda", "zara", "uniqlo", "wildberries", "wb", "ozon", "одеж", "обув"),
    "перевод": ("перевод", "система быстрых платежей", "сбп"),
    "налог": ("nalog", "fns", "фнс", "налог"),
    "зарплат": ("salary", "зарплата", "аванс", "payroll"),
    "кэшбэк": ("cashback", "кэшбэк"),
    "процент": ("interest", "процент", "deposit interest", "вклад"),
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
        text = str(value or "").lower().replace("ё", "е").strip()
        if not text:
            return None
        text = text.replace("сбп", "система быстрых платежей")
        text = NON_WORD_RX.sub(" ", text)
        text = MULTISPACE_RX.sub(" ", text).strip()
        return text or None

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
        normalized_description = self.normalize_description(" ".join(filter(None, [description, counterparty])))

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
            operation_reason = "Неизвестный тип операции заменён на regular"

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
            review_reasons.append("Не удалось определить счёт операции")

        requires_category = transaction_type == "expense" and operation_type != "transfer"
        if requires_category and category_id is None:
            review_reasons.append("Категория не определена автоматически")

        if operation_type == "transfer":
            if account_id is None:
                review_reasons.append("Для перевода не найден счёт списания")
            if target_account_id is None:
                review_reasons.append("Для перевода не найден счёт назначения")
            elif account_id == target_account_id:
                review_reasons.append("Для перевода счёт списания совпал со счётом назначения")

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
                return op_type, 0.96, f"Тип операции взят из истории похожих транзакций ({count} совп.)"

        haystack = self.normalize_description(" ".join([description, raw_type])) or ""
        if any(token in haystack for token in ["погашение тела кредита", "основного долга", "тело кредита"]):
            return "credit_payment", 0.88, "Определено как погашение тела кредита"
        if any(token in haystack for token in ["погашение", "задолжен"]):
            return "credit_payment", 0.84, "Определено как погашение кредита"
        if any(token in haystack for token in ["выдача кредита", "кредит выдан", "кредитные средства"]):
            return "credit_disbursement", 0.88, "Определено как выдача кредита"
        if any(token in haystack for token in ["перевод", "система быстрых платежей", "сбп", "между своими счетами"]):
            return "transfer", 0.82, "Определено как перевод"
        if any(token in haystack for token in ["покупка ценных бумаг", "покупка акций", "инвестици"]) and "продаж" not in haystack:
            return "investment_buy", 0.84, "Определено как инвестиционная покупка"
        if any(token in haystack for token in ["продажа ценных бумаг", "продажа акций", "продаж"]):
            return "investment_sell", 0.84, "Определено как инвестиционная продажа"
        return "regular", 0.65, "Использован тип regular по умолчанию"

    def _resolve_transaction_type(self, *, direction: Any, operation_type: str, history: list[Transaction]) -> str:
        if history:
            type_counter = Counter(item.type for item in history)
            if type_counter:
                resolved = type_counter.most_common(1)[0][0]
                if resolved in {"income", "expense"}:
                    return resolved
        direction_value = str(direction or "").strip().lower()
        if direction_value in {"income", "expense"}:
            return direction_value
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
                    return matched.id, 0.95, f"Счёт определён по маске {last4} из выписки"

        transfer_related_account = self._find_account_in_text(
            accounts=accounts,
            text=" ".join(filter(None, [description, counterparty])),
            exclude_account_id=session_account_id if operation_type == "transfer" and transaction_type == "income" else None,
        )
        if transfer_related_account is not None and operation_type == "transfer" and transaction_type == "income":
            return transfer_related_account.id, 0.9, "Счёт списания для входящего перевода найден в описании"

        normalized_description = self.normalize_description(description) or ""
        for account in accounts:
            account_name = self.normalize_description(account.name) or ""
            if account_name and account_name in normalized_description:
                return account.id, 0.86, "Счёт найден по названию в описании"

        if session_account_id is not None:
            return session_account_id, 0.78, "Использован счёт, выбранный в мастере импорта"
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
            return session_account_id, 0.96, "Счёт назначения взят из счёта, выбранного в мастере импорта"

        matched = self._find_account_in_text(
            accounts=accounts,
            text=" ".join(filter(None, [description, counterparty])),
            exclude_account_id=source_account_id,
        )
        if matched is not None:
            return matched.id, 0.9, "Счёт назначения найден в описании перевода"

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
            return matched.id, 0.9, "Счёт списания найден в описании входящего перевода"

        for account in accounts:
            if account.id not in {target_account_id, session_account_id}:
                return account.id, 0.35, "Источник перевода подобран как резервный счёт; требуется проверка"
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
        if operation_type == "transfer" or transaction_type != "expense":
            return None, 0.0, ""

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
            return best_category.id, confidence, "Категория найдена по ключевым словам и названию операции"
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
            if overlap >= 2:
                candidate_scores[item.category_id] += overlap

        if not candidate_scores:
            return None

        category_id, overlap_score = candidate_scores.most_common(1)[0]
        if overlap_score < 2:
            return None

        category = category_by_id.get(category_id)
        if category is None:
            return None
        confidence = 0.86 if overlap_score >= 4 else 0.78
        return category.id, confidence, "Категория определена по похожим описаниям из истории"

    def _find_history(self, *, user_id: int, normalized_description: str | None) -> list[Transaction]:
        if not normalized_description:
            return []

        sample = self.transaction_repo.list_transactions(
            user_id=user_id,
        )[:300]
        exact_matches = [
            item for item in sample
            if self.normalize_description(item.normalized_description or item.description) == normalized_description
        ]
        if exact_matches:
            return exact_matches

        current_tokens = self._tokenize(normalized_description)
        fuzzy_matches: list[Transaction] = []
        for item in sample:
            candidate_description = self.normalize_description(item.normalized_description or item.description)
            if not candidate_description:
                continue
            candidate_tokens = self._tokenize(candidate_description)
            overlap = len(current_tokens & candidate_tokens)
            if overlap >= 2:
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
            if last4 and last4 in haystack:
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
