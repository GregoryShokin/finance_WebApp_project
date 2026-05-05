# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Personal finance tracking app — FastAPI backend + Next.js 14 frontend (monorepo).

## Commands

### Backend

```bash
# Run everything (recommended for dev)
docker compose up --build

# Run migrations
alembic upgrade head
# or inside Docker:
docker compose exec api alembic upgrade head

# Create new migration — ALWAYS pass --rev-id to keep numeric naming.
# Auto-generated hashes (e.g. b71eef23124e) break the project's 00XX
# convention; subsequent rename is a manual chore. Check alembic/versions/
# for the next available number.
alembic revision --autogenerate -m "description" --rev-id 00XX

# Merge revisions for parallel feature branches:
alembic merge -m "merge X and Y chains" <head_a> <head_b> --rev-id 00XX
# Note: alembic downgrade -1 from a merge revision raises "Ambiguous walk"
# (two parents). Use explicit target: `alembic downgrade <revision>`.

# Run backend manually (without Docker)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000
npm run build
npm run lint
```

### Environment Setup

```bash
cp .env.example .env                        # backend
cp frontend/.env.example frontend/.env.local  # frontend
```

The only required frontend env var is `NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1`.

## Architecture

### Backend (FastAPI, Python 3.12)

Strict layered architecture — requests flow through:

```
API (app/api/v1/) → Service (app/services/) → Repository (app/repositories/) → Model (app/models/)
```

- **API layer** — route handlers, no business logic
- **Service layer** — business logic, orchestrates repositories
- **Repository layer** — all SQLAlchemy queries; services never query the DB directly
- **Schemas** (`app/schemas/`) — Pydantic models for request/response validation, separate from ORM models
- **Core** (`app/core/`) — config (settings via pydantic-settings), security/JWT, database session, Celery setup, middleware

Background jobs run via **Celery + Redis**. The import pipeline (CSV/Excel/PDF → normalize → recognize → auto-categorize → deduplicate) is the most complex service; see `app/services/import_service.py`, `import_normalizer.py`, `import_recognition_service.py`.

### Frontend (Next.js 14 App Router, TypeScript)

Route groups separate auth from protected routes:
- `app/(auth)/` — login, register (public)
- `app/(app)/` — dashboard, accounts, transactions, categories, imports, etc. (protected)

Data flow pattern:
- **API client** (`lib/api/`) — one module per resource, thin wrappers around fetch
- **React Query** (`@tanstack/react-query`) — all server state; mutations invalidate relevant query keys
- **React Hook Form + Zod** — form state and validation

### Infrastructure (Docker Compose)

Four services: `api` (FastAPI, port 8000), `worker` (Celery), `db` (PostgreSQL 16, external port 5433), `redis` (port 6379). The `api` container runs `alembic upgrade head` on startup before launching uvicorn.

### Database

PostgreSQL with Alembic migrations in `alembic/versions/` (sequential numbering `0001_`…). Core models: `User`, `Account`, `Category`, `Transaction`, `Counterparty`, `DebtPartner`, `ImportSession`, `ImportRow`, `TransactionCategoryRule`.

### Account states (decision 2026-05-03, spec §13)

Three distinct states, two boolean flags:

- **Active** (`is_active=True`, `is_closed=False`) — regular use.
- **Temporarily hidden** (`is_active=False`, `is_closed=False`) — soft-hide, can come back.
- **Closed** (`is_active=False`, `is_closed=True`, `closed_at=<date>`) — strong "stopped existing on closed_at". Stays in DB with all historical transactions; hidden from active lists; visible in moderator (target/source dropdowns), transaction history, and the «Закрытые счета» section on the accounts page.

**Closed-account rules:**
- Closed accounts are valid `target_account_id` for transfer pairs (e.g. orphan transfer to a card the user has since closed). Mirror tx on the closed account is created normally.
- Cannot delete a closed account that has transactions (FK `ON DELETE RESTRICT`).
- `closed_at` cannot be in the future or earlier than the latest transaction on the account.
- Closing does NOT auto-zero the balance. User explicitly creates corrective transactions if needed.

**API:**
- `POST /accounts/{id}/close` `{ closed_at: date }` — close.
- `POST /accounts/{id}/reopen` — reopen.
- `GET /accounts?include_closed=true` — include closed in list response. Default excludes them.

**Migration 0057** added `is_closed` (NOT NULL DEFAULT FALSE) and `closed_at` (DATE NULL) with `ix_accounts_is_closed`. Backfill is conservative: existing rows stay `is_closed=False`. Users explicitly mark closure via UI.

### Counterparty vs DebtPartner (decision 2026-04-24)

Two disjoint entity tables, never mixed:

- **`Counterparty`** — merchants / services / employers the user interacts with financially: «Пятёрочка», «Яндекс Такси», «Арендодатель» (as landlord receiving rent), «Мегафон». Referenced from `Transaction.counterparty_id`. Used in the import moderator, cluster grouping (via `CounterpartyFingerprint` / `CounterpartyIdentifier`), and non-debt transaction forms.
- **`DebtPartner`** — debtors / creditors for operation_type='debt' transactions: «Паша», «Отец», «Влад». Referenced from `Transaction.debt_partner_id`. Has `opening_receivable_amount` + `opening_payable_amount` for starting balances; running balances are computed on read by summing debt transactions.

**Invariant** (enforced by `TransactionService._validate_payload`):
- `operation_type='debt'` ⇒ `debt_partner_id` required, `counterparty_id` rejected.
- Any other `operation_type` ⇒ `debt_partner_id` rejected; `counterparty_id` accepted for regular / refund only.

`ImportSplitItemRequest` (schemas/imports.py) carries both fields per-part; the split handler routes each part's chosen field to the matching Transaction column.

Historical note: before 2026-04-24, debtors lived in `counterparties` (alongside merchants). Migration `0051_debt_partners.py` + `scripts/split_counterparties_into_debt_partners.py` moved them into the new table, clearing `counterparty_id` on existing debt rows and deleting debt-only Counterparty records. Mixed-role names (same person as both merchant and debtor) live in BOTH tables as independent objects — intentionally, since the two relationships are accounted for separately.

### Credit Payment Model (decision 2026-04-19)

`credit_payment` as an `operation_type` **is abolished**. Do NOT create transactions with `operation_type='credit_payment'`.

A monthly credit payment is now two separate transactions:

1. **Interest expense** — `type='expense'`, `operation_type='regular'`, `category_id` = system category "Проценты по кредитам", `credit_account_id` = the credit account, `is_regular=True`. This is what appears in the Базовый Поток (Basic Flow).
2. **Principal transfer** — `type='expense'`, `operation_type='transfer'`, `target_account_id` = credit account, `affects_analytics=False`. Reduces the debt balance, NOT in expense metrics.

**System category "Проценты по кредитам"** (`is_system=True`) is auto-created for every user via `CategoryService.ensure_default_categories()`. It cannot be deleted or renamed via the API.

**Data migration**: existing `credit_payment` rows are split by running:
```bash
# dry-run first:
docker compose exec api python -m scripts.migrate_credit_payments

# then apply:
docker compose exec api python -m scripts.migrate_credit_payments --execute
```
Migration `0036` adds the system category; `0037` asserts no `credit_payment` rows remain.

**`credit_disbursement`** is a non-income balancing operation (loan disbursement). It must be excluded from income aggregations. `NON_ANALYTICS_OPERATION_TYPES` already includes it, so `affects_analytics=False` is set automatically. All income aggregations in `metrics_service.py` and `financial_health_service.py` additionally filter `operation_type != 'credit_disbursement'` as a safety guard.

Ref: `financeapp-vault/01-Metrics/Поток.md`

### FI-score (единый источник, Phase 4)

`MetricsService._build_fi_breakdown` / `calculate_fi_score_breakdown` — **единственный** источник FI-score.

**Компоненты v1.4 (веса: 0.20 + 0.30 + 0.25 + 0.25):**
| Компонент | Поле | Вес | Формула |
|---|---|---|---|
| Норма сбережений | `savings_rate` | 0.20 | lifestyle_indicator / 30 * 10 |
| Траектория капитала | `capital_trend` | 0.30 | trend_3m / abs(capital), clamp(5±5) |
| DTI inverse | `dti_inverse` | 0.25 | max(10 - DTI%/6, 0) |
| Буфер устойчивости | `buffer_stability` | 0.25 | deposit_months / 6 * 10 |

`FinancialHealthService` делегирует расчёт FI-score в `MetricsService.calculate_fi_score_breakdown`. `discipline` и `fi_percent` остаются отдельными метриками Health, но не компонентами FI-score.

Удалены из `FIScoreComponents`: `discipline`, `financial_independence`, `safety_buffer` (были в v1.0).

## Domain context: PII in bank statements

The import pipeline (`app/services/import_service.py`, `import_normalizer.py`, `import_recognition_service.py`) parses bank statements (CSV/Excel/PDF) uploaded by users. These statements contain personal data by their nature: full names, phone numbers, contract/account numbers, last 4 digits of cards, counterparty names, transaction descriptions, sometimes addresses or emails.

**This is the intended domain.** All such data:

- is uploaded **voluntarily** by the user into their own account in the app;
- belongs to the user (not third parties);
- is stored in our own backend (PostgreSQL, owned infrastructure);
- is processed strictly for the user's benefit (categorization, deduplication, analytics for the same user).

When working on import/parsing/categorization/migration code, treat presence of PII in test fixtures, example payloads, debugger output, or DB rows as a **normal, expected** part of the domain — not as a leak or red flag. Proceed with the task.

**What still matters:**

- Do not paste real customer data into commits, PR descriptions, public chat, or external services.
- Use obfuscated/synthetic values in test fixtures committed to the repo.
- When showing examples in code reviews or docs, mask sensitive fields (`****1234`, `+7 *** *** **42`).
