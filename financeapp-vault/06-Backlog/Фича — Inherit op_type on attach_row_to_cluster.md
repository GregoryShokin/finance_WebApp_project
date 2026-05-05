# Фича — Inherit op_type on attach_row_to_cluster
#бэклог #импорт #пост-mvp #низкий-приоритет

> При attach row к существующему cluster'у `op_type` ставится жёстко `regular`, не наследуется из rows кластера. Если cluster имеет 30 подтверждений как `debt` — attach'нутый row не получит этот сигнал.

---

## Контекст

Обнаружено при review Этапа 2 (2026-05-04).

В `app/services/import_service.py:634` (метод `attach_row_to_cluster`):

```python
if rule is not None and rule.category_id is not None:
    target_category_id = int(rule.category_id)
    target_operation_type = "regular"  # ← всегда regular
```

Это создаёт несимметрию с `bulk_apply_orchestrator`, который в Этапе 2 учитывает op_type по mode rows кластера.

## Проблема

Юзер attach'ит row к cluster'у «Иван — debt» (30 предыдущих rows подтверждены debt). Текущее поведение: row получает `op_type='regular'`, не наследует debt. При следующем preview/commit правило (Иван, debt, confirms=30) активно, но к этому конкретному attach'нутому row не применяется (если row уже зафиксирован с regular).

## Решение

В `attach_row_to_cluster` резолвить op_type как **mode** rows целевого cluster'а:

```python
op_type_counter = Counter(
    str(r.normalized_data.get("operation_type") or "regular").lower()
    for r in cluster_rows
)
target_operation_type, _count = op_type_counter.most_common(1)[0]
```

Или (более консервативно): использовать `get_best_rule(want_op_type=True)` для cluster'а и взять op_type оттуда, если правило активно с op_type.

## Тесты

```python
def test_attach_inherits_debt_op_type_from_cluster():
    # Cluster с 30 debt-rows + active rule (debt, confirms>threshold)
    # attach новый row → row получает op_type='debt'
```

## Скоуп

- `app/services/import_service.py:attach_row_to_cluster` — резолюция op_type.
- 1-2 теста.

## Эстимейт

0.5 дня.

## Приоритет

**Низкий** — пост-MVP. attach редко используется (моderator UI), сценарий с debt-cluster не основной use-case.

## Связанные документы

- [[Спецификация — Пайплайн импорта]] §22.7 (known risk #3).
- Этап 2 review (2026-05-04).
