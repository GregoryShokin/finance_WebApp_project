# FinanceApp Frontend

Frontend часть приложения на Next.js 14 + TypeScript + Tailwind CSS.

## Запуск

```bash
cp .env.example .env.local
npm install
npm run dev
```

## Переменные окружения

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

## Команды'
## Команда для выполнения миграций
docker compose exec api alembic upgrade head

```bash
npm run dev
npm run build
npm run start
npm run lint
```

## Стандарты структуры

- `app/` — маршруты и layout'ы App Router
- `components/` — переиспользуемые UI и feature-компоненты
- `hooks/` — клиентские hooks
- `lib/` — API-клиенты, auth, utils
- `types/` — общие типы

## Что не должно храниться в репозитории

- `node_modules/`
- `.next/`
- `.env.local`
