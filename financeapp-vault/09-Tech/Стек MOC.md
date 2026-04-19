# Стек MOC
#стек
> Технический стек проекта.
---
## Backend
- FastAPI + SQLAlchemy + PostgreSQL + Redis + Celery + Alembic
- Docker Compose (api, worker, db, redis, bot)
- JWT (python-jose, passlib)
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
4 сервиса Docker: api (8000), worker (Celery), db (PostgreSQL 16, ext 5433), redis (6379)

## Ключевые модели
User, Account, Category, Transaction, Counterparty, ImportSession, ImportRow, TransactionCategoryRule

## Репозиторий
https://github.com/GregoryShokin/finance_WebApp_project
