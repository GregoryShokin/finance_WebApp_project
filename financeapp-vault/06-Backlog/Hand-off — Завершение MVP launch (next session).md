# Hand-off — Завершение MVP launch
#подготовка-к-запуску #handoff
> ТЗ для следующей сессии. Все этапы 0.1+0.2+0.3+0.5+1.6 готовы по коду + тестам, ждут manual smoke. Остаются 0.4 + 0.6 + 0.7 + 1.7 + cleanup.

**Дата создания:** 2026-05-04
**Контекст:** предыдущая сессия закрыла Этап 0.5 + Шаг 1.6 + регрессию 0.3 (FastAPIError ForwardRef UploadFile).

---

## Состояние на момент hand-off (2026-05-04)

### 🟩 Закрыто полностью
- Этап 2 (operation_type learning) — 12 тестов, документация, memory.
- Этап 0.7.1 (alembic merge resolution) — миграция 0063, single head.
- Шаги 1.1–1.5 (bank whitelist column + API + UI + bank-support requests + UI).

### 🟨 Готово по коду + тестам, ждёт manual smoke (5 этапов)
| Этап | Тесты | Smoke сценарии |
|---|---|---|
| 0.1 Refresh Token | 19/19 (2 SQLite-only fail в полном suite — Postgres-naive datetime) | 12 (silent refresh, parallel 401 coalescing, reuse-detection) |
| 0.2 Upload validation | 49/49 | 10 (30 MB PDF toast без сетевого, .csv с PDF magic → 415, zip-bomb XLSX) |
| 0.3 Rate-limit | 17/17 | 3 (login spam → 429, register spam → 429, upload spam → 429) |
| 0.5 Duplicate-выписка UX | 9/9 | 5 (первая → CHOOSE → «Открыть существующую», «Загрузить как новую», committ + повторная → WARN) |
| 1.6 Bank guard upload | 7/7 | 4 (supported pass, unsupported → modal pre-filled, no-match pass, mix-bank disclaimer banner) |

**Полный suite:** 730 passed, 7 pre-existing fails (baseline), 6 skipped, 3 xfailed. 0 регрессий.

### 🟥 НЕ начато (для этой сессии)
- Этап 0.4 — Worker timeout и зависшие сессии (1 день).
- Этап 0.6 — Бэкапы БД (0.5 дня).
- Этап 0.7.2–0.7.6 — staging, observability, launch gate, E2E, security pre-flight (3-3.5 дня).
- Шаг 1.7 — Регрессионные fixtures из реальных выписок (ждёт анонимизированных образцов от Григория).
- Cleanup pre-existing fails (1-2 часа) — блокер 0.7.4 «Launch Gate требует полный pytest зелёный».

---

## Memory (читать первым)
`/Users/grigorii/.claude/projects/-Users-grigorii-Documents-Projects-finance-WebApp/memory/`

Особенно важны после предыдущей сессии:
- `MEMORY.md` — индекс.
- `architecture_decisions.md` — все load-bearing decisions, добавлены блоки «Rate limits» (0.3) и «Duplicate-statement UX» (0.5), расширен «Bank whitelist» (1.6 guard implementation + order of checks).
- `project_state.md` — состояние проекта (snapshot 2026-05-03, нужно дочитать обновлённый MVP plan).

## Vault (продуктовые спеки)
- `financeapp-vault/06-Backlog/Подготовка к запуску MVP.md` — главный чеклист.
- `financeapp-vault/14-Specifications/Спецификация — Пайплайн импорта.md` — §21 (whitelist + 1.6 guard), §22 (op_type learning), §23 (duplicate detection).

---

## Приоритизированный план для следующей сессии

### Приоритет 1 — Manual smoke 5 этапов (1-2 часа в браузере)
**Кто:** Григорий лично. Агент координирует, не выполняет.

Сценарии — см. таблицу выше. После прохождения каждого этапа → пометить статус 🟩 в `Подготовка к запуску MVP.md`.

Если smoke выявит баг → создать backlog-карточку, не лечить инлайн (контекст этой сессии не должен расширяться на debug).

### Приоритет 2 — Этап 0.4 Worker timeout (1 день)
Карточка: `06-Backlog/Фича — Worker timeout и зависшие сессии.md`.
- Watchdog Celery beat (каждые 2-3 мин): сканирует `ImportSession.summary_json["auto_preview"]` и transfer_match, помечает `status="failed"` если `started_at` старше 10 мин и `finished_at` отсутствует.
- `soft_time_limit=600` на jobs в Celery config.
- API endpoint `POST /imports/{session_id}/retry-preview` — снимает failed-статус и запускает auto_preview заново.
- Frontend: `import-status-card.tsx` при `status="failed"` показывает алерт + кнопку «Повторить». При `status="running"` >30 сек — индикатор «обработка занимает дольше обычного».

### Приоритет 3 — Этап 0.6 Бэкапы БД (0.5 дня)
Карточка: `06-Backlog/Фича — Бэкапы базы данных.md`.
- Сервис `backup` в `docker-compose.yml` (или внешний cron на хосте).
- `pg_dump --format=custom` ежедневно 04:00 UTC.
- Volume `./backups/` (или Yandex Object Storage для пост-MVP).
- Ротация: 7 ежедневных + 4 еженедельных + 3 ежемесячных, gzip.
- Скрипты `scripts/backup_db.sh` + `scripts/restore_db.sh`.
- README раздел про backup/restore + квартальный проверочный restore.

### Приоритет 4 — Cleanup pre-existing fails (1-2 часа)
Карточка: `06-Backlog/Фича — Cleanup pre-existing test failures.md`. 7 fails:
- 4 в `test_bulk_cluster_grouping` (MIN_CLUSTER_SIZE регрессия).
- 2 в `test_auth_refresh` (SQLite naive datetime — Postgres-only).
- 1 в `test_category_rule_lifecycle` (LLM-related, LLM удалён 2026-05-03).

Блокер 0.7.4 (Launch Gate требует «полный pytest зелёный»). Подходит для разогрева в начале сессии.

### Приоритет 5 — Этап 0.7 Pre-deployment Hardening (3-3.5 дня)
- 0.7.2 Staging environment — `docker-compose.staging.yml`, restore-from-prod-snapshot процедура.
- 0.7.3 Observability minimum — Sentry + structlog для 5 ключевых операций.
- 0.7.4 MVP Launch Gate checklist — release-control документ с 12-15 критериями.
- 0.7.5 Playwright E2E smoke — 2 сценария (happy + sad path).
- 0.7.6 Security pre-flight — secrets rotation, CORS prod, HTTPS, audit hardcoded secrets.

### Приоритет 6 — Шаг 1.7 Регрессионные fixtures
Ждёт анонимизированных образцов выписок от Григория в `tests/fixtures/statements/raw/` (gitignored). Если образцы появятся в этой сессии — прогнать `test_import_normalizer_v2_golden.py`.

---

## Известные следствия и edge cases

### Order of checks в `upload_file` (фиксированный 2026-05-04)
```
1. file_hash = sha256(raw_bytes)         # cheap
2. find_by_file_hash → CHOOSE/WARN       # dedup before expensive extract
3. extract                                # PDF parse expensive
4. recognize → suggested_account_id       # account binding
5. bank guard (1.6) → BankUnsupportedError # only if positive bank match
6. create session
```

### Контракт ответа upload
Все 4 ключа `(action_required, existing_progress, existing_status, existing_created_at)` присутствуют ВО ВСЕХ ответах upload, включая fresh-upload (со значением `null`). Инвариант, защищён тестом `test_first_upload_creates_session_no_duplicate_marker`.

### file_hash semantics
`sha256(raw_bytes)` — exact byte match. Изменение в PDF (юзер открыл, добавил пометку, пересохранил) → новый hash → новая session. Это intentional (см. memory architecture_decisions.md «Duplicate-statement UX»).

### Bank guard fires только при positive match
`suggested_account_id is None` → guard skipped. Brand-new юзер без счетов или first-time upload от нового банка проходят. Frontend disclaimer (`<UnsupportedBankBanner>`) — proactive line of defense для mix-bank сценария.

### PATCH `/imports/{id}/account` НЕ дублирует guard
Out of MVP scope. Если smoke выявит «загрузил с supported, потом переключил на unsupported account» → backlog item.

### Manual статусы `in_review` и `broken`
`BankService.ensure_extractor_status_baseline()` НЕ трогает их при рестарте. Менять через прямой UPDATE через CLI / админ-доступ. Guard их treats как unsupported (только `supported` проходит).

### bot не читает bot_message
Backend возвращает `bot_message` (Russian text) в duplicate-detection и bank_unsupported response, но bot/main.py пока его игнорирует. Backlog HIGH `Фича — Bot reads structured error messages`.

---

## Критичные правила (CLAUDE.md compliance)

### Alembic
Новые миграции через `alembic revision --autogenerate -m "..." --rev-id 00XX`. Никогда без `--rev-id` (получишь hash который ломает convention).

### Conftest changes (важно для regression)
Предыдущая сессия добавила в `tests/conftest.py`:
- `poolclass=StaticPool` — SQLite in-memory shared между threadpool worker'ами FastAPI.
- Autouse `_disable_rate_limit_by_default` — выключает limiter для всех тестов; rate-limit-specific тесты сами re-enable через monkeypatch.

Если будешь писать новые TestClient-based тесты с rate-limit — убедись, что включаешь limiter тем же паттерном (см. docstring `_disable_rate_limit_by_default` для напоминания, что нужны swap'ы и `_storage`, и `_limiter`).

### Slowapi gotchas (зафиксировано предыдущей сессией)
- НЕ ставить `from __future__ import annotations` в файлы с rate-limited routes — ломает FastAPI ForwardRef резолюцию через slowapi wrapper.
- `headers_enabled=False` в Limiter — slowapi wrapper crashed на success-path, если handler возвращает Pydantic-модель без `response: Response` параметра.

### Не trespass в чужие зоны
Если smoke выявит баг в зоне, которая не относится к текущему шагу — создай backlog-карточку, не фикси инлайн (не рассеивай контекст). Исключение — production-баги (frontend crash, data loss): фикси с явным согласованием.

### Не commit без явного запроса
Все наработки 0.1+0.2+0.3+0.5+1.6 — uncommitted. Локально в working tree. Когда коммитить — Григорий решает (после успешного manual smoke + 🟩 на этапе).

---

## Action items для Григория перед открытием новой сессии

1. **Manual smoke 5 этапов** в браузере — переводит 🟨 → 🟩.
2. (Опционально) **Анонимизированные образцы выписок** в `tests/fixtures/statements/raw/` для Шага 1.7.
3. **Решение:** что приоритетнее в новой сессии:
   - 0.4 + 0.6 (закрытие Этапа 0)
   - 0.7 (pre-deployment hardening)
   - cleanup + smoke координация
   - комбинация

## First action для следующего агента
1. Прочитать memory + этот hand-off + `Подготовка к запуску MVP.md`.
2. Прочитать `git status` + `git log --oneline -20` для текущего состояния.
3. Подтвердить с Григорием приоритет на эту сессию (одно из выше).
4. Стартовать.

Не предполагать, что smoke прошёл — спросить статус 🟩-перевода у Григория явно.
