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

# Create new migration
alembic revision --autogenerate -m "description"

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

PostgreSQL with Alembic migrations in `alembic/versions/` (sequential numbering `0001_`…). Core models: `User`, `Account`, `Category`, `Transaction`, `Counterparty`, `ImportSession`, `ImportRow`, `TransactionCategoryRule`.

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
