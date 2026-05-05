# Фича — Race-safe duplicate detection
#бэклог #пост-mvp #импорт #db
> Partial UNIQUE INDEX на `(user_id, file_hash) WHERE status != 'committed'` для атомарной защиты от race-условий при параллельной загрузке.
---
## Контекст (2026-05-04)
В Этапе 0.5 duplicate-detection реализован как app-level check (`find_by_file_hash` → если не пусто, вернуть existing). Между `find_by_file_hash()` и `INSERT` есть гэп в миллисекунды, в течение которых второй request может пройти тот же check и тоже создать новую сессию.

Текущая защита: **logger.warning** при `len(active_dups) > 1`:
```python
if len(active_dups) > 1:
    logger.warning("multiple uncommitted sessions for one file_hash — possible race", ...)
```

Окно — миллисекунды (2 tab'а с одной выпиской, оба жмут «Загрузить» одновременно). Ущерб — две uncommitted сессии в queue вместо одной. Юзер видит обе, может удалить лишнюю руками. Не критично, но след в логах.

## Планируемое
### Миграция
```python
# alembic revision --autogenerate -m "partial_unique_file_hash" --rev-id 00XX
op.create_index(
    "uq_import_sessions_user_file_hash_active",
    "import_sessions",
    ["user_id", "file_hash"],
    unique=True,
    postgresql_where=sa.text("status != 'committed'"),
)
```

`postgresql_where` — partial-index syntax. Не работает на SQLite — но nature of duplicate-defense это OK (тесты на SQLite не покрывают concurrent-INSERT race).

### Backend
- `ImportRepository.create_session` — wrap в `try/except IntegrityError` → re-fetch existing и вернуть как duplicate (CHOOSE).
- Helper `_handle_concurrent_duplicate` отделяет race-recovery от обычной ветки `find_by_file_hash`.
- DEBUG-лог при срабатывании (полезно для аналитики «как часто это происходит»).

### Тесты
- Postgres-only тест (skip on SQLite): два threading concurrent INSERT с одним file_hash → один успешен, второй ловит IntegrityError и видит CHOOSE-response.
- Не-tagged тест на committed-сессии: создание новой сессии с тем же hash после commit'а — успешно (partial WHERE исключает committed).

## Edge cases
- **Migration на проде**: до запуска миграции должна быть очистка дубликатов (если были). Скрипт `scripts/dedupe_active_sessions.py` — для каждого `(user, file_hash)` оставить newest, остальные удалить (с предварительным отчётом).
- **Cascade delete-and-create**: pour `force_new=true` поток (Этап 0.5 §23.4) — partial UNIQUE НЕ препятствует, потому что мы создаём НОВУЮ запись с тем же hash, но обе active одновременно. Подождите — это нарушение constraint! Нужно решить:
  - **Вариант A**: `force_new=true` пропускает constraint через `ON CONFLICT DO NOTHING + RETURNING` подход — но это семантически странно (намеренный дубль помечен как single-row constraint).
  - **Вариант B**: убрать non-destructive `force_new` (использовать destructive replace из [[Фича — Atomic destructive replace для duplicate UX]]) — тогда constraint не мешает.
  - **Вариант C**: оставить `force_new` создающим параллель, но без partial UNIQUE — тогда защита только от race, не от намеренного дубля.

Решение: **Вариант C** — partial UNIQUE опускаем при `force_new=true` через `ON CONFLICT DO NOTHING` (или просто snapshot session.file_hash на разное значение типа `f"{file_hash}-force-{uuid}"`). Это compromise: race защищён, intentional parallel разрешён.

## Оценка
0.5-1 день (миграция + 2 теста + dedupe-скрипт + edge-case decision).

## Критичность
**LOW (пост-MVP)** — race-окно миллисекунды, ущерб минимальный, текущий logger.warning достаточен для диагностики. Возвращаемся когда:
- логи показывают, что race происходит регулярно (>1 раз в неделю);
- сообщения в support'е про «у меня две одинаковые сессии после двойного клика».

## Ссылки
- §23.5 «Race-condition signal» в `Спецификация — Пайплайн импорта.md`
- `app/services/import_service.py:upload_file` — место, где сейчас живёт логика (строки 167-202)
- Memory `architecture_decisions.md` блок «Duplicate-statement UX» — фиксирует «race signal только в логах» как принятое compromise решение
