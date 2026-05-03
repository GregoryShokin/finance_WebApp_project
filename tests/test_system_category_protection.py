"""T8 — Системная категория «Проценты по кредитам».

Проверяет три инварианта:
1. Категория автоматически создаётся для нового пользователя через
   `CategoryService.ensure_default_categories` (которая делегирует в
   `ensure_system_categories`).
2. Попытка обновить системную категорию через сервис → CategoryValidationError.
3. Попытка удалить системную категорию через сервис → CategoryValidationError.

Контракт API (categories.py): сервисная ошибка превращается в HTTP 400. Тест
бьёт по сервисному слою — это даёт ту же гарантию без поднятия FastAPI/JWT.
"""
from __future__ import annotations

import pytest

from app.services.category_defaults import SYSTEM_CATEGORIES
from app.services.category_service import (
    CategoryService,
    CategoryValidationError,
)


def _system_category_definition():
    assert len(SYSTEM_CATEGORIES) == 1, (
        "T8 предполагает ровно одну системную категорию — «Проценты по кредитам». "
        "Если SYSTEM_CATEGORIES расширили, тест нужно обобщить."
    )
    item = SYSTEM_CATEGORIES[0]
    assert item.name == "Проценты по кредитам"
    assert item.is_system is True
    return item


def test_ensure_default_categories_creates_system_interest_category(db, user):
    service = CategoryService(db)
    _system_category_definition()

    service.ensure_default_categories(user_id=user.id)

    all_categories = service.list_categories(user_id=user.id)
    interest = next(
        (c for c in all_categories if c.name == "Проценты по кредитам"),
        None,
    )
    assert interest is not None, (
        "ensure_default_categories должна создать «Проценты по кредитам» "
        "через делегирование в ensure_system_categories"
    )
    assert interest.is_system is True
    assert interest.kind == "expense"
    assert interest.priority == "expense_essential"


def test_ensure_default_categories_is_idempotent(db, user):
    service = CategoryService(db)

    service.ensure_default_categories(user_id=user.id)
    second_run = service.ensure_default_categories(user_id=user.id)

    assert all(c.name != "Проценты по кредитам" for c in second_run), (
        "Повторный вызов не должен создавать дубликат системной категории"
    )

    all_categories = service.list_categories(user_id=user.id)
    interests = [c for c in all_categories if c.name == "Проценты по кредитам"]
    assert len(interests) == 1, "В БД должна остаться ровно одна системная категория"
    assert interests[0].is_system is True


def test_update_system_category_is_rejected(db, user):
    service = CategoryService(db)
    service.ensure_default_categories(user_id=user.id)

    interest = next(
        c for c in service.list_categories(user_id=user.id)
        if c.name == "Проценты по кредитам"
    )

    with pytest.raises(CategoryValidationError) as exc:
        service.update_category(
            user_id=user.id,
            category_id=interest.id,
            updates={"name": "Мои проценты"},
        )
    assert "Системную категорию" in str(exc.value)

    refreshed = next(
        c for c in service.list_categories(user_id=user.id)
        if c.id == interest.id
    )
    assert refreshed.name == "Проценты по кредитам", "Имя не должно было измениться"


def test_delete_system_category_is_rejected(db, user):
    service = CategoryService(db)
    service.ensure_default_categories(user_id=user.id)

    interest = next(
        c for c in service.list_categories(user_id=user.id)
        if c.name == "Проценты по кредитам"
    )

    with pytest.raises(CategoryValidationError) as exc:
        service.delete_category(user_id=user.id, category_id=interest.id)
    assert "Системную категорию" in str(exc.value)

    still_present = next(
        (c for c in service.list_categories(user_id=user.id) if c.id == interest.id),
        None,
    )
    assert still_present is not None, "Системная категория должна остаться в БД"
    assert still_present.is_system is True
