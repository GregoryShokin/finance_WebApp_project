# Подготовка к запуску MVP
#подготовка-к-запуску #mvp #план

> Сводный план работ перед публичным запуском. Этапы пронумерованы и помечены статусом — обновлять по мере прохождения. Каждая задача имеет референс на отдельную backlog-карточку, где живёт детальное описание.

**Дата создания:** 2026-05-03
**Текущая фаза:** До закрытого тестирования. Этапы 0 + 1 + 2 в активной работе. Этап 0: 0.1+0.2+0.3+0.5 готовы по коду + тестам (🟨, ждут manual smoke в браузере); 0.4 + 0.6 не начаты. Этап 1: 5/7 шагов закрыты, 1.6 UNBLOCKED после 0.5, 1.7 ждёт образцов. Этап 2: 🟩 закрыт.

---

## Легенда статусов

- 🟥 **NOT_STARTED** — задача не начата
- 🟧 **IN_DESIGN** — в проработке (UX/архитектура), код не пишется
- 🟨 **IN_PROGRESS** — в активной разработке
- 🟩 **DONE** — реализовано и проверено
- ⬜ **DEFERRED** — отложено на пост-MVP (с пометкой когда вернуться)

> ⚠️ **Как обновлять:** меняй статус-эмодзи в шапке каждой задачи. Если этап целиком завершён — поставь 🟩 в шапке самого этапа.

---

## ЭТАП 0 — Critical Import & Stability 🟨
**Цель:** импорт перестаёт «терять» работу пользователя и не падает на криво загруженном файле.
**Срок:** ~1 неделя
**Блокирует:** закрытое тестирование. Без этого этапа юзеров звать нельзя.
**Прогресс:** 0.1 готов по коду (🟨, ждёт прогона+smoke), 0.2 готов по коду (🟨, ждёт прогона+smoke), 0.3 — дизайн-план готов (🟧), 0.4/0.5/0.6 не начаты.

### 0.1 — Refresh Token 🟨
- Файл: [[Фича — Refresh Token]]
- Backend: `/auth/refresh`, `/auth/logout`, таблица `refresh_tokens` (миграция 0059), rotation + reuse-detection, `with_for_update()` против race
- Frontend: interceptor на 401 в `lib/api/client.ts` с singleton refreshPromise, `RETURN_TO_KEY` в sessionStorage
- Параметры: access 15 мин, refresh 30 дней; multi-device; SameSite=Strict для refresh
- Cleanup: Celery beat `prune_refresh_tokens` ежедневно 04:30 UTC
- Тесты: `tests/test_auth_refresh.py` (написан, требует прогона в docker compose)
- Осталось до 🟩: прогон тестов + smoke-чеклист в браузере (12 сценариев из ревью)
- Оценка: 1.5 дня

### 0.2 — Лимит размера файла + content-type whitelist 🟨
- Файл: [[Фича — Лимиты загрузки и rate-limit]]
- Backend: `app/services/upload_validator.py` (streaming 64 KB chunks, magic-byte detection, CSV negative-check для cp1251, XLSX zip-bomb защита через central directory) + `MaxBodySizeMiddleware` (header-only Content-Length, 30 MB глобальный cap, 413). Helper `app/api/v1/_upload_helpers.py` (idempotent close, переиспользуем в Celery/CLI). Интегрирован в `/imports/upload` и `/telegram/bot/upload`.
- 7 структурных кодов ошибок (`upload_too_large`, `extension_content_mismatch`, `xlsx_decompression_too_large`, `empty_file`, `unsupported_upload_type`, `xlsx_missing_manifest`/`xlsx_invalid_archive`) через `to_payload()` — фронт читает поля payload, не regex по тексту.
- Frontend: `frontend/lib/upload/limits.ts` (pre-upload check + early-return на пустой файл), `import-page.tsx:formatUploadError` (mapper всех 7 кодов с fallback), `import-actions-bar.tsx` accept `.csv,.xlsx,.pdf` + MIME (Safari/Chrome паритет).
- Лимиты: CSV/XLSX 10 MB, PDF 25 MB, XLSX uncompressed cap 100 MB, global 30 MB. Все env-переопределяемы (`MAX_UPLOAD_SIZE_*_MB`, `NEXT_PUBLIC_MAX_UPLOAD_*_MB` — sync обязателен; Next.js inline'ит `NEXT_PUBLIC_*` на build).
- Тесты: `tests/test_upload_validator.py` (23), `tests/test_max_body_size_middleware.py` (9), `tests/test_imports_upload_validation.py` (17) = 49 тестов; ждут прогона в docker.
- Follow-ups (вынесены в backlog): [[Фича — Bot-side upload validation]], [[Фича — Memory-efficient upload pipeline]], [[Фича — Frontend test infra]], [[Фича — Frontend error-codes typings]].
- Осталось до 🟩: прогон 49/49 тестов + manual smoke (10 сценариев из ревью, особенно zip-bomb через DevTools-перехват FormData).
- Оценка: 0.5 дня

### 0.3 — Rate-limit на upload и auth 🟨
- Файл: [[Фича — Лимиты загрузки и rate-limit]]
- Backend: `slowapi==0.1.9` + Redis backend (общий с Celery/refresh-debounce). `app/core/rate_limit.py` (Limiter + custom 429 handler), `app/core/keys.py` (`ip_key`, `user_or_ip_key` с JWT decode), `app/core/client_ip.py` (XFF + TRUSTED_PROXIES — закрывает TODO 0.2 по ip-resolver). `SlowAPIMiddleware` зарегистрирован для X-RateLimit-* headers + `default_limits=[]`.
- Декораторы: `/auth/login` 5/15мин per-IP, `/auth/register` 3/час per-IP, `/auth/refresh` 30/5мин per-IP, `/imports/upload` 30/час **per-user** (`user_or_ip_key`), `/telegram/bot/upload` 30/час per-IP (per-telegram_id отложено в [[Фича — Bot rate-limit per-telegram_id]] — двойной парсинг multipart).
- Custom 429 handler: structured payload `{detail, code='rate_limit_exceeded', endpoint, retry_after_seconds}` + `Retry-After` header. `retry_after = max(int(...), 1)` против 429-loop.
- Frontend: `frontend/lib/api/rate-limit-error.ts` (общий `formatRateLimitErrorAuth` минуты + N=1 особый случай / `formatRateLimitErrorUpload` секунды<60→минуты + `isRateLimitError` guard). Интегрировано в `login-form.tsx`, `register-form.tsx`, `import-page.tsx:formatUploadError`.
- Конфиг: 5 `RATE_LIMIT_*` строк + `RATE_LIMIT_ENABLED` toggle + `TRUSTED_PROXIES` (env-overridable). `.env.example` обновлён.
- Архитектурные решения зафиксированы в memory `architecture_decisions.md` блок «Rate limits»: decorator-only mode (slowapi `_should_exempt` пропускает декорированные роуты в middleware), 401 побеждает 429 (pinned тестом), fail-open при Redis-down (`swallow_errors=True`), TRUSTED_PROXIES обязателен в проде за reverse-proxy.
- Тесты: `tests/test_client_ip.py` (7) + `tests/test_rate_limit_auth.py` (6) + `tests/test_rate_limit_uploads.py` (4) = **17 тестов**; `MemoryStorage` swap в file-local fixture для unit-isolation от Redis.
- Follow-ups: [[Фича — Bot rate-limit per-telegram_id]], [[Фича — nginx rate-limit как outer layer]], [[Фича — Pre-auth IP rate-limit на upload]].
- README раздел «Rate limits» добавлен (таблица 5 эндпоинтов + конфигурация + TRUSTED_PROXIES warning + payload контракт + known limitations).
- Осталось до 🟩: прогон 17/17 тестов в docker + manual smoke (3 сценария: login/register/upload spam) — либо покрытие через E2E pre-deployment hardening backlog.
- Оценка: 2 дня (фактически потрачено ~эта оценка)

### 0.4 — Worker timeout и зависшие сессии 🟥
- Файл: [[Фича — Worker timeout и зависшие сессии]]
- Watchdog-задача, soft_time_limit на job'ах, retry-эндпоинт
- UI: алерт при failed + кнопка «Повторить»
- Оценка: 1 день

### 0.5 — Дубликат-выписка UX 🟨
- Файл: [[Фича — Дубликат-выписка UX]]
- Backend: `ImportService.upload_file` two-stage detection (`active` побеждает `committed`), `find_by_file_hash(include_committed=True)`, response с `action_required` + `existing_progress` + `existing_status` + `existing_created_at` (все 4 ключа во ВСЕХ ответах upload, инвариант контракта). `force_new=true` (form-параметр) — non-destructive escape hatch.
- Frontend: `DuplicateModal` для CHOOSE (3 кнопки) + soft-banner для WARN (committed). Интеграция в `import-page.tsx`. Bot route возвращает `bot_message` (server-formatted Russian text), но bot пока не отображает — backlog [[Фича — Bot reads structured error messages]].
- Race-condition: `if len(active_dups) > 1: logger.warning(...)` — окно миллисекунды, partial UNIQUE INDEX отложен в [[Фича — Race-safe duplicate detection]].
- Conservative `user_actions` filter: `status NOT IN ('ready', 'error')` (false-positive для warning/duplicate/skipped) — намеренный safer-UX trade-off, закреплён тестом.
- Тесты: `tests/test_imports_duplicate_upload.py` — **9/9 PASSED** (реальный extractor + SQLite, не mock).
- Документация: §23 «Duplicate detection» в `Спецификация — Пайплайн импорта.md`, memory `architecture_decisions.md` блок «Duplicate-statement UX».
- Follow-ups (новые backlog cards): [[Фича — Bot reads structured error messages]] (HIGH), [[Фича — Atomic destructive replace для duplicate UX]] (MEDIUM пост-MVP), [[Фича — Race-safe duplicate detection]] (LOW миграция).
- Осталось до 🟩: manual smoke в браузере (5 сценариев: первая загрузка → повторная (CHOOSE) → «Открыть существующую» → «Загрузить как новую» (две сессии в queue) → committ + повторная (WARN)).
- Оценка: 1 день (по факту ~1 день включая фикс production-бага в fresh-upload response shape)

### 0.6 — Бэкапы базы данных 🟥
- Файл: [[Фича — Бэкапы базы данных]]
- pg_dump cron, ротация 7+4+3, restore-doc, проверочный restore раз в квартал
- Оценка: 0.5 дня

**Сумма Этапа 0:** ~5 рабочих дней

---

## ЭТАП 0.7 — Pre-deployment Hardening 🟥
**Цель:** превратить feature-готовый код в production-ready release. Закрывает дыру «как выпускать», которую план до этого не адресовал.
**Срок:** ~3.5 дня
**Блокирует:** закрытое тестирование. Без этого invite'нуть тест-юзеров нельзя.
**Контекст:** добавлен 2026-05-04 после ревью плана GPT-5.5 (см. историю изменений).

### 0.7.1 — Alembic merge resolution 🟩
- Закрыто 2026-05-04. Migration `0063_merge_refresh_tokens_and_op_type.py` (`down_revision = ("0059", "0062")`) — pure join без schema changes.
- Convention preserved: переименован hash auto-gen revision (`b71eef23124e`) на numeric `0063` под общую схему проекта.
- Cycle test: `alembic upgrade head` → `downgrade 0058` → `upgrade head` проходит чисто на dev-БД. `alembic heads` теперь возвращает single `0063`.
- Известное Alembic-поведение зафиксировано в docstring: `alembic downgrade -1` от merge-revision даёт `Ambiguous walk` (две parent chains, нет однозначного выбора). Корректный downgrade — explicit target (`alembic downgrade 0059` / `0062` / `0058`).
- Smoke-test: 83 теста по rule + bank + import_normalization + bulk_apply прошли без регрессии после merge.
- Оценка: 0.25 дня (по факту 30 минут)

### 0.7.2 — Staging environment 🟥
- Сейчас: только dev (docker compose локально) и (будущий) prod. Между ними должен быть staging.
- `docker-compose.staging.yml` с отдельным volume / БД / env-файлом.
- Restore-from-prod-snapshot процедура (заготовка для будущего, когда prod появится).
- Smoke-checklist на staging-домене (отдельно от dev manual smoke), с реальным nginx если возможно.
- Опционально: auto-deploy через git push на staging branch.
- Оценка: 1 день

### 0.7.3 — Observability minimum 🟥
- Sentry (бесплатный tier) подключён к API + Celery worker + bot. DSN через env.
- `structlog` или `python-json-logger` для structured logs (JSON output).
- Logger calls на 5 ключевых операциях: `upload_started/completed/failed`, `commit_succeeded/failed`, `auth_login`, `auth_refresh_failed`, `transfer_match_completed`.
- Без этого первая жалоба тест-юзера будет «у меня не работает» без возможности диагностировать.
- Prometheus `/metrics` + Grafana — пост-MVP (overkill для 10-50 юзеров).
- Оценка: 0.5 дня

### 0.7.4 — MVP Launch Gate checklist 🟥
- Документ в финале плана MVP с 12-15 критериями готовности.
- Минимум: все этапы 0+1 на 🟩, alembic heads = 1, полный pytest зелёный, staging-БД развёрнута и прошла smoke, Sentry baseline снят за 24h, backup автоматизирован + restore проверен на staging, HTTPS активен, 4 банка поддержаны (Сбер/Тинькофф/Озон/Яндекс), happy path E2E подтверждён.
- Это release-control документ, не backlog.
- Оценка: 0.25 дня

### 0.7.5 — Playwright E2E smoke 🟥
- 2 сценария:
  - Happy path: register → create account → upload PDF → preview → commit → check dashboard
  - Sad path: upload 30 MB PDF → expect 413 toast (без сетевого запроса при pre-validation)
- Tooling: Playwright (или Cypress) + headless browser в CI.
- Для закрытого тестирования желательно, для публичного — обязательно.
- Оценка: 1 день

### 0.7.6 — Security pre-flight 🟥
- Чеклист single-source-of-truth (распылённая security сейчас по этапам 0.1/0.2/0.3/0.6).
- Включает:
  - Secrets rotation playbook (`SECRET_KEY`, `TELEGRAM_BOT_TOKEN`, БД-пароль).
  - `.env.production.example` placeholder без реальных credentials.
  - CORS/`TRUSTED_HOSTS` prod values (сейчас дефолты для localhost).
  - HTTPS через Let's Encrypt или Cloudflare; `ENABLE_HTTPS_REDIRECT=true` в проде.
  - `TRUSTED_PROXIES` активирован при деплое за nginx/Cloudflare.
  - Backup encryption: pg_dump в plain — out of MVP scope (volume локальный, не cloud); зафиксировано в карточке Бэкапов как пост-MVP.
  - Audit через `grep -r "secret\|password\|token" --exclude-dir=.git` на hardcoded secrets.
  - Data deletion endpoint (`DELETE /users/me` каскадно) — зафиксировано как блокер публичного запуска (152-ФЗ), не закрытого тестирования.
- Оценка: 0.5 дня

**Сумма Этапа 0.7:** ~3.5 рабочих дня

---

## ЭТАП 1 — Whitelist банков 🟨
**Цель:** пользователь не получает мусор от непротестированного банка на первой выписке.
**Срок:** ~4-5 дней
**Блокирует:** закрытое тестирование (вместе с Этапом 0).

### 1.1 — Колонки extractor_status на banks 🟩
- Файл: [[Фича — Whitelist банков для импорта]]
- Решение 2026-05-03: колонки `extractor_status` / `extractor_last_tested_at` / `extractor_notes` прямо на `banks` (не отдельная таблица). CHECK constraint на статусе (`supported`/`in_review`/`pending`/`broken`).
- Миграция 0060 + idempotent baseline в `app/services/bank_service.py` (startup-event), защита ручных статусов
- Оценка: 0.5 дня

### 1.2 — API GET /banks?supported_only=true 🟩
- Файл: [[Фича — Whitelist банков для импорта]]
- Поле `extractor_status` в `BankResponse`
- Оценка: 0.5 дня

### 1.3 — UI BankPicker фильтр 🟩
- Файл: [[Фича — Whitelist банков для импорта]]
- Две секции «Импорт поддерживается» / «Импорт пока не поддерживается»; бейджи «Скоро» / «Временно не работает»; disclaimer + CTA «Запросить поддержку» в account-form
- Оценка: 0.5 дня

### 1.4 — API POST /bank-support/request 🟩
- Файл: [[Фича — Whitelist банков для импорта]]
- Решение 2026-05-03: **JSON-only payload** (`bank_id?`, `bank_name`, `note?`). Sample-файлы deferred (PII / encryption / cleanup — пост-MVP).
- Изолированный роутер `app/api/v1/bank_support.py` (не `imports.py`) — снимает merge-конфликт с Этапом 0.
- Idempotent: повторный запрос на тот же банк с открытым статусом возвращает существующий.
- Миграция 0061 (`bank_support_requests`).
- Оценка: 1 день

### 1.5 — UI «Запросить поддержку банка» 🟩
- Файл: [[Фича — Whitelist банков для импорта]]
- `BankSupportRequestModal` — форма, без file-upload. Подключена в EmptyState `/import` (для юзеров без supported-счетов) и в account-form под disclaimer'ом.
- Оценка: 0.5 дня

### 1.6 — Жёсткий guard на upload 🟨
- Файл: [[Фича — Whitelist банков для импорта]]
- Backend: `BankUnsupportedError` exception в `ImportService` + check после resolve `suggested_account_id` (по `contract_number` / `statement_account_number`). Route handlers (`/imports/upload` + `/telegram/bot/upload`) ловят и возвращают **HTTP 415** со структурой `{code: 'bank_unsupported', bank_id, bank_name, extractor_status, detail}`. Bot-вариант добавляет `bot_message` для chat-reply.
- **Порядок check'ов в upload_file**: file_hash dedup (0.5) → extract → resolve `suggested_account_id` → bank guard (1.6) → создать сессию. Dedup идёт первым (cheap, sha256 + 1 query); bank guard после extract'а потому, что банк определяется через extraction.meta. Сессии для unsupported-банков **никогда не создаются** — порядок dedup vs guard инвариантен семантически.
- **Когда guard НЕ срабатывает**: brand-new юзер без счетов; extraction не дала contract/account match. PATCH `/imports/{id}/account` (assign account post-upload) НЕ дублирует guard — out of MVP scope, полагаемся на frontend disclaimer и BankPicker.
- Frontend (`import-page.tsx`):
  - `uploadMut.onError` ловит `code='bank_unsupported'` → открывает `BankSupportRequestModal` с pre-filled `bank_id` + `bank_name` (без generic toast'а).
  - Pre-upload disclaimer: `<UnsupportedBankBanner>` рендерится над import-area, если у юзера есть accounts на unsupported-банках (даже когда есть и supported). Каждая unsupported-банк строка → CTA «Запросить поддержку «Bank X»».
  - `formatUploadError` дополнен fallback'ом для `bank_unsupported` (если payload почему-то без bank_id).
- Тесты: `tests/test_imports_unsupported_bank.py` — **7/7 PASSED** (pending/in_review/broken reject, supported pass, no-match pass, no-accounts pass, exception fields contract pin).
- Регрессия: полный suite — 730 passed (было 723), 7 pre-existing fails не выросли.
- Документация: §21.6 в `Спецификация — Пайплайн импорта.md` расширена (порядок check'ов + frontend integration + тесты).
- Осталось до 🟩: manual smoke в браузере (4 сценария: contract-bound supported → 201 / contract-bound unsupported → 415 + modal / no contract match → 201 + null suggested_account / multi-bank user with mix → disclaimer banner показывается).
- Оценка: 0.5 дня (выполнено)

### 1.7 — Регрессионные fixtures из реальных выписок 🟥
- Файл: [[Фича — Whitelist банков для импорта]]
- Maintainer кладёт анонимизированные образцы в `tests/fixtures/statements/raw/` (gitignored). Существующий `test_import_normalizer_v2_golden.py` подхватит автоматически.
- Оценка: 1-1.5 дня

**Сумма Этапа 1:** ~4-5 рабочих дней (1.1–1.5 закрыты, 1.6 ждёт мержа Этапа 0.5, 1.7 ждёт образцов)

---

## ЭТАП 2 — Качество модерации 🟩
**Цель:** модератор перестаёт «забывать» решения юзера.
**Срок:** ~3-5 дней (карточка занижала из-за неучтённых race-protection + 2-pass семантики). Реально: ~5 дней (2026-05-03 → 2026-05-04).
**Блокирует:** публичный запуск (UX-блокер для retention).
**Прогресс:** 2.1-2.6 закрыты. 12/12 целевых тестов зелёных (1 Postgres-only skipped на SQLite).

### 2.1 — Миграция + модель 🟩
- Файл: [[Фича — Обучаемый operation_type]]
- Миграция 0062 (down_revision="0061"): колонка `operation_type VARCHAR(32) NULL` + UNIQUE INDEX (4-кол) с `NULLS NOT DISTINCT` + partial index `WHERE operation_type IS NOT NULL`
- Defensive duplicate check перед DROP CONSTRAINT, symmetric downgrade
- Boundary sanity NULLS NOT DISTINCT: подтверждён через psql (runtime-инвариант, не только metadata)
- Существующие 39/39 rule-related тестов зелёные после миграции
- Оценка: 0.5 дня

### 2.2 — Repository + service-слои 🟩
- Файл: [[Фича — Обучаемый operation_type]]
- `bulk_upsert` / `upsert` через `INSERT ... ON CONFLICT DO NOTHING` + `RETURNING` + fallback re-SELECT (race-safe; dialect-aware: pg_insert для Postgres, sqlite_insert для SQLite)
- `get_best_rule(want_op_type=False)` — backward compat (legacy single-pass), `want_op_type=True` — двухпроходный (сначала с op_type, fallback на legacy)
- `rule_stats_committer` пробрасывает op_type в upsert; skip-list (`transfer/refund/credit_disbursement`) остаётся СНАРУЖИ
- 39/39 existing rule tests зелёные
- Оценка: 1.5 дня

### 2.3 — Применение в enrichment 🟩
- Файл: [[Фича — Обучаемый operation_type]]
- Реализовано в `apply_decisions` priority slot 1 (cleaner separation: `enrichment._resolve_operation_type` остаётся heuristics-only, `apply_decisions` применяет priority ladder)
- `preview_row_processor` зовёт `get_best_rule(want_op_type=True)` единожды — результат идёт и в category, и в op_type
- DEBUG-лог `rule-keyword op_type conflict` при противоречии правила и keyword-сигнала
- `DecisionRow.assignment_reasons` пишет `f"operation_type из обученного правила #{rule.id}"` для audit-trail
- Оценка: 1 день

### 2.4 — Bulk-apply 🟩
- Файл: [[Фича — Обучаемый operation_type]]
- Bucket key (fp, category_id, operation_type) — 3-tuple. Mixed cluster (30 regular + 20 debt) → 2 правила. Uniform → 1 (backwards compat). UI не меняется.
- Нормализация `bucket_op_type = str(...).strip() or None` — защита от whitespace
- 128/128 existing bulk-apply тесты зелёные (нет регрессии uniform-cluster behavior)
- Оценка: 0.5 дня

### 2.5 — Тесты обучения и деактивации 🟩
- Файл: [[Фича — Обучаемый operation_type]]
- `tests/test_op_type_learning.py` — 12 тестов (8 контрактных + 4 расширенных): override после threshold, below-threshold guard, deactivation по rejections, co-existence, 2-pass priority, fallback на legacy, mixed bulk-upsert, skip-list negative (transfer), skip-list positive (debt), idempotent bulk-upsert (race), Postgres-only NULLS NOT DISTINCT (skipped on SQLite), audit-reason в DecisionRow
- Регрессионный прогон: 687 passed, 6 pre-existing fails (не выросли), 6 skipped, 0 регрессий из Этапа 2
- Оценка: 1 день

### 2.6 — Документация 🟩
- §22 «Обучаемый operation_type» в `Спецификация — Пайплайн импорта.md` (8 подсекций: zachem / model / repo / pipeline / bulk-apply / skip-list / known risks / deactivation)
- Memory `architecture_decisions.md` — блок «Op_type learning (Этап 2, decided 2026-05-04)»
- `project_operation_type_learning_gap.md` помечен **CLOSED 2026-05-04**, MEMORY.md индекс обновлён
- 4 новые backlog-карточки: «Atomic confirms increment via SQL UPDATE», «Cleanup pre-existing test failures», «Inherit op_type on attach_row_to_cluster», «Frontend audit_notes vs issues»
- Оценка: 0.5 дня

**Сумма Этапа 2:** ~5 рабочих дней — закрыт 2026-05-04. Все 6 под-задач 🟩.

---

## ЭТАП 3 — Экспорт и идемпотентность 🟥
**Цель:** GDPR-минимум + защита коммита от crash.
**Срок:** ~2-3 дня
**Блокирует:** публичный запуск (юридически + технически).

### 3.1 — GET /transactions/export.csv 🟥
- Файл: [[Фича — Экспорт транзакций CSV]]
- Streaming response, RU-locale, BOM
- Оценка: 1 день

### 3.2 — UI кнопка «Экспортировать» 🟥
- Файл: [[Фича — Экспорт транзакций CSV]]
- В шапке `/transactions`, period picker
- Оценка: 0.5 дня

### 3.3 — Idempotency-Key на commit_import 🟥
- Файл: [[Фича — Idempotency token на commit]]
- Redis storage 24h TTL
- Оценка: 1 день

### 3.4 — Партиальный retry commit 🟥
- Файл: [[Фича — Idempotency token на commit]]
- Пропуск уже закоммиченных rows (по created_transaction_id)
- Оценка: 0.5 дня

**Сумма Этапа 3:** ~2-3 рабочих дня

---

## ЭТАП 4 — Empty states & демо 🟥
**Цель:** новый пользователь не сталкивается с пустыми / бессмысленными метриками.
**Срок:** ~3-4 дня
**Блокирует:** публичный запуск (первое впечатление).

### 4.1 — Демо-режим 🟥
- Файл: [[Фича — Демо-режим]]
- POST /demo/seed-user, фабрика данных по 3 профилям
- Кнопка «Посмотреть на примере» на /login
- Оценка: 1.5 дня

### 4.2 — Empty states на dashboard / health / planning / goals 🟥
- Файл: [[Фича — Empty states и insufficient_data guard]]
- Большой CTA «Загрузить выписку» / «Демо»
- Оценка: 1 день

### 4.3 — Insufficient_data guard в MetricsService 🟥
- Файл: [[Фича — Empty states и insufficient_data guard]]
- Возврат null + флаг при <3 завершённых месяцах
- Оценка: 0.5 дня

### 4.4 — Компонент <MetricCard insufficientData /> 🟥
- Файл: [[Фича — Empty states и insufficient_data guard]]
- Прогресс-бар «N из 3 месяцев», серый цвет
- Оценка: 0.5 дня

**Сумма Этапа 4:** ~3-4 рабочих дня

---

## ЭТАП 5 — Онбординг и дизайн-унификация 🟥
**Цель:** структурированный первый experience + единый визуальный язык.
**Срок:** ~1-2 недели
**Блокирует:** публичный запуск.

### 5.1 — Инструкции «где взять выписку» 🟥
- Файл: [[Фича — Инструкции где взять выписку]]
- Контент для каждого whitelist-банка (скриншоты + текст)
- На пустом state /import + в BankPicker
- Оценка: 2 дня

### 5.2 — Онбординг-флоу 🟥
- Файл: [[Фича — Онбординг-флоу]]
- 5 шагов: welcome → импорт/демо → категории → tour → школа
- Поле onboarding_state на User
- Оценка: 2-3 дня

### 5.3 — Диагностика профиля пользователя 🟥
- Файл: [[Фича — Диагностика профиля пользователя]]
- AudienceProfileService.diagnose(), поле audience_profile на User
- Закрывает open-question в спеке школы
- Оценка: 1-1.5 дня

### 5.4 — Дизайн-аудит и унификация 🟥
- Файл: [[Фича — Дизайн-аудит и унификация]]
- Свод design tokens, удаление старой `components/import/`, унификация UI primitives
- Оценка: 3-5 дней

### 5.5 — Мобильная адаптация 🟥
- Файл: [[Фича — Дизайн-аудит и унификация]]
- Bottom-nav, fullscreen razvorot, sheet-фильтры
- Тестирование на iOS/Android
- Оценка: 1-2 дня

**Сумма Этапа 5:** ~9-13 рабочих дней (1.5-2.5 недели)

---

## ЭТАП 6 — Школа (Phase 8 + 8b) ⬜ DEFERRED
**Цель:** контентный фундамент «не трекер, а наставник».
**Срок:** ~4-6 недель
**Статус:** Deferred — после публичного запуска, до маркетинга.

### 6.1 — Модели школы 🟥
- Module, Lesson, LessonProgress, Quiz, QuizAttempt + миграции
- Оценка: 2 дня

### 6.2 — API школы 🟥
- Чтение уроков, отметки прохождения, квизы
- Оценка: 2 дня

### 6.3 — UI школы 🟥
- Страница /school, плеер, квизы, прогресс по модулям
- Оценка: 5-7 дней

### 6.4 — Контент модуля «Первый шаг» 🟥
- Файл: `03-School/Модуль школы — Первый шаг.md`
- 12-15 уроков: текст + видео-сценарии + квизы
- Оценка: 2-3 недели

### 6.5 — Контент модуля «Рост» 🟥
- Файл: `03-School/Модуль школы — Рост.md`
- 10-12 уроков
- После запуска для retention DTI<40% юзеров
- Оценка: отдельно (~2 недели)

### 6.6 — Контент модуля «Прорыв» 🟥
- Файл: `03-School/Модуль школы — Прорыв.md`
- 10-12 уроков
- Оценка: отдельно (~2 недели)

### 6.7 — Phase 8b — Widget Unlock System 🟥
- Файл: [[Фича — Система разблокировки виджетов]]
- unlocked_widgets JSON на User, эндпоинт unlock-widget
- UI блокировки виджетов до прохождения уроков
- Оценка: 3-4 дня

**Сумма Этапа 6:** ~4-6 недель (без модулей «Рост» и «Прорыв», их можно делать после запуска)

---

## Сводная таблица

| Этап | Статус | Прогресс | Срок | Блокирует |
|---|---|---|---|---|
| 0. Critical Import & Stability | 🟨 | 0.1+0.2+0.3+0.5 готовы по коду+тестам (ждут manual smoke); 0.4 + 0.6 не начаты | 1 нед | Закрытый тест |
| 0.7. Pre-deployment Hardening | 🟨 | 0.7.1 🟩 (alembic merge); 0.7.2–0.7.6 не начаты | 3.5 дн | **Закрытый тест** |
| 1. Whitelist банков | 🟨 | 1.1–1.5 + 1.6 (код+тесты, ждут smoke) закрыты; 1.7 ждёт образцов | 4-5 дн | Закрытый тест |
| 2. Качество модерации | 🟩 | Все 2.1–2.6 закрыты 2026-05-04 | 3-5 дн (по факту 5) | Публичный запуск |
| 3. Экспорт + идемпотентность | 🟥 | не начат | 2-3 дн | Публичный запуск |
| 4. Empty states + демо | 🟥 | не начат | 3-4 дн | Публичный запуск |
| 5. Онбординг + дизайн | 🟥 | не начат | 1.5-2.5 нед | Публичный запуск |
| 6. Школа | ⬜ DEFERRED | — | 4-6 нед | Маркетинг |

**До закрытого теста:** ~2.5 недели работы (Этапы 0 + 0.7 + 1)
**До публичного запуска:** +2.5-3 недели (Этапы 2 + 3 + 4 + 5)
**До маркетинга:** +1-1.5 месяца (Этап 6)

---

## Что НЕ входит в MVP (явно отложено)

Эти фичи есть в Backlog, но делаются после запуска:
- AI-категоризация (LLM fallback) — есть scaffold, без неё MVP работает
- AI-оценка активов
- AI финансовый консультант
- Семейный доступ
- Подкатегории
- Прогнозный виджет среднедневных трат
- Инвестиционный счёт (broker scaffold уже есть, виджеты потом)
- Криптокошельки
- Интеграция с розничными сетями
- Открытые API банков (ЦБ — 2027+)
- Telegram Login Widget (нужен permanent домен)
- Обучающие вебинары
- Ачивки
- Тегирование целевых денег по счетам
- Open Questions: мультивалютность, готовность к инвестициям

---

## История изменений плана

- **2026-05-03** — План создан после полного аудита проекта. Все этапы 🟥 NOT_STARTED. Этап 6 помечен ⬜ DEFERRED.
- **2026-05-03** — Этап 1 IN_PROGRESS: 1.1–1.5 закрыты. Колонки `extractor_status` на `banks` (не отдельная таблица), сидинг через `BankService.ensure_extractor_status_baseline` на startup, изолированный роутер `bank_support.py` (JSON-only без sample-файлов). 1.6 (guard на upload) ждёт мержа Этапа 0.5 — пересечение по `import_service.upload_file`. 1.7 (regression fixtures) ждёт образцов от maintainer'а. §21 «Поддержка банков и whitelist» добавлена в `Спецификация — Пайплайн импорта.md`.
- **2026-05-03** — Этап 0.1 (Refresh Token) реализован: `/auth/refresh` + `/auth/logout`, миграция 0059, multi-device, rotation + reuse-detection, `with_for_update()` против race, frontend interceptor с singleton refreshPromise + RETURN_TO_KEY, Celery beat `prune_refresh_tokens`. 19 тестов написаны. Статус 🟨 — ждёт docker-прогона + 12 smoke-сценариев. Memory `architecture_decisions.md` обновлён блоком про refresh-token scheme.
- **2026-05-03** — Этап 0.2 (Лимит размера файла + content-type whitelist) реализован: `app/services/upload_validator.py` (streaming, magic-detection, CSV negative-check для cp1251, XLSX zip-bomb защита) + `MaxBodySizeMiddleware` (Content-Length 30 MB cap) + helper `_upload_helpers.py` + интеграция в `/imports/upload` и `/telegram/bot/upload`. Frontend pre-upload validation + `formatUploadError` mapper для 7 кодов + `accept` атрибут. 49 тестов (23 + 9 + 17). Статус 🟨 — ждёт прогона + 10 smoke. 4 follow-up backlog cards (Bot-side validation, Memory-efficient pipeline, Frontend test infra, Frontend error-codes typings). Memory обновлён.
- **2026-05-03** — Этап 0.3 (Rate-limit) — дизайн-план готов, статус 🟧 IN_DESIGN. slowapi + Redis backend, per-IP/per-user разделение, custom 429 handler с Retry-After, helper `client_ip.py` (X-Forwarded-For + TRUSTED_PROXIES) закроет TODO 0.2. Эстимейт уточнён: 2 дня (карточка занижала до 0.5). Старт после прогона+smoke 0.2.
- **2026-05-03** — Этап 2 (operation_type learning) IN_PROGRESS. 2.1: миграция 0062 с `NULLS NOT DISTINCT` + 4-кол UNIQUE INDEX + partial index, defensive duplicate check, symmetric downgrade. 2.2: `bulk_upsert` через `INSERT ... ON CONFLICT DO NOTHING` + RETURNING (race-safe, dialect-aware), `get_best_rule(want_op_type=True)` двухпроходный (сначала op_type, fallback на legacy), skip-list `non_analytics_operation_types` остаётся снаружи в committer'е. 39/39 existing rule tests зелёные. 2.3 на старте.
- **2026-05-04** — Добавлен Этап 0.7 — Pre-deployment Hardening (~3.5 дня) после ревью плана GPT-5.5. Закрывает дыру «как выпускать», которую план до этого не адресовал. 6 под-задач: alembic merge resolution (0059+0062 две головы → нужен merge), staging environment (отсутствовал между dev и prod), observability minimum (Sentry + structlog для 5 ключевых операций), MVP Launch Gate checklist (12-15 release-control критериев в финале плана), Playwright E2E smoke (happy + sad path), security pre-flight (single-source-of-truth checklist вместо распылённой security по этапам). Этап 0.7 блокирует закрытое тестирование наравне с этапами 0+1. До-закрытое-тестирование оценка скорректирована с ~2 недель до ~2.5 недель.
- **2026-05-04** — Этап 0.7.1 (alembic merge) **закрыт 🟩**. Создана `0063_merge_refresh_tokens_and_op_type.py` с `down_revision=("0059", "0062")` — pure join, без schema changes. Auto-gen hash-revision переименован на numeric convention. Cycle test (upgrade head → downgrade 0058 → upgrade head) чистый. Single head `0063`. Documented Ambiguous walk caveat для `downgrade -1` (use explicit target). Smoke 83/83 tests passed.
- **2026-05-04** — Этап 2 (operation_type learning) **закрыт 🟩**. 2.3: `apply_decisions` priority slot 1 + `want_op_type=True` в `preview_row_processor` + `DecisionRow.assignment_reasons` для audit-trail. 2.4: bucket key `(fp, category_id, operation_type)` — mixed cluster даёт N правил, uniform — одно (backwards compat). 2.5: 12 тестов в `tests/test_op_type_learning.py` (11 passed + 1 Postgres-only skipped on SQLite), 687 passed на полном suite, 6 pre-existing fails не выросли. 2.6: §22 в спеке пайплайна импорта, memory `architecture_decisions.md` блок, `project_operation_type_learning_gap.md` помечен CLOSED. 4 новые backlog-карточки: «Atomic confirms increment via SQL UPDATE», «Cleanup pre-existing test failures» (4+2+1=7 fails), «Inherit op_type on attach_row_to_cluster», «Frontend audit_notes vs issues» (pre-emptive). Известные ограничения: skip-list rows не учатся (отдельный backlog), cross-request idempotency через Этап 3.3 Idempotency-Key.
- **2026-05-04** — **Регрессия 0.3 зафиксена**: `FastAPIError: ForwardRef('UploadFile')` на upload-роутах. Причина — `from __future__ import annotations` + slowapi `functools.wraps` + ForwardRef-резолюция через `__globals__` обёртки (slowapi-модуль, без `UploadFile`). Фикс: убрать `from __future__ import annotations` в `app/api/v1/imports.py` и `app/api/v1/telegram.py`. Дополнительно — `headers_enabled=False` в Limiter (slowapi-обёртка крашится при возврате Pydantic-модели без `response: Response` в сигнатуре; 429-путь имеет свой Retry-After handler). API оживает, `/docs` отвечает 200.
- **2026-05-04** — Шаг 1.6 (Жёсткий guard на upload) **готов по коду + тестам, статус 🟨** (ждёт manual smoke). Backend: `BankUnsupportedError` в `ImportService.upload_file` после resolve `suggested_account_id` через `account_repo.get_by_id_and_user` → проверка `account.bank.extractor_status == 'supported'`. Route handlers (`/imports/upload` + `/telegram/bot/upload`) ловят и возвращают 415 со структурой `{code: 'bank_unsupported', bank_id, bank_name, extractor_status, detail}` (+ `bot_message` для bot-варианта). Порядок check'ов в `upload_file`: file_hash dedup (0.5) → extract → bank guard (1.6) → create session. Dedup первым потому что cheap, guard после extract'а потому что банк определяется через extraction.meta; сессии unsupported-банков никогда не создаются → семантически инвариантен порядок. Frontend: `uploadMut.onError` ловит `code='bank_unsupported'` и открывает `BankSupportRequestModal` pre-filled (без generic toast'а); `<UnsupportedBankBanner>` над import-area для юзеров с mix-банками (CTA per unsupported банк); `formatUploadError` дополнен fallback'ом. Тесты: `tests/test_imports_unsupported_bank.py` — 7/7 PASSED (pending/in_review/broken reject, supported pass, no-match pass, no-accounts pass, exception fields contract pin). Полный suite: 730 passed (было 723), 7 pre-existing fails не выросли. Документация: §21.6 в спеке пайплайна расширена. Открытый вопрос: PATCH `/imports/{id}/account` (assign post-upload) **не дублирует guard** — out of MVP scope, полагаемся на frontend.
- **2026-05-04** — Этап 0.5 (Дубликат-выписка UX) **готов по коду + тестам, статус 🟨** (ждёт manual smoke). 0.5.5: `tests/test_imports_duplicate_upload.py` — **9/9 PASSED**. По пути зафиксен production-баг: fresh-upload путь в `ImportService.upload_file` возвращал dict БЕЗ ключей `action_required` / `existing_progress` / `existing_status` / `existing_created_at` — фронт бы крашился `KeyError`. Все 4 ключа теперь во ВСЕХ ответах upload (инвариант контракта). Также фикс инфраструктурных багов в тестах: `_FakeService.upload_source(force_new=False)` в двух test-файлах, `FixedWindowRateLimiter(new_storage)` swap в rate-limit fixtures (strategy ловит storage в `__init__`, swap только `_storage` оставлял enforcement на Redis), `poolclass=StaticPool` в conftest (FastAPI threadpool иначе видел свежий :memory: без таблиц), `_disable_rate_limit_by_default` autouse-fixture (без неё test_imports_upload_validation видел загрязнённые Redis-бакеты от rate-limit-тестов). После всех фиксов: 723 passed, 7 pre-existing fails (как baseline). 0.5.6: §23 в спеке пайплайна импорта, memory `architecture_decisions.md` блок «Duplicate-statement UX», MVP plan статус 0.5 → 🟨, 1.6 UNBLOCKED. 3 новые backlog-карточки: [[Фича — Bot reads structured error messages]] (HIGH — bot молча принимает duplicate, confusion-source), [[Фича — Atomic destructive replace для duplicate UX]] (MEDIUM пост-MVP), [[Фича — Race-safe duplicate detection]] (LOW миграция с partial UNIQUE INDEX).
