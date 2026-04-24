"""Per-cluster LLM moderator (И-08 Phase 4.2).

Input: a `Cluster` from `import_cluster_service.py` (Phase 3.2) and the user's
context (accounts, categories, active rules).

Output: a `ClusterHypothesis` — structured guess from the LLM about
operation_type/direction/category and an optional follow-up question the LLM
itself suggests asking the user. The moderator service NEVER writes to the
database: it returns a hypothesis, the caller decides what to persist.

**Anonymization invariant** (Phase 4.7): the payload sent to the LLM contains
only the cluster `skeleton` and example skeletons — no raw phone numbers,
contracts, IBANs, cards, or person names. A unit test asserts this by
feeding a row with PII-looking tokens and inspecting the prompt the
provider receives.

**Prompt caching** (Phase 4.8): the `system` block is tagged with
`cache_key="moderator:v1:{user_id}"` so Anthropic reuses the cache across
clusters of the same session.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.category import Category
from app.services.import_cluster_service import Cluster
from app.services.llm import LLMProvider, LLMUnavailableError, get_provider
from app.services.llm.base import LLMResult

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_TEMPLATE = """Ты — модератор банковского импорта для личного финансового приложения.

Пользователь загрузил выписку. Похожие строки сгруппированы в кластеры. Для каждого кластера ты получаешь:
- нормализованный скелет описания (идентификаторы уже заменены на плейсхолдеры: <PHONE>, <CONTRACT>, <IBAN>, <CARD>, <PERSON>, <ORG>, <AMOUNT>, <DATE>),
- направление (income/expense/unknown),
- число одинаковых строк и суммарную сумму,
- банк/счёт,
- список категорий пользователя,
- список его активных правил с аналогичным описанием (если есть).

Твоя задача — выбрать:
1. operation_type — один из: "regular", "transfer", "refund", "investment_buy", "investment_sell", "credit_disbursement".
   - "refund" — это возврат средств от продавца (отмена покупки, chargeback, возврат товара). Всегда income по направлению. Категория наследуется от прошлых покупок у этого же продавца, а не из доходных категорий.
   - ВАЖНО: "credit_payment" запрещён. Платёж по кредиту в выписке → "transfer" (тело долга уходит на кредитный счёт); проценты при этом идут отдельной строкой как "regular" с категорией «Проценты по кредитам». Никогда не возвращай "credit_payment".
2. direction — "income" или "expense" (даже если во входе "unknown"). Для refund всегда "income".
3. predicted_category_id — ID категории из списка пользователя, или null если это transfer/investment/credit (тогда категория не нужна). Для refund — категория из истории расходов у этого продавца (expense-kind), чтобы возврат компенсировал расходы в той же категории.
4. confidence ∈ [0, 1]:
   - 0.9+ — очевидный случай (имя бренда, ключевые слова, прямая аналогия).
   - 0.7-0.9 — вероятный случай.
   - <0.7 — не угадывай, верни confidence меньше 0.7 и сформулируй follow_up_question.
5. reasoning — короткое объяснение (до 120 символов), на русском.
6. follow_up_question — если ты не уверен (<0.7), сформулируй один короткий вопрос пользователю на русском. Иначе null.

НЕ угадывай вслепую. Лучше вернуть confidence=0.5 с хорошим вопросом, чем уверенный неправильный ответ.
НЕ раскрывай плейсхолдеры — ты их видишь уже обезличенными, и это правильно.

Категории пользователя:
{categories_block}

Активные правила с близким описанием:
{rules_block}"""


class ClusterHypothesis(BaseModel):
    """LLM's guess for a single cluster."""

    operation_type: str = Field(description="regular/transfer/refund/investment_buy/investment_sell/credit_disbursement")
    direction: str = Field(description="income or expense")
    predicted_category_id: int | None = Field(
        default=None,
        description="Category ID from the user's list, or null for transfers/investments.",
    )
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="Short Russian explanation, max 120 chars.")
    follow_up_question: str | None = Field(
        default=None,
        description="Short Russian question to the user if LLM is unsure (<0.7).",
    )


@dataclass(frozen=True)
class ModerationContext:
    """Per-user context passed to every cluster call in a session."""

    user_id: int
    categories: list[Category]
    active_rule_snippets: list[str]  # pre-anonymized "<skeleton> → <category_name>"


class ImportModeratorService:
    def __init__(self, db: Session, provider: LLMProvider | None = None) -> None:
        self.db = db
        self._provider = provider or get_provider()

    @property
    def is_enabled(self) -> bool:
        return self._provider.is_enabled

    def moderate_cluster(
        self, cluster: Cluster, context: ModerationContext
    ) -> ClusterHypothesis | None:
        """Ask the LLM to classify this cluster. Returns None if disabled or parse fails.

        The caller (the Celery task) decides whether `None` means "try again
        later" or "fall back to manual review". This service does not retry.
        """
        outcome = self.moderate_cluster_with_usage(cluster, context)
        return outcome[0] if outcome is not None else None

    def moderate_cluster_with_usage(
        self, cluster: Cluster, context: ModerationContext
    ) -> tuple[ClusterHypothesis, LLMResult] | None:
        """Variant of `moderate_cluster` that also returns the raw `LLMResult`
        so the caller can record token usage for metrics (Phase 6.1).
        """
        if not self.is_enabled:
            return None

        system_prompt = self._build_system_prompt(context)
        user_prompt = self._build_user_prompt(cluster)

        try:
            result = self._provider.generate_structured(
                system=system_prompt,
                user=user_prompt,
                schema=ClusterHypothesis,
                max_tokens=512,
                cache_key=f"moderator:v1:{context.user_id}",
            )
        except LLMUnavailableError:
            return None

        if result is None:
            return None

        hypothesis: ClusterHypothesis = result.parsed

        # Defense-in-depth for §12.3: even if the model ignores the prompt
        # and returns "credit_payment", fold it back into a transfer here.
        # The split (interest + principal) is a user decision in the
        # split-form, not something the LLM is trusted to classify.
        if hypothesis.operation_type == "credit_payment":
            logger.warning(
                "Moderator returned forbidden operation_type=credit_payment; coercing to transfer",
            )
            hypothesis = hypothesis.model_copy(
                update={"operation_type": "transfer", "predicted_category_id": None},
            )

        # Defensive: validate the predicted category belongs to this user.
        if hypothesis.predicted_category_id is not None:
            valid_ids = {c.id for c in context.categories}
            if hypothesis.predicted_category_id not in valid_ids:
                logger.info(
                    "Moderator returned unknown category_id=%s", hypothesis.predicted_category_id
                )
                # Treat as "no category" but keep the rest of the hypothesis.
                hypothesis = hypothesis.model_copy(update={"predicted_category_id": None})

        return hypothesis, result

    # ------------------------------------------------------------------
    # Prompt builders — isolated so tests can assert anonymization.
    # ------------------------------------------------------------------

    def _build_system_prompt(self, context: ModerationContext) -> str:
        if context.categories:
            categories_block = "\n".join(
                f"- ID {c.id}: {c.name} ({c.kind})" for c in context.categories
            )
        else:
            categories_block = "(у пользователя нет категорий)"

        if context.active_rule_snippets:
            rules_block = "\n".join(f"- {snippet}" for snippet in context.active_rule_snippets)
        else:
            rules_block = "(нет активных правил с близким описанием)"

        return SYSTEM_PROMPT_TEMPLATE.format(
            categories_block=categories_block,
            rules_block=rules_block,
        )

    def _build_user_prompt(self, cluster: Cluster) -> str:
        """Build the per-cluster user message.

        Only the `skeleton` and aggregate stats go in — NOT the raw row
        descriptions. `skeleton` from Phase 1 has all identifiers already
        replaced with placeholders.
        """
        lines = [
            f"Скелет описания: {cluster.skeleton or '(пусто)'}",
            f"Направление: {cluster.direction}",
            f"Количество строк: {cluster.count}",
            f"Суммарная сумма: {cluster.total_amount} RUB",
        ]
        if cluster.bank_code:
            lines.append(f"Банк: {cluster.bank_code}")
        if cluster.identifier_key:
            # Only the KEY (phone/contract/iban/...) leaks — the VALUE stays
            # inside the backend. This tells the LLM "a contract number is
            # present" without telling it WHICH contract.
            lines.append(f"Обнаружен идентификатор: {cluster.identifier_key}")
        if cluster.is_refund:
            # Refund hint — tells the LLM "this is a reversal of a prior
            # purchase from `<brand>`". The brand is just the merchant token
            # extracted from the skeleton, no PII. If we already resolved a
            # counterparty from purchase history, surface its name too — the
            # LLM can use it to prefer the same category the user uses for
            # that merchant's expenses.
            refund_hint = "Это похоже на возврат средств"
            if cluster.refund_brand:
                refund_hint += f" от продавца «{cluster.refund_brand}»"
            if cluster.refund_resolved_counterparty_name:
                refund_hint += (
                    f" (совпадает с контрагентом «{cluster.refund_resolved_counterparty_name}» "
                    "из истории расходов)"
                )
            refund_hint += (
                ". Верни operation_type=\"refund\" и подбери категорию как для обычной "
                "покупки у этого продавца (expense-kind). Если категория неочевидна — null."
            )
            lines.append(refund_hint)
        return "\n".join(lines)
