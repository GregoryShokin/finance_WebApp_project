# Стек MOC
#стек
> Технический стек проекта.
---
## Backend
- FastAPI + SQLAlchemy + PostgreSQL + Redis + Celery + Alembic
- Docker Compose (api, worker, db, redis, bot)
- JWT (python-jose, passlib): access ~15 мин + refresh ~30 дн с rotation и reuse-detection. Refresh-токены хранятся в БД (`refresh_tokens`, sha256-хеш + jti); фронт держит обе токена в js-cookie (refresh — `SameSite=Strict`). Cleanup протухших — Celery beat ежедневно 04:30 UTC (`prune_refresh_tokens`)
- openpyxl, pypdf — импорт данных
- python-telegram-bot — Telegram бот

## Frontend
- Next.js 14 + TypeScript + Tailwind CSS
- @tanstack/react-query — кэширование
- Recharts — графики
- lucide-react — иконки
- sonner — toast-уведомления

## Архитектура бэкенда
```
API (app/api/v1/) → Service (app/services/) → Repository (app/repositories/) → Model (app/models/)
```

## Telegram бот
- @financeapp_import_bot
- Отдельный Docker контейнер
- Привязка через одноразовый код

## Мобильное приложение (планируется)
→ [[Фаза 10 — Мобильное приложение]]
- Flutter

## Инфраструктура
5 сервисов Docker: api (8000), worker (Celery), beat (Celery beat), db (PostgreSQL 16, ext 5433), redis (6379) + bot

## Ключевые модели
User, Account, Category, Transaction, Counterparty, ImportSession, ImportRow, TransactionCategoryRule

## Репозиторий
https://github.com/GregoryShokin/finance_WebApp_project
