# Фича — Worker timeout и зависшие сессии
#бэклог #критический-приоритет #импорт
> Если воркер падает или задача висит, сессия импорта должна явно становиться `failed` с понятным юзеру сообщением и кнопкой «повторить».
---
## Проблема (2026-05-03)
Сейчас в `app/jobs/auto_preview_import_session.py` и `app/jobs/transfer_matcher_debounced.py` нет timeout-логики.

Сценарий:
1. Юзер загрузил выписку → `auto_preview_import_session` запустилась.
2. Воркер упал (OOM, deploy, network issue) → задача потерялась.
3. `ImportSession.summary_json["auto_preview"].status = "running"` остаётся навсегда.
4. Юзер видит спиннер, ничего не происходит, опции «повторить» нет.

То же самое для `transfer_match` (debounced job).

## Планируемое
### Backend
- Watchdog-задача (Celery beat, каждые 2-3 мин): сканирует `ImportSession.summary_json["auto_preview"]` и `transfer_match`, помечает `status = "failed"` с `error = "обработка зависла"`, если `started_at` старше 10 минут и `finished_at` отсутствует.
- Soft timeout на сами задачи (`soft_time_limit=600` в Celery config) → задача сама пишет `status = "failed"` при таймауте.
- API эндпоинт `POST /imports/{session_id}/retry-preview` — снимает failed-статус и запускает auto_preview заново.

### Frontend
- `import-status-card.tsx`: при `status = "failed"` показать алерт с error_message + кнопку «Повторить».
- При `status = "running"` дольше 30 секунд — индикация «обработка занимает дольше обычного» (с polling).

## Критичность
**Критический приоритет** — без этого первый же crash воркера в проде оставит юзеров с вечно крутящимися спиннерами.

## Ссылки
- [[Подготовка к запуску MVP]] — Этап 0.4
