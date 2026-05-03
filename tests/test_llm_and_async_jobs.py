"""Группа 9 (T31) и Группа 10 (T32–T33) — LLM service и async jobs.

T31 переформулирован: эндпоинта `POST /imports/rows/{id}/llm-suggest` в
коде нет (см. `app/api/v1/imports.py`). LLM применяется только внутри
enrichment'а (см. `transaction_enrichment_service._resolve_category` с
`skip_llm=False`). Здесь — контракт самой `LLMService`:

  • `is_enabled` отражает provider.is_enabled;
  • `classify_transaction_category` короткозамыкает на None/0.0 если
    is_enabled=False, если categories пуст, если ANTHROPIC возвращает
    низкий confidence или невалидный category_id.

T32 (Celery refund-matcher): refund-matcher в проекте синхронный
(`ImportPostProcessor.apply_refund_matches`), Celery-task для него нет.
Контракт фиксируем явно — отсутствие async-задачи это намеренное
архитектурное решение.

T33 (Celery transfer-matcher async): debounced-task существует
(`schedule_transfer_match` → `match_transfers_for_user_debounced`).
Тест без Redis — проверка чистого контракта функции и сигнатуры task'а.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.models.category import Category
from app.services.llm_service import LLMService


# ---------------------------------------------------------------------------
# T31 — LLMService contract
# ---------------------------------------------------------------------------


@pytest.fixture
def grocery_category(db, user) -> Category:
    cat = Category(
        user_id=user.id, name="Продукты",
        kind="expense", priority="expense_essential",
        regularity="regular", is_system=False,
        icon_name="shopping-basket", color="#16a34a",
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat


def test_llm_classify_returns_none_when_provider_disabled(grocery_category):
    """T31 контракт: provider.is_enabled=False → ранний выход."""
    svc = LLMService()
    fake_provider = MagicMock()
    fake_provider.is_enabled = False
    svc._provider = fake_provider

    cat_id, conf, reason = svc.classify_transaction_category(
        description="x", amount=None,
        transaction_type="expense",
        categories=[grocery_category],
    )
    assert cat_id is None
    assert conf == 0.0
    fake_provider.generate_structured.assert_not_called()


def test_llm_classify_returns_none_when_no_categories_match_kind(grocery_category):
    """Все категории не подходящего типа (income vs expense) → None без LLM-вызова."""
    svc = LLMService()
    fake_provider = MagicMock()
    fake_provider.is_enabled = True
    svc._provider = fake_provider

    cat_id, conf, _ = svc.classify_transaction_category(
        description="зарплата", amount=Decimal("100000"),
        transaction_type="income",  # запрос income, а категория expense
        categories=[grocery_category],
    )
    assert cat_id is None
    assert conf == 0.0
    fake_provider.generate_structured.assert_not_called()


def test_llm_classify_rejects_low_confidence(grocery_category):
    """LLM вернул confidence ниже LLM_MIN_CONFIDENCE → None."""
    svc = LLMService()
    fake_provider = MagicMock()
    fake_provider.is_enabled = True

    fake_result = MagicMock()
    fake_result.parsed = MagicMock(
        category_id=grocery_category.id, confidence=0.1, reasoning="weak",
    )
    fake_provider.generate_structured = MagicMock(return_value=fake_result)
    svc._provider = fake_provider
    svc._min_confidence = 0.6

    cat_id, conf, _ = svc.classify_transaction_category(
        description="random", amount=Decimal("100"),
        transaction_type="expense",
        categories=[grocery_category],
    )
    assert cat_id is None
    assert conf == 0.0


def test_llm_classify_rejects_invalid_category_id(grocery_category):
    """LLM вернул category_id, которого нет в filtered → None."""
    svc = LLMService()
    fake_provider = MagicMock()
    fake_provider.is_enabled = True

    fake_result = MagicMock()
    fake_result.parsed = MagicMock(
        category_id=99999, confidence=0.95, reasoning="hallucinated",
    )
    fake_provider.generate_structured = MagicMock(return_value=fake_result)
    svc._provider = fake_provider
    svc._min_confidence = 0.6

    cat_id, _, _ = svc.classify_transaction_category(
        description="random", amount=Decimal("100"),
        transaction_type="expense",
        categories=[grocery_category],
    )
    assert cat_id is None


def test_llm_classify_returns_provider_result_on_happy_path(grocery_category):
    """Provider enabled + valid category + confidence ≥ min → возврат
    (category_id, confidence, reasoning)."""
    svc = LLMService()
    fake_provider = MagicMock()
    fake_provider.is_enabled = True

    fake_result = MagicMock()
    fake_result.parsed = MagicMock(
        category_id=grocery_category.id, confidence=0.92,
        reasoning="merchant matches grocery list",
    )
    fake_provider.generate_structured = MagicMock(return_value=fake_result)
    svc._provider = fake_provider
    svc._min_confidence = 0.6

    cat_id, conf, reason = svc.classify_transaction_category(
        description="Pyaterochka", amount=Decimal("500"),
        transaction_type="expense",
        categories=[grocery_category],
    )
    assert cat_id == grocery_category.id
    assert conf == 0.92
    assert "LLM" in reason


# ---------------------------------------------------------------------------
# T32 — refund matcher остаётся sync, Celery-задачи нет
# ---------------------------------------------------------------------------


def test_refund_matcher_has_no_celery_task():
    """T32 контракт: refund_matcher_service не регистрирует Celery-task.
    apply_refund_matches вызывается синхронно из ImportPostProcessor."""
    import app.jobs as jobs_pkg
    import pkgutil

    job_modules = [m.name for m in pkgutil.iter_modules(jobs_pkg.__path__)]
    assert not any("refund" in m.lower() for m in job_modules), (
        "Появился job-модуль для refund matcher — обновите тест T32 под "
        "новую async-архитектуру."
    )


# ---------------------------------------------------------------------------
# T33 — transfer matcher debounced
# ---------------------------------------------------------------------------


def test_schedule_transfer_match_publishes_celery_task_with_token():
    """T33: schedule_transfer_match (a) пишет token в Redis, (b) ставит
    Celery-task с countdown. Без подключения к Redis/Celery — мокаем
    клиент и сам task."""
    from app.jobs import transfer_matcher_debounced as tmd

    fake_redis = MagicMock()
    fake_task = MagicMock()
    with patch.object(tmd, "_redis_client", return_value=fake_redis), \
         patch.object(tmd, "_mark_sessions_pending", return_value=None), \
         patch.object(tmd, "match_transfers_for_user_debounced", fake_task):
        tmd.schedule_transfer_match(user_id=42)

    # Token записан в Redis с TTL 30 секунд.
    args, kwargs = fake_redis.set.call_args
    assert args[0] == "tm:debounce:42"
    assert kwargs["ex"] == tmd.TOKEN_TTL_SECONDS

    # Celery-task поставлен с user_id+token и countdown=DEBOUNCE_SECONDS.
    fake_task.apply_async.assert_called_once()
    apply_args = fake_task.apply_async.call_args
    assert apply_args.kwargs["countdown"] == tmd.DEBOUNCE_SECONDS
    task_args = apply_args.kwargs["args"]
    assert task_args[0] == 42
    # token — строка из time.time_ns(); проверяем что non-empty.
    assert isinstance(task_args[1], str) and task_args[1]


def test_match_transfers_debounced_supersedes_when_token_outdated():
    """Если token в Redis НЕ равен нашему — задача выходит как superseded
    и матчер не дёргается."""
    from app.jobs import transfer_matcher_debounced as tmd

    fake_redis = MagicMock()
    fake_redis.get.return_value = b"newer-token"
    with patch.object(tmd, "_redis_client", return_value=fake_redis), \
         patch("app.services.transfer_matcher_service.TransferMatcherService") as fake_matcher:
        result = tmd.match_transfers_for_user_debounced(user_id=42, token="old-token")
        assert result["status"] == "superseded"
        fake_matcher.assert_not_called()


def test_schedule_transfer_match_swallows_redis_failures():
    """Контракт устойчивости: при сбое Redis schedule_transfer_match не
    бросает наружу — иначе любой импорт упадёт целиком."""
    from app.jobs import transfer_matcher_debounced as tmd

    with patch.object(tmd, "_redis_client", side_effect=RuntimeError("redis down")):
        # Не должно бросать
        tmd.schedule_transfer_match(user_id=42)
