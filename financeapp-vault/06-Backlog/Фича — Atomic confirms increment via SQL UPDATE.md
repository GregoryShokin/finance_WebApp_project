# Фича — Atomic confirms increment via SQL UPDATE
#бэклог #импорт #техдолг #средний-приоритет

> `RuleStrengthService.on_confirmed` использует Python-side инкремент `rule.confirms = (rule.confirms or 0) + delta`. Race-prone при параллельных commit'ах.

---

## Контекст

Existing risk, обнаружен при review Этапа 2 (2026-05-04). Не введён Этапом 2 — был и до него.

В `app/services/rule_strength_service.py:108`:

```python
rule.confirms = (rule.confirms or Decimal("0")) + delta
```

И аналогично rejections (line 154). Это **read-modify-write** на Python-уровне без atomic SQL UPDATE — два параллельных worker'а могут оба прочитать `confirms=5`, оба добавить +1, оба записать `confirms=6` (потеря одного инкремента).

`bulk_upsert` (Этап 2) защищён через `INSERT ... ON CONFLICT DO NOTHING` для **создания** правила, но `on_confirmed` после этого делает Python-side инкремент → race возвращается.

## Вероятность в проде

- Single-tenant MVP: <0.1%. Юзер обычно делает один commit за раз.
- Multi-worker Celery: возможно при параллельной commit-обработке нескольких rows одного fingerprint.
- Bulk-apply: 50 rows в одном orchestrator-вызове → один thread, race не возникает.

## Решение

```python
# В RuleStrengthService.on_confirmed:
self.session.execute(
    update(TransactionCategoryRule)
    .where(TransactionCategoryRule.id == rule_id)
    .values(
        confirms=TransactionCategoryRule.confirms + delta,
        updated_at=func.now(),
    )
)
# is_active transition остаётся в Python (нужен read AFTER update — RETURNING)
```

Можно через `.returning(TransactionCategoryRule)` чтобы получить обновлённую row для `is_active` логики. Или RETURNING confirms only + Python-side decision.

## Скоуп

- Только `on_confirmed` и `on_rejected` в `rule_strength_service.py`.
- Тесты на race через threading или pytest-asyncio с двумя параллельными commit'ами.

## Эстимейт

0.5-1 день.

## Когда возвращаться

- Перед публичным запуском (Этап 0.7 Launch Gate).
- Или при первой жалобе на «правило слишком быстро/медленно растёт» в проде.

## Связанные документы

- [[Спецификация — Пайплайн импорта]] §22.7 (known risk #2).
- Этап 2 review (2026-05-04).
