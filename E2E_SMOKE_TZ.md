# ТЗ для Claude Code: E2E smoke-suite на Playwright для FinanceApp MVP

> **Адресат:** Claude Code в новой сессии в этом репо.
> **Автор ТЗ:** аналитический агент в Cowork-сессии Григория.
> **Источник требований:** QA brief на 38 сценариев (приведён в разделе [§9](#9-исходный-qa-brief)).
> **Дата:** 2026-05-04.
> **Статус:** §8 — приняты решения по всем 6 открытым вопросам, ТЗ готово к исполнению. Стартовать с Фазы 0.

---

## 0. TL;DR

Нужно поднять с нуля **Playwright + TypeScript** suite в новой папке `e2e/` в корне монорепо, который автоматически прогоняет 35 из 38 сценариев closed-test приёмки FinanceApp MVP. Suite должен запускаться одной командой (`npm run test:smoke` из `e2e/`), детерминированно проходить против локального стека (`docker compose up --build`), репортить упавшие сценарии в формате близком к QA brief. Это **regression suite на годы вперёд**, не одноразовый скрипт.

3 сценария оставляем на ручную приёмку (CC.2 mobile responsive — реалистично проверяет только человек; куски CC.1 «посмотреть глазами на UX»).

Работай **итеративно по фазам**. Каждая фаза — самостоятельный, проверяемый PR-кандидат. Не пытайся сделать всё за один проход.

---

## 1. Контекст и цель

### Что строим
- Регрессионный smoke на критические flow перед закрытым тестированием MVP и перед каждым релизом после.
- Покрывает: auth + refresh-token flow, upload validation (size/magic-byte/zip-bomb), rate-limit, duplicate detection при импорте, bank guard, happy path E2E, edge-cases (offline, expired cookies).

### Что НЕ строим
- НЕ unit-тесты компонентов (это отдельная задача).
- НЕ visual regression (Percy / Chromatic) — на этом этапе избыточно.
- НЕ нагрузочное тестирование.
- НЕ покрытие 100% UI — только critical-path.
- НЕ CI integration в этой задаче. Suite должен **уметь** работать в CI (детерминированный, без ручных шагов), но настройку GitHub Actions сделаем отдельной фазой позже.
- НЕ переписываем основной код. Если найдёшь баг по ходу — не фикси, оформляй как `KNOWN_ISSUES.md` запись и продолжай.

### Связь с roadmap
В `financeapp-vault/07-Roadmap/Фаза 0 — Фундамент.md` это Этап 0.7.5 (или близко). Сейчас он подтягивается вперёд, до закрытого теста, потому что 38 сценариев руками — нереалистично.

---

## 2. Технический стек и обоснование

| Компонент | Выбор | Почему |
|---|---|---|
| Test runner | **Playwright @latest stable (v1.49+)** | Лучший DevTools-уровень контроля: cookies, network, offline-mode, мобильные viewports — всё из коробки. |
| Язык | **TypeScript strict** | Согласован с frontend. Типы для API responses ловят регрессии на этапе компиляции. |
| Браузеры | **Chromium only** | Закрытый тест предполагает Chrome 90%+ юзеров. Firefox/Safari — после MVP. |
| Структура | Чистые функции-helpers, **БЕЗ Page Object Model** | POM окупается на >100 спеков с активной эволюцией UI. У нас 35 сценариев, 80% уникальные flow — POM создаст больше абстракций, чем сэкономит. |
| Ассерты | Native `expect` from `@playwright/test` | Не тащим chai/jest. |
| HTTP в helpers | Playwright `request` context | Не fetch, не axios — единый API. |
| Управление DB | **БЕЗ ORM в тестах**. Прямые SQL через `pg` или сидинг через FastAPI test endpoints | Тесты не должны знать про SQLAlchemy. См. [§5](#5-backend-test-endpoints-новые-обязательные). |

---

## 3. Архитектура и структура папок

Создавай в **корне монорепо**, не внутри `frontend/`. Suite тестирует stack целиком (FastAPI + Next.js + Postgres + Redis), ему место рядом с `docker-compose.yml`.

```
finance_WebApp/
├── e2e/                              # ← новая папка
│   ├── package.json                  # отдельный package, не смешан с frontend
│   ├── playwright.config.ts
│   ├── tsconfig.json
│   ├── .env.example                  # E2E_API_URL, E2E_FRONTEND_URL, E2E_DB_URL
│   ├── README.md                     # как запускать локально
│   │
│   ├── global-setup.ts               # health-check сервисов, prepare seed
│   ├── global-teardown.ts            # cleanup test data
│   │
│   ├── helpers/
│   │   ├── auth.ts                   # register(), login(), logout(), getCookies()
│   │   ├── api.ts                    # typed wrappers для прямых API calls
│   │   ├── network.ts                # waitForRequest/Response, expectCallSequence
│   │   ├── cookies.ts                # setCookieExpiry(), deleteAccessCookie() и т.д.
│   │   ├── files.ts                  # generateLargeFile(), generateZipBomb(), генераторы fixtures
│   │   ├── seed.ts                   # createTestUser(), createTestAccount(), createTestBank()
│   │   ├── reset.ts                  # resetRateLimit(), cleanupUser()
│   │   └── selectors.ts              # стабильные data-testid селекторы (см. §6.2)
│   │
│   ├── fixtures/
│   │   ├── statements/               # symlink → ../../Bank-extracts/ (gitignored), реальные anonymized выписки. См. §3.1.
│   │   │   └── .gitkeep
│   │   ├── statements-synthetic/     # синтетические маленькие CSV/PDF, committed
│   │   │   ├── valid-sber.csv
│   │   │   ├── cyrillic-cp1251.csv
│   │   │   └── tiny-valid.pdf
│   │   ├── adversarial/
│   │   │   ├── zip-bomb.xlsx         # committed, ~250KB на диске, 200MB в распаковке
│   │   │   ├── empty.csv
│   │   │   ├── fake-extension.exe
│   │   │   └── README.md             # объяснение каждого файла
│   │   └── (large files генерятся on-the-fly в global-setup)
│   │
│   ├── specs/
│   │   ├── 01-auth-refresh.spec.ts          # 12 сценариев Этапа 0.1
│   │   ├── 02-upload-validation.spec.ts     # 10 сценариев Этапа 0.2
│   │   ├── 03-rate-limit.spec.ts            # 3 сценария Этапа 0.3
│   │   ├── 05-duplicate-detection.spec.ts   # 5 сценариев Этапа 0.5
│   │   ├── 16-bank-guard.spec.ts            # 4 сценария Этапа 1.6
│   │   └── cc-cross-cutting.spec.ts         # CC.1, CC.3, CC.4 (без CC.2)
│   │
│   └── reports/                      # gitignored, output Playwright HTML reporter
│       └── .gitkeep
│
├── backend/                          # существующий код (НЕ трогаем business logic)
│   └── app/api/v1/test_utils.py      # ← НОВЫЙ файл, см. §5
│
├── docs/
│   └── E2E_KNOWN_ISSUES.md           # ← новый, баги найденные suite'ом
│
└── E2E_SMOKE_TZ.md                   # этот документ
```

### Почему `e2e/` отдельный package
- Не смешиваем dev-зависимости frontend (React, Next, Tailwind) с e2e-зависимостями (Playwright, pg).
- Можно запускать без поднятия frontend node_modules (важно для CI).
- В будущем легко вынести в отдельный репо, если потребуется.

### 3.1 Источник реальных выписок (`Bank-extracts/`)

Anonymized выписки разных банков лежат в `Bank-extracts/` в корне репо. Это и есть источник правды для всех тестов, которым нужен «реальный» PDF/CSV/XLSX (happy-path импорта, dedup, bank-guard, recognition).

**Правила:**

1. В `e2e/global-setup.ts` или в README — инструкция создать симлинк: `ln -s ../../Bank-extracts e2e/fixtures/statements` (одной командой). Симлинк gitignored.
2. Тесты ссылаются на файлы по относительному пути: `fixtures/statements/sber-2026-03.pdf` и т.п. **Никогда** не хардкодь абсолютный путь к `Bank-extracts/`.
3. Полный список доступных выписок и их назначение (какой банк, какой период, что покрывает) Claude Code должен **узнать у Григория** в начале Фазы 3, не угадывать имена файлов.
4. Если для какого-то теста нужной выписки нет в `Bank-extracts/` — генерим синтетический минимальный CSV в `fixtures/statements-synthetic/` (committed, ~1KB). Не пытайся придумать «реалистичный» PDF.
5. **Запрет:** не копируй файлы из `Bank-extracts/` в `e2e/fixtures/statements-synthetic/` (committed) — это эквивалентно коммиту PII в репо. Только синтетика идёт в committed.

---

## 4. Фазы реализации

Каждая фаза — атомарная единица работы. Выполняй **строго по порядку**. После каждой фазы:
1. Запусти suite (или его часть, доступную на этой фазе) — должно быть зелёно.
2. Закоммить изменения с описательным сообщением.
3. Покажи Григорию краткий отчёт: что сделано, что осталось, какие сюрпризы. Спроси go/no-go перед следующей фазой.

### Фаза 0 — Bootstrap (1–2 часа)

**Цель:** запускающийся пустой `playwright test` со здоровой инфраструктурой.

Задачи:
1. `cd /Users/grigorii/Documents/Projects/finance_WebApp && mkdir e2e && cd e2e`
2. `npm init -y`, `npm install -D @playwright/test typescript @types/node pg @types/pg dotenv`
3. `npx playwright install chromium` (только chromium, не все 3 браузера).
4. Создай `tsconfig.json` (target ES2022, strict, esModuleInterop).
5. Создай `playwright.config.ts`:
   - `testDir: './specs'`
   - `timeout: 30_000`, `expect.timeout: 10_000`
   - `use.baseURL: process.env.E2E_FRONTEND_URL ?? 'http://localhost:3000'`
   - `use.trace: 'retain-on-failure'`
   - `use.video: 'retain-on-failure'`
   - `use.screenshot: 'only-on-failure'`
   - `reporter: [['list'], ['html', { outputFolder: 'reports', open: 'never' }]]`
   - `globalSetup: './global-setup.ts'`
   - `workers: process.env.CI ? 1 : 2` (rate-limit suite потребует workers=1, остальное может параллелиться)
   - `projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }]`
6. `global-setup.ts`:
   - Проверь `GET http://localhost:8000/api/v1/health` → 200. Если нет — `throw` с понятным сообщением.
   - Проверь `GET http://localhost:3000` → 200.
   - Проверь, что test-эндпоинты доступны (см. фазу 1).
7. `.env.example` с переменными.
8. `.gitignore`: `node_modules/`, `reports/`, `test-results/`, `fixtures/statements/*` (кроме `.gitkeep`).
9. Создай **один dummy-spec** `specs/00-smoke.spec.ts` который ходит на baseURL и проверяет статус — чтобы убедиться, что инфра работает.
10. Корневой `package.json` или **новый** `e2e/package.json` scripts:
    - `"test:smoke": "playwright test"`
    - `"test:smoke:headed": "playwright test --headed"`
    - `"test:smoke:ui": "playwright test --ui"`
    - `"test:smoke:report": "playwright show-report reports"`

**Definition of Done (DoD) фазы 0:**
- `cd e2e && npm run test:smoke` проходит зелёно (один dummy-тест).
- `npm run test:smoke:report` открывает HTML отчёт.
- В README.md указано как запускать (предусловие: docker compose поднят).

---

### Фаза 1 — Backend test endpoints + auth helpers (2–3 часа)

**Цель:** инфраструктура для управления тестовыми данными из spec-файлов.

#### 1.1 Backend test endpoints

Создай `app/api/v1/test_utils.py`. Доступ контролируется отдельным флагом `ENABLE_TEST_ENDPOINTS` (см. §5 — три слоя защиты). Дефолт `False`. Никакой привязки к `settings.environment`.

Эндпоинты (все под префиксом `/api/v1/_test/`):

```
POST /_test/seed/user
  body: { email, password, full_name }
  response: { user_id, access_token, refresh_token }
  Создаёт юзера или возвращает существующего по email. Idempotent.

POST /_test/seed/account
  body: { user_id, name, type, bank_id?, contract_number?, balance? }
  response: { account_id }

POST /_test/seed/bank
  body: { name, extractor_status: 'supported'|'pending'|'in_review'|'broken' }
  response: { bank_id, extractor_status, created: bool }
  UPSERT-семантика: если банк с таким name есть — обновляет extractor_status и
  возвращает { created: false }. Иначе создаёт и возвращает { created: true }.
  Это использует Фаза 6: тест 1.6.2 переключает Сбер в pending, грузит обычную
  Сбер-выписку (ожидает 415), в teardown возвращает 'supported'.

POST /_test/cleanup/user
  body: { email }
  Удаляет юзера и весь его cascade (accounts, transactions, import_sessions, etc.)

POST /_test/reset/rate-limit
  body: { scope: 'login'|'register'|'upload', identifier?: str }
  Чистит соответствующий ключ в Redis (например, ratelimit:login:127.0.0.1).

POST /_test/auth/issue-tokens
  body: { user_id, access_ttl_seconds?: int, refresh_ttl_seconds?: int }
  response: { access_token, refresh_token }
  Прямая выдача токенов с кастомным TTL — используется в сценарии 0.1.7
  (silent refresh без 16-минутной паузы). Также возвращает Set-Cookie
  заголовки, чтобы тест мог сразу применить их через context.addCookies().

GET /_test/import-session/{id}
  response: { id, total_rows, user_actions_count, committed }
  Для проверки состояния сессии импорта в дедуп-сценариях.
```

**Важно:** все мутирующие эндпоинты — POST с явным телом, никаких неявных побочных эффектов через GET. Все идемпотентны где это разумно. Все возвращают структурированный JSON, не строки.

**Тест:** в `tests/test_test_utils.py` напиши минимальные unit-тесты:
- endpoints работают при `ENABLE_TEST_ENDPOINTS=true`;
- **404 на каждом endpoint при `ENABLE_TEST_ENDPOINTS=false`** (через TestClient + monkeypatch на settings);
- `seed/bank` с существующим именем апдейтит `extractor_status` и возвращает `created: false`;
- `seed/bank` с новым именем создаёт и возвращает `created: true`.

#### 1.2 Auth helpers (e2e/helpers/)

`helpers/auth.ts`:
```typescript
export async function registerTestUser(api: APIRequestContext, opts?: Partial<{ email, password, fullName }>): Promise<TestUser>
export async function loginViaUI(page: Page, user: TestUser): Promise<void>
export async function loginViaAPI(context: BrowserContext, user: TestUser): Promise<void>  // быстрее, для setup
export async function logoutViaUI(page: Page): Promise<void>
export function getAuthCookies(context: BrowserContext): Promise<{ access?: Cookie, refresh?: Cookie }>
export async function expireAccessCookie(context: BrowserContext): Promise<void>
export async function deleteCookie(context: BrowserContext, name: 'access' | 'refresh' | 'both'): Promise<void>
```

`helpers/seed.ts`:
```typescript
export async function seedUser(api: APIRequestContext, ...): Promise<TestUser>
export async function seedAccount(api: APIRequestContext, userId, ...): Promise<TestAccount>
export async function seedBank(api: APIRequestContext, name, status): Promise<TestBank>
export async function cleanupUser(api: APIRequestContext, email): Promise<void>
```

#### 1.3 Первые 3 spec'а как proof-of-concept

В `specs/01-auth-refresh.spec.ts` реализуй сценарии **0.1.1, 0.1.2, 0.1.3** из QA brief. Это базовая регистрация + login happy path + login wrong password. Используй helpers из 1.2.

Ассерты:
- 0.1.1: после submit URL содержит `/dashboard`, в `context.cookies()` есть оба токена с правильными `httpOnly`/`sameSite`/`expires`.
- 0.1.2: то же.
- 0.1.3: response status 401, toast виден (по `data-testid="toast-error"` или role+text), cookies нет.

**DoD фазы 1:**
- Backend test endpoints реализованы, юнит-тесты зелёные.
- Helpers покрывают auth-флоу.
- 3 spec'а зелёные.
- Suite полностью идемпотентен — можно запустить 5 раз подряд без падений (cleanup в `afterEach` или уникальные emails через `Date.now()`).

---

### Фаза 2 — Полный refresh-token suite (3–4 часа)

Реализуй оставшиеся 9 сценариев Этапа 0.1 в том же `specs/01-auth-refresh.spec.ts`.

Особые места — продумай заранее:

**0.1.4 Silent refresh при удалённом access:**
```typescript
test('0.1.4 silent refresh при удалённом access cookie', async ({ page, context }) => {
  await loginViaAPI(context, user);
  await deleteCookie(context, 'access');

  const refreshPromise = page.waitForResponse(r =>
    r.url().endsWith('/auth/refresh') && r.status() === 200
  );

  await page.goto('/transactions');
  const refreshResp = await refreshPromise;
  expect(refreshResp.ok()).toBe(true);

  // не редиректнуло на /login
  await expect(page).toHaveURL(/\/transactions/);
});
```

**0.1.7 Долгая сессия — НЕ ждём 16 минут:**
Используй новый endpoint `/_test/auth/issue-tokens?access_ttl_seconds=1`. Login через него, подожди 2 секунды, сделай действие — должен сработать silent refresh.

**0.1.8 Параллельные 401 → singleton refresh:**
Открой две страницы в одном `context`, синхронно через `Promise.all([page1.goto, page2.goto])`. Слушай **все** запросы на `/auth/refresh`, после 5-секундного окна — `expect(refreshCalls.length).toBe(1)`.

**0.1.10 Reuse-detection:**
Сложный сценарий с двумя контекстами. Используй `browser.newContext()` дважды. Скопируй refresh-cookie из первого во второй через `context2.addCookies([...])`. Триггерни refresh во втором. Потом во первом → должен получить 401. **Ассерт:** оба контекста после этого не могут вызвать защищённые endpoints.

**0.1.7, 0.1.10 — если test-endpoints не покрывают:**
Если выяснится, что для какого-то сценария нужно ещё что-то от backend (например, программный revoke refresh-token) — добавь endpoint в `_test/`, не хардкодь магию в spec.

**DoD фазы 2:**
- Все 12 сценариев Этапа 0.1 зелёные.
- Suite запускается за <2 минут.
- Если какой-то сценарий технически невозможен через Playwright (например, действительно требует 16-минутной паузы) — обоснуй в комментарии в spec'е и помечь `test.skip` с причиной.

---

### Фаза 3 — Upload validation (3–4 часа)

#### 3.1 Fixtures

`helpers/files.ts`:
```typescript
// Генерируется on-the-fly в global-setup или в beforeAll, складывается в .tmp/
export async function generateLargePDF(sizeMB: number): Promise<string>  // path
export async function generateLargeCSV(sizeMB: number): Promise<string>
export async function getFixturePath(name: string): Promise<string>
```

Большие файлы (>10MB) **не коммить**. Генерируй в `e2e/.tmp/` (gitignored) в `global-setup`.

Маленькие commit-able fixtures положи в `fixtures/adversarial/`:
- `empty.csv` — нулевой размер.
- `fake-extension.exe` — текстовый файл с расширением .exe (для drag-drop теста).
- `zip-bomb.xlsx` — сгенерируй через скрипт `scripts/build-zip-bomb.ts`, закоммить **результат** (~250KB).
- `cyrillic-cp1251.csv` — реальный CSV в кодировке windows-1251 с русскими описаниями.

В `fixtures/adversarial/README.md` опиши **как** каждый файл сгенерён, чтобы при проблемах его можно было пересобрать.

#### 3.2 Specs

`specs/02-upload-validation.spec.ts` — 10 сценариев Этапа 0.2.

Сценарий 0.2.7 (mismatch CSV с PDF magic) — единственный, который требует прямой fetch из браузера. Используй `page.evaluate()` для запроса вместо UI-click:
```typescript
const response = await page.evaluate(async () => {
  const blob = new Blob([new Uint8Array([0x25, 0x50, 0x44, 0x46, ...])], { type: 'text/csv' });
  const file = new File([blob], 'fake.csv', { type: 'text/csv' });
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch('/api/v1/imports/upload', {
    method: 'POST',
    credentials: 'include',
    body: fd,
  });
  return { status: r.status, body: await r.json() };
});
expect(response.status).toBe(415);
expect(response.body.code).toBe('extension_content_mismatch');
```

Сценарий 0.2.9 (curl middleware cap) — это тест бэкенд-middleware, не UI. Используй `request` context Playwright:
```typescript
const r = await api.post('/imports/upload', {
  headers: { 'Content-Length': '50000000' },
  // body не нужен — middleware режет на header'ах
});
expect(r.status()).toBe(413);
```

#### 3.3 Что важно

- Для всех «валидация без сетевого запроса» (0.2.2, 0.2.3, 0.2.4, 0.2.5) ассертить **отсутствие** запроса на `/imports/upload`. Pattern: подпиши слушатель **до** drag-drop, считай попадания, после действия `expect(uploadRequests).toHaveLength(0)`.
- Для toast-сообщений — НЕ ассертить точный текст слово-в-слово. Используй `toContainText` с ключевыми фрагментами («превышает», «лимит», «10 МБ» и т.п.) — иначе при копирайт-правке всё развалится.

**DoD фазы 3:**
- Все 10 сценариев Этапа 0.2 зелёные.
- Fixtures документированы в README.
- Generation-скрипты воспроизводимы.

---

### Фаза 4 — Rate-limit (1–2 часа)

`specs/03-rate-limit.spec.ts` — 3 сценария Этапа 0.3.

**Главное:** в `beforeEach` каждого rate-limit теста зови `resetRateLimit(api, scope, identifier)` через test endpoint. Иначе тесты заражают друг друга.

В `playwright.config.ts` — для этого spec'а форсни `workers: 1` через `test.describe.configure({ mode: 'serial' })`, иначе параллельные prod-тесты будут сжигать лимит.

**DoD фазы 4:**
- Все 3 сценария зелёные.
- Если запустить весь suite (`npm run test:smoke`) — rate-limit specs не валят соседей.

---

### Фаза 5 — Duplicate detection (2–3 часа)

`specs/05-duplicate-detection.spec.ts` — 5 сценариев Этапа 0.5.

Тут нужен **контролируемый** input: повторная загрузка того же файла должна сматчить тот же hash. Используй committed fixture `fixtures/statements-synthetic/valid-sber.csv` или подобное.

Сценарий 0.5.5 (committed duplicate) требует пройти весь flow до commit'а. Это ~10 шагов UI. Чтобы не повторять каждый раз:
- Вынеси в helper `commitImportSession(page, sessionId, options): Promise<void>`.
- Используй `test.beforeAll` для setup'а закоммиченной сессии (один раз на describe block).

Через `/_test/import-session/{id}` проверяй state в ассертах вместо парсинга UI.

**DoD фазы 5:**
- Все 5 сценариев зелёные.
- DuplicateModal helpers вынесены в `helpers/import.ts`.

---

### Фаза 6 — Bank guard (2 часа)

`specs/16-bank-guard.spec.ts` — 4 сценария Этапа 1.6.

**Ключевая идея:** не нужны выписки от unsupported-банков. Используем UPSERT-семантику `seedBank()` — переключаем существующий Сбер в `pending` на время теста, грузим обычную Сбер-выписку (она и так есть в `Bank-extracts/`), ассертим 415, в teardown возвращаем `'supported'`. Один fixture покрывает все 4 сценария 1.6.

Pattern:
```typescript
test.describe('1.6 bank guard', () => {
  let originalSberStatus: ExtractorStatus;

  test.beforeAll(async ({ request }) => {
    const sber = await seedBank(request, { name: 'Сбер', extractor_status: 'supported' });
    originalSberStatus = sber.extractor_status; // обычно 'supported'
  });

  test.afterAll(async ({ request }) => {
    // обязательно вернуть в исходное, иначе соседние spec'ы получат 415
    await seedBank(request, { name: 'Сбер', extractor_status: originalSberStatus });
  });

  test('1.6.2 загрузка выписки от unsupported банка → 415', async ({ page, request }) => {
    await seedBank(request, { name: 'Сбер', extractor_status: 'pending' });
    // upload реальной Сбер-выписки из fixtures/statements/
    // ассерт: 415, code='bank_not_supported', toast виден
  });

  // 1.6.1, 1.6.3, 1.6.4 — аналогично, через переключение статуса
});
```

**Изоляция:** этот describe должен запускаться `serial`, потому что меняет shared-state (статус банка глобален для всех юзеров). Объяви `test.describe.configure({ mode: 'serial' })` в начале файла. Если в будущем другие spec'и тоже захотят менять статус Сбера — нужно будет либо вынести bank-guard на отдельный worker, либо ввести scoped-банки (но это уже за рамками текущей задачи).

**DoD фазы 6:**
- Все 4 сценария зелёные.
- Реальные выписки Сбера берутся из `e2e/fixtures/statements/` (симлинк на `Bank-extracts/`).
- Teardown гарантированно восстанавливает Сбер в `supported` даже если тест упал (через `afterAll`, не `afterEach`, чтобы не вызывать дважды).
- Документировано в README, какие банки seed'ятся и как переключаются.

---

### Фаза 7 — Cross-cutting (3–4 часа)

`specs/cc-cross-cutting.spec.ts`:

**CC.1 happy path E2E** — большой сценарий на ~150-200 строк. Реально используй ВСЕ helpers. Это тест проверки, что suite собран правильно.

**CC.2 mobile responsive** — НЕ автоматизируем визуальную проверку. Но добавь skeleton-тест с тремя не-визуальными ассертами (console errors + horizontal scroll + touch-target). Все три бесплатные, ловят конкретные классы багов:

```typescript
test('CC.2 dashboard renders on mobile viewport (smoke)', async ({ browser }) => {
  const context = await browser.newContext({ ...devices['iPhone 14 Pro'] });
  const page = await context.newPage();
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', msg => msg.type() === 'error' && errors.push(msg.text()));

  await loginViaAPI(context, user);
  await page.goto('/dashboard');
  await page.waitForLoadState('networkidle');

  // (1) Никаких runtime errors при mount mobile viewport
  expect(errors).toEqual([]);

  // (2) Нет горизонтального скролла (+1px tolerance на subpixel rendering)
  const overflow = await page.evaluate(() =>
    document.body.scrollWidth - window.innerWidth
  );
  expect(overflow).toBeLessThanOrEqual(1);

  // (3) Touch targets ≥ 44px (Apple HIG / WCAG 2.5.5).
  // Меряем все интерактивные элементы, видимые в viewport.
  const tinyTargets = await page.evaluate(() => {
    const selectors = 'button, a, [role="button"], [role="link"], input[type="checkbox"], input[type="radio"]';
    const results: { tag: string, h: number, w: number, text: string }[] = [];
    for (const el of document.querySelectorAll<HTMLElement>(selectors)) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue; // скрытое — пропускаем
      if (r.height < 44 || r.width < 44) {
        results.push({
          tag: el.tagName,
          h: Math.round(r.height),
          w: Math.round(r.width),
          text: (el.innerText || el.getAttribute('aria-label') || '').slice(0, 40),
        });
      }
    }
    return results;
  });
  // Если будут false-positives (например, inline-иконка внутри кнопки),
  // добавь data-testid="ignore-touch-target" и фильтруй здесь.
  expect(tinyTargets, `маленькие touch targets:\n${JSON.stringify(tinyTargets, null, 2)}`).toEqual([]);

  // ВАЖНО: эти 3 ассерта НЕ заменяют визуальную приёмку.
  // Полная проверка вёрстки делается человеком, см. QA brief CC.2.
});
```

Прогони на нескольких ключевых страницах (`/dashboard`, `/transactions`, `/imports`, форма логина, форма создания транзакции). Не на всех — только там, где mobile-баги будут самым заметным регрессом.

**CC.3 expired cookies** — манипулируй cookie expires через `context.addCookies()` с `expires: 0`.

**CC.4 offline mid-action** — `await context.setOffline(true)`. Потом `setOffline(false)` для cleanup.

**DoD фазы 7:**
- CC.1, CC.3, CC.4 зелёные.
- CC.2 skeleton зелёный, в комментариях ссылка на ручную приёмку.

---

### Фаза 8 — Cleanup, README, финальный прогон (1–2 часа)

1. `e2e/README.md` — полный гайд:
   - Предусловия (docker, .env).
   - Команды.
   - Как добавить новый сценарий.
   - Как смотреть failure traces.
   - Как обновлять/добавлять fixtures.
2. `docs/E2E_KNOWN_ISSUES.md` — сюда складывай баги, которые suite нашёл по ходу. **Не фикси их**, только репорт.
3. Прогони `npm run test:smoke` 3 раза подряд. Все должны быть зелёные. Засеки время.
4. Проверь `--repeat-each=3` на Auth и Rate-limit suite — они часто flaky первыми.
5. Финальный отчёт Григорию:
   - Сколько сценариев автоматизировано / skipped / на ручную приёмку.
   - Время прогона полного suite.
   - Список найденных багов из `E2E_KNOWN_ISSUES.md`.
   - Recommendations: что улучшить в основном коде, чтобы тесты были стабильнее (например, добавить `data-testid` где их нет).

**DoD фазы 8:**
- README исчерпывающий.
- Suite за один прогон проходит за ≤ 5 минут.
- Suite проходит зелёным 3 раза подряд без вмешательства.

---

## 5. Backend test endpoints (новые, обязательные)

См. подробности в фазе 1. Сводный список:

| Endpoint | Метод | Назначение |
|---|---|---|
| `/_test/seed/user` | POST | Создать/получить тестового юзера (idempotent по email) |
| `/_test/seed/account` | POST | Создать тестовый счёт |
| `/_test/seed/bank` | POST | UPSERT банка по `name`: создать или обновить `extractor_status` |
| `/_test/cleanup/user` | POST | Каскадно удалить юзера и его данные |
| `/_test/reset/rate-limit` | POST | Сбросить ключ в Redis |
| `/_test/auth/issue-tokens` | POST | Выдать токены с кастомным TTL |
| `/_test/import-session/{id}` | GET | Прочитать state сессии импорта |

### 5.1 Защита: флаг `ENABLE_TEST_ENDPOINTS`

**Привязка к `settings.environment` отвергнута** — `environment` используется для других решений (логи, Sentry, CORS), и его кто-то может случайно ослабить. Стоимость утечки seed-эндпоинтов в прод катастрофическая (любой создаёт юзеров, читает чужие import-сессии). Поэтому отдельный флаг.

**Контракт:**

- В `app/core/config.py` (`Settings`):
  ```python
  enable_test_endpoints: bool = False
  ```
  Дефолт `False`. Читается из env-var `ENABLE_TEST_ENDPOINTS` (pydantic-settings).
- В `.env.example`: `ENABLE_TEST_ENDPOINTS=false` (явный дефолт, чтобы видно было в шаблоне).
- В `.env` для локальной разработки и в env CI: `ENABLE_TEST_ENDPOINTS=true`.
- В прод-окружении (Yandex Cloud / любой другой деплой) — переменная отсутствует или явно `false`. Никаких других кейсов.

### 5.2 Три слоя защиты (defence in depth)

```python
# Слой 1 — app/api/v1/__init__.py: router регистрируется по флагу
from app.core.config import settings
from app.api.v1 import test_utils

if settings.enable_test_endpoints:
    app.include_router(test_utils.router, prefix='/api/v1/_test', tags=['_test'])
```

```python
# Слой 2 — внутри test_utils.py: каждая функция роута проверяет флаг
# (на случай если кто-то случайно include_router'нет в обход проверки)
from fastapi import APIRouter, HTTPException, Depends
from app.core.config import settings

router = APIRouter()

def require_test_endpoints_enabled():
    if not settings.enable_test_endpoints:
        # 404, не 403 — endpoint должен быть невидим
        raise HTTPException(status_code=404)

@router.post('/seed/user', dependencies=[Depends(require_test_endpoints_enabled)])
def seed_user(...):
    ...
```

```python
# Слой 3 — tests/test_test_utils.py: юнит-ассерт что при флаге=False всё 404
def test_endpoints_return_404_when_flag_false(monkeypatch):
    monkeypatch.setattr(settings, 'enable_test_endpoints', False)
    client = TestClient(create_app())  # app собирается с учётом флага
    for path in ['/api/v1/_test/seed/user', '/api/v1/_test/seed/bank', ...]:
        response = client.post(path, json={})
        assert response.status_code == 404, f'{path} leaked: {response.status_code}'

def test_endpoints_work_when_flag_true(monkeypatch):
    monkeypatch.setattr(settings, 'enable_test_endpoints', True)
    # ассертим 200/4xx (не 404) на каждом endpoint'е с валидным телом
```

Слои 1 и 2 защищают от **разных** ошибок: слой 1 от случайного misconfig в проде (флаг True), слой 2 от случайного `include_router` в обход флага. Не убирай ни один как «избыточный».

### 5.3 Дополнительные правила

- В логах при старте приложения, если `enable_test_endpoints=True`, **печатать предупреждение** уровня WARNING: `"⚠ TEST ENDPOINTS ENABLED — must be False in production"`. Это страховка от того, что флаг забыли выключить при выкладке.
- В `app/main.py` после старта — если `settings.environment == 'production'` И `settings.enable_test_endpoints == True`, **abort startup** с понятным сообщением. Это последний рубеж: если кто-то случайно выставил оба — приложение не запустится в проде вообще.

---

## 6. Конвенции

### 6.1 Naming
- Spec-файлы: `NN-feature-name.spec.ts`, NN — соответствует этапу из QA brief.
- Тесты внутри: `test('0.1.4 silent refresh при удалённом access cookie', ...)` — номер сценария префиксом, чтобы можно было быстро смапить с QA brief.
- Helpers: `verbNoun.ts` (`auth.ts`, `seed.ts`).

### 6.2 Селекторы
**Жёсткое правило:** в spec'ах используй ТОЛЬКО `data-testid` или `getByRole(name)`. Никаких `.css-класс`, никаких xpath по индексу.

Если для какого-то нужного элемента в `frontend/` нет `data-testid` — добавь его в frontend код (это допустимый кросс-репо change). Соберите такие места в `helpers/selectors.ts` как константы:
```typescript
export const SEL = {
  loginEmail: '[data-testid="login-email-input"]',
  loginSubmit: '[data-testid="login-submit"]',
  toastError: '[data-testid="toast-error"]',
  duplicateModal: '[data-testid="duplicate-modal"]',
  // ...
} as const;
```

При добавлении testid в frontend — придерживайся convention `kebab-case`, понятные имена, не привязанные к стилю (`primary-button` плохо, `confirm-import-button` хорошо).

### 6.3 Изоляция тестов
- **Каждый тест создаёт своего юзера** через `seedUser()` с уникальным email (`test-${Date.now()}-${Math.random()}@local.test`).
- В `afterEach` или `afterAll` — `cleanupUser()`.
- Не share state между тестами иначе как через `test.describe.serial` + `beforeAll`.

### 6.4 Network-ассерты
Универсальный pattern:
```typescript
const networkLog = startNetworkLog(page);  // helpers/network.ts
await action();
expect(networkLog.calls('POST', '/imports/upload')).toHaveLength(0);
const refresh = networkLog.calls('POST', '/auth/refresh');
expect(refresh).toHaveLength(1);
expect(refresh[0].response.status()).toBe(200);
```

### 6.5 Что НЕ делать
- Не используй `page.waitForTimeout(N)` иначе как с явным комментарием почему. Всегда предпочитай `waitForRequest`/`waitForResponse`/`waitForSelector`/`waitForURL`.
- Не trust toast-success без проверки Network. Дублируй ассерты: «toast виден» + «backend вернул 200».
- Не лезь напрямую в Postgres из тестов (`pg`-клиент допустим только в `helpers/seed.ts` если test-endpoint не подходит, и только в крайних случаях). Все mutations — через test-endpoints.

---

## 7. Запуск и отчёты

```bash
# Предусловие: docker compose up -d --build (в корне репо)
cd e2e
cp .env.example .env  # один раз
npm install            # один раз
npx playwright install chromium  # один раз

# Прогон всего suite
npm run test:smoke

# Один файл
npx playwright test specs/01-auth-refresh.spec.ts

# Один тест по grep
npx playwright test -g "0.1.4"

# Headed (видишь браузер)
npm run test:smoke:headed

# UI mode (интерактивный отладчик)
npm run test:smoke:ui

# После failure — открыть HTML report с traces
npm run test:smoke:report
```

При падении — Playwright сохранит trace, video, screenshot в `reports/`. Trace открывается через `npx playwright show-trace reports/trace.zip` и показывает покадрово что происходило в браузере + Network/Console.

---

## 8. Принятые решения (2026-05-04)

Все 6 открытых вопросов закрыты. Стартуй с Фазы 0 без дополнительных уточнений, кроме одной точечной справки в начале Фазы 3 (см. п. 8.1).

### 8.1 Реальные выписки → `Bank-extracts/`

Anonymized выписки лежат в `Bank-extracts/` в корне репо. Подключение — через симлинк `e2e/fixtures/statements → ../../Bank-extracts/` (см. §3.1).

**Точечная справка в начале Фазы 3:** список доступных выписок и их назначения (какой банк, какой период, какой формат) Claude Code узнаёт у Григория одним коротким вопросом — не угадывает имена файлов и не парсит каталог самостоятельно.

### 8.2 Выписка unsupported-банка не нужна

Тест 1.6.2 решается через UPSERT-семантику `seedBank()`: переключаем существующий Сбер в `pending`, грузим обычную Сбер-выписку (она уже есть в `Bank-extracts/`), ассертим 415, в teardown возвращаем `'supported'`. Один fixture покрывает все 4 сценария 1.6, ноль зависимостей от файлов unsupported-банков. Реализация — Фаза 6.

### 8.3 CI откладываем отдельной фазой после suite'а

Подтверждено. Spec'и пишутся **сразу CI-ready**: никаких manual prereq, всё через env, идемпотентность, никаких локальных абсолютных путей. Тогда подключение CI после = одна задача на полдня. Делать одновременно — потерять неделю на дебаг runner'а вместо тестов.

### 8.4 CC.2 mobile — три не-визуальных ассерта (skeleton)

OK на skeleton-тест без визуальной приёмки. Дополнительно включены два недорогих non-visual ассерта (см. Фаза 7 CC.2):

- (a) нет горизонтального скролла: `document.body.scrollWidth - window.innerWidth ≤ 1`;
- (b) все кликабельные элементы имеют `width ≥ 44 && height ≥ 44` (Apple HIG / WCAG 2.5.5).

Это ловит конкретные классы багов («mobile viewport крашит», «overflow рвёт layout», «touch target меньше пальца»), но НЕ заменяет визуальную приёмку. Полная mobile-проверка остаётся ручной.

### 8.5 Test endpoints — отдельный флаг `ENABLE_TEST_ENDPOINTS`

**§5 переписан целиком.** Привязка к `settings.environment` отвергнута (хрупко: environment используется для логов/Sentry/CORS и может быть случайно ослаблен). Введён отдельный флаг `enable_test_endpoints: bool = False` в `Settings`, с тремя слоями защиты — детали в §5.1–5.3.

### 8.6 Очерёдность — 0→8 по порядку

Closed-test целевая дата: ~2026-05-18…25 (≥ 2 недели от старта). Времени достаточно, идём строго по фазам без двухэтапного merge. Rate-limit (Фаза 4) делается в общей очереди, не откладывается.

Если по ходу обнаружится, что дедлайн closed-test сдвинется ближе и нужен двухэтапный merge — Claude Code должен **остановиться и спросить Григория**, не переупорядочивать фазы самостоятельно.

### 8.7 Архивные открытые вопросы (для исторической справки)

<details>
<summary>Раскрыть исходные 6 вопросов в той форме, в какой они были до 2026-05-04</summary>

1. **Тестовые выписки.** Есть ли у тебя anonymized PDF/CSV/XLSX выписок Сбера, Тинькофф, Озон, Яндекса для fixtures? Если да — куда их положить? Если нет — нужны ли такие реалистичные выписки или достаточно синтетических CSV с минимальной структурой?
2. **Выписка от unsupported банка** для сценария 1.6.2. Есть ли у тебя выписка «Точки» или другого банка со статусом `pending`? Если нет — генерируем синтетический PDF с правильным contract_number?
3. **CI integration.** В этой задаче CI не делаем. Подтверди, что это ОК и мы вернёмся к GitHub Actions / GitLab CI отдельной фазой после.
4. **Ручная приёмка mobile (CC.2).** Согласен, что полную визуальную проверку оставляем тебе/QA, а в suite — только smoke-тест на console errors?
5. **Test endpoints в продакшне.** Подтверди что `settings.environment` в проде гарантированно `production`. Если нет — добавим дополнительный feature flag `ENABLE_TEST_ENDPOINTS` в env.
6. **Очерёдность фаз.** Если что-то блокирует closed-test (например, нужны прямо сейчас только Auth + Upload), скажи — я переставлю приоритеты, остальное сделаю отдельным заходом.

</details>

---

## 9. Исходный QA brief

Полные 38 сценариев со всеми шагами, ожиданиями, severity и форматом баг-репорта — в чат-логе Cowork-сессии Григория от 2026-05-04 (тема «ТЗ для Claude в Computer Use mode»).

Если этот файл не приложен к твоей сессии — попроси Григория переслать. Без него ты не сможешь корректно реализовать spec'и: каждый тест должен ссылаться на номер сценария из brief'а, и ассерты должны точно соответствовать «Ожидаемое».

---

## 10. Финальная приёмка от Григория

После фазы 8 покажи:
1. `cd e2e && npm run test:smoke` → всё зелёное, время прогона.
2. `npm run test:smoke:report` → HTML-отчёт открывается, видны passed/failed по сценариям.
3. `docs/E2E_KNOWN_ISSUES.md` → список багов, которые suite нашёл (с severity и шагами воспроизведения в формате из QA brief).
4. Запусти suite ещё раз с `--repeat-each=3` — flakiness должна быть 0.
5. Краткий summary Григорию: «Из 38 сценариев — N автоматизированы, M skipped с причинами, 1 (CC.2) на ручной приёмке. Время прогона: X минут. Найдено K багов разной severity».

---

**Финальная нота.** Если по ходу обнаружишь, что какое-то требование из ТЗ невыполнимо или сильно усложняет жизнь — **остановись и скажи Григорию**, не делай молча workaround. Это инфраструктура надолго, важно сделать правильно с первого раза, чем дешёво и потом переписывать.
