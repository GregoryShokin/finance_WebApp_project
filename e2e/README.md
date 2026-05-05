# FinanceApp E2E smoke suite

Regression smoke for FinanceApp MVP. Built on Playwright + TypeScript.
Covers 37 of 38 closed-test scenarios from the QA brief — full
specification, phased plan, and decisions log live in
`../E2E_SMOKE_TZ.md`.

> **Status:** all 8 phases complete. 43 tests, ~17 s per run, zero
> flakiness across 5 consecutive runs and `--repeat-each=3` (129/129).

## What's covered

| Stage | File | Tests |
|-------|------|------:|
| Bootstrap | `specs/00-smoke.spec.ts` | 2 |
| 0.1 — auth + refresh-token | `specs/01-auth-refresh.spec.ts` | 12 |
| 0.2 — upload validation | `specs/02-upload-validation.spec.ts` | 10 |
| 0.3 — rate limits | `specs/03-rate-limit.spec.ts` | 3 |
| 0.5 — duplicate detection | `specs/05-duplicate-detection.spec.ts` | 5 |
| 1.6 — bank guard | `specs/16-bank-guard.spec.ts` | 4 |
| Cross-cutting | `specs/cc-cross-cutting.spec.ts` | 7 (CC.1, CC.2×4, CC.3, CC.4) |
| **Total** | | **43** |

CC.2 mobile is a SMOKE-level check (console errors + horizontal overflow
+ soft touch-target audit) — full visual review of mobile layouts stays
manual. See `../docs/E2E_KNOWN_ISSUES.md` for KI-02.

## Prerequisites

- **Backend stack** running locally: `docker compose up --build` from
  the repo root. Required services: `api` (8000), `db` (5433),
  `redis` (6379).
- **Frontend** dev server: `cd frontend && npm run dev` in another
  terminal. Default port 3000.
- **`ENABLE_TEST_ENDPOINTS=true`** in the repo-root `.env`. The suite
  cannot run without `/api/v1/_test/*` endpoints; the flag is defaulted
  to `false` and main.py refuses to boot if it's `true` while
  `APP_ENV=production`. After flipping it, restart the api container.
- **`Bank-extracts/` symlink**: the suite consumes real anonymized
  statements via `e2e/fixtures/statements/` → `../../Bank-extracts/`.
  See "Real bank statements" below.
- Node.js 20+ and npm 10+ on the host.
- macOS / Linux. Windows is not supported.

## First-time setup

```bash
cd e2e
cp .env.example .env             # adjust ports if your local stack differs
npm install
npm run install:browsers          # downloads chromium only (~165 MiB)
ln -s ../../Bank-extracts fixtures/statements   # one-shot symlink
```

In the repo-root `.env`:

```bash
ENABLE_TEST_ENDPOINTS=true
```

Then `docker compose restart api`.

## Run

```bash
# Full suite, headless
npm run test:smoke

# Headed (browser visible) — useful when authoring new specs
npm run test:smoke:headed

# Interactive UI mode — best for debugging a single failing test
npm run test:smoke:ui

# Open last HTML report
npm run test:smoke:report

# A single spec
npx playwright test specs/00-smoke.spec.ts

# A single test by name
npx playwright test -g "0.1.4"

# Stress / flake hunt: every test 3× in one go
npx playwright test --repeat-each=3
```

A clean run completes in ~17 s on a laptop with workers=1; the stress
mode runs ~1.5 min for 129 invocations.

## Failure investigation

Playwright records a trace, video, screenshot, and network log for
every failure into `reports/`. Replay with the trace viewer (much
faster than re-running headed):

```bash
npx playwright show-trace test-results/<test-folder>/trace.zip
```

The viewer shows actions frame-by-frame, plus the timeline of network
requests and console output.

## Layout

```
e2e/
├── specs/                     # one file per QA-brief stage
│   ├── 00-smoke.spec.ts
│   ├── 01-auth-refresh.spec.ts          (12 tests)
│   ├── 02-upload-validation.spec.ts     (10 tests)
│   ├── 03-rate-limit.spec.ts            (3 tests, serial)
│   ├── 05-duplicate-detection.spec.ts   (5 tests)
│   ├── 16-bank-guard.spec.ts            (4 tests, serial)
│   └── cc-cross-cutting.spec.ts         (7 tests)
├── helpers/                   # shared utilities, no Page Object Model
│   ├── api.ts                 # APIRequestContext factory + assertOk
│   ├── auth.ts                # loginViaUI, loginViaAPI, getAuthCookies, deleteAuthCookie
│   ├── files.ts               # path resolvers + on-the-fly large-file generators
│   ├── network.ts             # startNetworkLog
│   ├── seed.ts                # seedUser/Bank/Account, cleanupUser, issueTokens, etc.
│   ├── selectors.ts           # data-testid constants (SEL.*)
│   ├── types.ts               # TestUser, ExtractorStatus, ImportSessionState
│   └── upload.ts              # uploadFile, uploadBuffer
├── fixtures/
│   ├── statements/            # symlink → ../../Bank-extracts (gitignored)
│   ├── statements-synthetic/  # tiny-valid.xlsx (committed)
│   └── adversarial/           # empty.csv, fake-extension.exe, cyrillic-cp1251.csv,
│                              # zip-bomb.xlsx, README.md
├── scripts/
│   ├── build_zip_bomb.py      # → fixtures/adversarial/zip-bomb.xlsx
│   └── build_minimal_xlsx.py  # → fixtures/statements-synthetic/tiny-valid.xlsx
├── reports/                   # HTML report (gitignored)
├── test-results/              # trace.zip + videos for failures (gitignored)
├── .tmp/                      # generated large files (gitignored)
├── playwright.config.ts
├── global-setup.ts            # health-checks API + frontend before any test runs
└── .env / .env.example
```

## Real bank statements

Anonymized statements live in `Bank-extracts/` at the repo root
(gitignored). The suite consumes them via a symlink:

```bash
ln -s ../../Bank-extracts fixtures/statements
ls -la fixtures/statements   # verify
```

Tests reference files as `fixtures/statements/<filename>.pdf`. NEVER
hardcode absolute paths.

Currently used by tests:

- `Сбер дебет.pdf` — happy-path PDF upload (0.2.1, 0.5.x, CC.1).
- `Т банк дебет.pdf` — bank-guard tests (1.6.x). The Т-Банк PDF
  surfaces both `contract_number=5452737298` and a
  `statement_account_number`, which are needed for the auto-match
  that triggers the `extractor_status` guard.

If a new test needs a PDF that surfaces a contract or
statement-account, probe candidates with curl + the upload endpoint
before committing the spec.

Synthetic fixtures (`fixtures/statements-synthetic/`) are committed
and used when a test needs deterministic input that doesn't depend
on a real statement.

## Adversarial fixtures

Committed under `fixtures/adversarial/`. Each file's role is
documented in `fixtures/adversarial/README.md`:

| File | Tests | Purpose |
|------|-------|---------|
| `empty.csv` | 0.2.4 | zero-byte → 415 `empty_file` |
| `fake-extension.exe` | 0.2.3 | binary content + `.exe` extension → 415 `unsupported_upload_type` |
| `cyrillic-cp1251.csv` | 0.2.10 | CP1251-encoded Russian CSV passes validator |
| `zip-bomb.xlsx` | 0.2.8 | 200 MB decompressed in 205 KB → 415 `xlsx_decompression_too_large` |

Re-generate with the scripts in `scripts/` if the validator changes.

## Adding a new spec

1. Pick the right file based on QA brief stage (one file per stage).
2. Test name format: `'0.X.N короткое описание на русском'` — start
   with the brief's scenario number so a failure can be cross-
   referenced to the QA document instantly.
3. Use the helpers in `helpers/` rather than inlining setup. If a
   helper doesn't exist, add it.
4. Selectors: `data-testid` (constants in `helpers/selectors.ts`) or
   `getByRole(name)` only. No CSS classes, no xpath-by-index. Add
   `data-testid` to the frontend code if it's missing — kebab-case,
   semantic (`confirm-import-button`, not `primary-button`).
5. Each test must clean up after itself. Generate emails via
   `uniqueEmail()` (uses `@e2e-local.fake` — see "Why .fake" below)
   and call `cleanupUser(api, user.email)` at the end.

### Why `.fake` and not `.test`

`uniqueEmail()` produces `e2e-<ts>-<rand>@e2e-local.fake`. Pydantic's
`EmailStr` (used by the production auth schemas in
`app/schemas/auth.py`) rejects IANA reserved TLDs like `.test`,
`.example`, `.invalid`, `.localhost`. Seeding a user with such an
email would succeed (the seed endpoint uses a relaxed `str` field),
but the production `/auth/login` route would later return 422. The
`.fake` TLD is not on the reserved list and avoids this trap without
weakening production validation.

### Selector / API gotchas

These are the non-obvious decisions baked into helpers — they will
trip up future readers if they go looking from scratch:

- **Tokens are JS-readable cookies**, not HttpOnly. The SPA needs to
  read the access token to attach `Authorization: Bearer …`. Do not
  write asserts on `httpOnly: true` — they will always fail.
- **`APIRequestContext.baseURL` needs a trailing slash.** Helpers
  pass paths like `_test/seed/user` (no leading slash). Adding `/_test/...`
  drops `/api/v1/` from the resolved URL — verified by global-setup.
- **Slowapi keys in Redis** look like `LIMITS:LIMITER/<key>/<route>/<rate>/<window>/<unit>`.
  The `resetRateLimit` helper maps scope → route fragment via a
  dictionary — the scope name doesn't appear verbatim in the key.
- **Bank-guard auto-match requires PDF metadata.** The guard fires
  only when the upload's recognition surfaces a `contract_number` or
  `statement_account_number` AND the user has an account that
  matches it. Most anonymized PDFs in `Bank-extracts/` strip both —
  Т-Банк дебет is the one known-working fixture today.

## Idempotency

Running the suite multiple times in a row must produce identical
results. Flakiness usually traces to one of:

- Missing cleanup (test data persists across runs).
- Shared state between tests (e.g. bank `extractor_status` left
  flipped). 1.6 has explicit afterAll restoration; 03-rate-limit
  uses `mode: 'serial'` plus blanket scope resets in `beforeEach`.
- Rate-limit buckets bleeding into the next run. `beforeEach` in
  every spec resets the relevant scopes.
- JWT exp / wall-clock races: the suite's TTL-based tests use a
  2.5 s sleep on a 1 s TTL to absorb up to 1 s of Docker↔host clock
  drift.

`--repeat-each=3` should pass for any green local suite — if it
flakes, fix the underlying race rather than adding retries.

## Workers and parallelism

`workers: 1` enforced project-wide. Two workers cause cross-file
race conditions on the global rate-limit Redis buckets that every
spec resets in `beforeEach` — single-worker serialisation is the
trade for predictable rate-limit semantics.

CI: keep `workers: 1` and bump `retries: 1` if you want belt-and-
braces against transient infrastructure issues.

## Known issues

`docs/E2E_KNOWN_ISSUES.md` tracks behavioural deviations between the
QA brief and the suite's reality. Today:

- **KI-01** — frontend lacks pre-upload validation. The 0.2 specs
  test the backend rejection path; if the frontend gains
  client-side validation later, amend the specs to also assert "no
  network request fired".
- **KI-02** — mobile touch-target audit deferred. CC.2's third
  assert is soft; violations are reported via test annotations
  rather than blocking the suite.
