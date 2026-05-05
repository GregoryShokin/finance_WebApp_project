# Фича — Atomic destructive replace для duplicate UX
#бэклог #пост-mvp #импорт
> Опциональный «Перезаписать» в DuplicateModal должен атомарно удалить старую сессию и создать новую, а не плодить параллель.
---
## Контекст (2026-05-04)
В Этапе 0.5 кнопка «Загрузить как новую» в `DuplicateModal` шлёт `force_new=true` → backend создаёт **параллельную** сессию рядом со старой. Старая не удаляется — это намеренно (non-destructive), чтобы юзер мог сравнить и выбрать.

Но в части кейсов поведение не идеально:
- Юзер действительно хотел «переписать» (банк перевыпустил выписку с исправленными данными) — и теперь видит две сессии в queue, обе с одинаковым названием файла, должен сам разобраться какую удалить.
- При ошибочной загрузке («не тот файл, второй раз кидаю правильный») — старая остаётся, queue замусоривается.

UX-решение в DuplicateModal требует разделения: «Перезаписать» (destructive: удалить старую, создать новую) vs «Загрузить как новую» (parallel). Backend сейчас умеет только parallel.

## Планируемое
### Backend
- Новый endpoint `PUT /imports/{existing_session_id}/replace` — атомарно в одной транзакции:
  1. `DELETE` cascade из `import_sessions` по `existing_session_id` (rows, fingerprint_aliases, etc — уже cascade на FK).
  2. `CREATE` новой сессии с теми же `raw_bytes`, без duplicate-check.
  3. `COMMIT`.
- Reject если `existing.status == "committed"` (нельзя перетереть закоммиченную — это уже Transactions).
- Idempotency: если client пере-шлёт PUT после успеха, должно вернуть последнюю созданную сессию (через `Idempotency-Key` header — Этап 3.3).

### Frontend
- `DuplicateModal`: разделить кнопки:
  - **«Открыть существующую»** — без backend-вызова, просто переход.
  - **«Перезаписать»** (destructive, красная) — `PUT /imports/{id}/replace` с raw_bytes. Confirmation step «Точно удалить 47 действий и 12 закоммиченных строк?» с показом existing_progress.
  - **«Загрузить как новую»** (current force_new=true behavior) — параллельная сессия.
  - **«Отмена»**.

### Migration concerns
- Cascade delete на ImportSession уже работает (FK `ON DELETE CASCADE` от import_rows).
- Atomic — всё в одной DB-транзакции, Celery jobs (auto_preview) на удалённую сессию должны fail-soft (`get_session()` returns None → exit task).

## Edge cases
- **Race**: tab1 жмёт «Перезаписать», tab2 жмёт «Открыть существующую» — tab2 видит 404 на open. Допустимо.
- **Auto-preview уже стартовал на старой**: Celery task завершится с warning «session disappeared» — добавить guard в `auto_preview_import_session`.
- **Bulk-apply rules уже привязаны к старой**: cascade удалит. Это потеря работы, но юзер явно попросил destructive — confirmation step предупреждает.

## Тесты
- `tests/test_imports_replace.py`:
  - Happy path: replace создаёт новую сессию, старая удалена, rows исчезли.
  - Reject committed: PUT на committed-сессию → 400.
  - Cascade: rules/aliases на старой удаляются.
  - Idempotency-Key: повторный PUT возвращает существующую новую без re-create.

## Оценка
1 день (backend endpoint + frontend modal + tests + Idempotency-Key wiring если ещё нет).

## Критичность
**MEDIUM (пост-MVP)** — current 0.5 поведение (parallel, non-destructive) не блокирующее, юзер вручную может удалить старую через queue. Опасность destructive-операций в проекте про деньги — вес добавления выше, чем UX-выгода в MVP. Возвращаемся когда:
- сообщения в support'е жалуются на «у меня дубликаты в queue»;
- тест-юзеры не находят кнопку «удалить сессию» в queue UI.

## Ссылки
- §23.4 «Escape hatch: force_new=true» в `Спецификация — Пайплайн импорта.md` — фиксирует текущее non-destructive поведение.
- Этап 3.3 [[Фича — Idempotency token на commit]] — Idempotency-Key infrastructure.
- Memory `architecture_decisions.md` блок «Duplicate-statement UX» — invariant «force_new НЕ destructive».
