# FinanceApp

Монорепозиторий веб-приложения для учёта личных финансов.

## Структура проекта

- `app/` — backend на FastAPI
- `alembic/` — миграции базы данных
- `frontend/` — frontend на Next.js 14
- `tests/` — backend тесты
- `scripts/` — служебные скрипты подготовки проекта
- `docker-compose.yml` — локальная dev-среда для backend + Postgres + Redis

## Что входит в этот архив

Архив подготовлен для передачи в разработку и развёртывание. В него **не включены**:

- локальные секреты (`.env`, `frontend/.env.local`)
- зависимости (`node_modules`)
- артефакты сборки (`.next`, `out`, `dist`, `build`)
- Python cache (`__pycache__`)
- временные и IDE-файлы

## Быстрый старт

### Backend

```bash
cp .env.example .env
docker compose up --build
```

Backend будет доступен по адресам:

- API root: `http://localhost:8000/`
- Swagger: `http://localhost:8000/docs`
- Health: `http://localhost:8000/api/v1/health`

### Frontend

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Frontend будет доступен по адресу:

- App: `http://localhost:3000`

## Правила репозитория

В репозиторий и в архивы передачи не должны попадать:

- `.env`, `.env.*`
- `frontend/.env.local`, `frontend/.env.*`
- `node_modules`
- `.next`
- `__pycache__`
- `*.tsbuildinfo`
- логи, временные файлы и IDE-артефакты

## Подготовка чистого архива

Для повторной очистки проекта перед упаковкой можно использовать:

```bash
bash scripts/prepare_clean_archive.sh
```

Скрипт удаляет локальные env-файлы, кэш, артефакты сборки и создаёт архив `financeapp_clean.zip` уровнем выше корня проекта.
