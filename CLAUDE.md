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
