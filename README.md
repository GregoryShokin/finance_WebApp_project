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

## Лимиты загрузки

Загрузка выписок (`/imports/upload`, `/telegram/bot/upload`) защищена двумя слоями:

1. **`MaxBodySizeMiddleware`** — глобальный header-only check (`Content-Length` > `GLOBAL_BODY_SIZE_CAP_MB`, по умолчанию 30 MB) → ранний 413 до multipart-парсера.
2. **`read_upload_with_limits`** в роуте — потоковое чтение 64 KB чанками, magic-byte detection, per-type cap (CSV/XLSX 10 MB, PDF 25 MB), zip-bomb-защита для XLSX (распакованный размер > `MAX_XLSX_DECOMPRESSED_MB`, по умолчанию 100 MB).

**Backend env** (`app/core/config.py`):
- `MAX_UPLOAD_SIZE_CSV_MB`, `MAX_UPLOAD_SIZE_XLSX_MB`, `MAX_UPLOAD_SIZE_PDF_MB`
- `MAX_XLSX_DECOMPRESSED_MB`
- `GLOBAL_BODY_SIZE_CAP_MB`

**Frontend env** (`frontend/lib/upload/limits.ts`):
- `NEXT_PUBLIC_MAX_UPLOAD_CSV_MB`, `NEXT_PUBLIC_MAX_UPLOAD_XLSX_MB`, `NEXT_PUBLIC_MAX_UPLOAD_PDF_MB`

**Sync обязательство**: backend и frontend env должны иметь одинаковые значения. При расхождении сервер всё равно защищён, но UX ломается — клиент говорит «OK» и юзер ждёт пустой загрузки только чтобы получить 413.

**Next.js inlining caveat**: `NEXT_PUBLIC_*` инлайнится на этапе `next build`. Изменение фронт-лимитов требует пересборки + редеплоя фронта. Бэкенд может менять лимиты в runtime через перезагрузку env.

## Rate limits

Защита от brute-force паролей, abuse upload-эндпоинтов, replay-атак refresh-токенов. Реализация — `slowapi` + Redis (общий с Celery).

| Endpoint | Лимит | Ключ | Защищает от |
|---|---|---|---|
| `POST /api/v1/auth/login` | 5 / 15 минут | per-IP | brute-force паролей |
| `POST /api/v1/auth/register` | 3 / час | per-IP | спам регистраций |
| `POST /api/v1/auth/refresh` | 30 / 5 минут | per-IP | refresh-token replay |
| `POST /api/v1/imports/upload` | 30 / час | per-user (JWT subject) | abuse импортов |
| `POST /api/v1/telegram/bot/upload` | 30 / час | per-IP | abuse через бота |

### Конфигурация

Лимиты переопределяются через env: `RATE_LIMIT_LOGIN`, `RATE_LIMIT_REGISTER`, `RATE_LIMIT_REFRESH`, `RATE_LIMIT_UPLOAD`, `RATE_LIMIT_BOT_UPLOAD`. Формат — `slowapi`/`limits` (`"5/15 minutes"`, `"30/hour"`, `"30/5 minutes"`).

Глобальный toggle: `RATE_LIMIT_ENABLED=false` отключает enforcement (для dev/тестов/emergency без перерелиза).

### За reverse-proxy (nginx, Cloudflare, ALB)

`TRUSTED_PROXIES='["10.0.0.0/8","172.16.0.0/12"]'` — список IP/CIDR прокси, чьему `X-Forwarded-For` мы доверяем. По дефолту `[]` (XFF игнорируется → используется `request.client.host`).

⚠️ **Без правильной настройки `TRUSTED_PROXIES` в проде ВСЕ запросы будут идти как от IP nginx — атакующий легко обойдёт rate-limit.**

### 429 response

```json
{
  "detail": "Слишком много запросов. Повтори через 47 сек.",
  "code": "rate_limit_exceeded",
  "endpoint": "login_user",
  "retry_after_seconds": 47
}
```

HTTP-header: `Retry-After: 47`.

### Известные ограничения

- **fail-open при недоступности Redis**: rate-limit отключается, легитимный трафик не блокируется. Атакующий может DoS Redis для отключения защиты. Mitigation — Sentry-alert на disconnect, заведено в pre-deployment hardening.
- **401 побеждает 429**: невалидный токен → `Depends(get_current_user)` бросает 401 ДО декоратора rate-limit. Pre-auth IP-rate-limit на `/imports/upload` не реализован — защита через `/auth/login` лимит.
- **Bot-route per-IP, не per-telegram_id**: избегаем двойного парсинга 25 MB multipart для извлечения `telegram_id`. Backlog: `Фича — Bot rate-limit per-telegram_id`.
- **Декоратор-only enforcement**: slowapi архитектурно связывает «декоратор → срабатывает после `Depends`». Атакующий проходит `Depends(get_db)` до 429 (~0.1ms на acquire/release из pool). Не security-проблема, перформанс-нюанс.

## Авторизация

Двухтокенная JWT-схема (access + refresh) с rotation и reuse-detection.

- `POST /auth/login` и `POST /auth/register` (через автологин) возвращают пару `{ access_token, refresh_token }`.
- Access-токен живёт 15 минут (`ACCESS_TOKEN_EXPIRE_MINUTES`), отправляется в заголовке `Authorization: Bearer …`.
- Refresh-токен живёт 30 дней (`REFRESH_TOKEN_EXPIRE_DAYS`), хранится в таблице `refresh_tokens` как sha256-хеш + jti. Передаётся **только** в теле `POST /auth/refresh` и `POST /auth/logout`.
- Frontend (`lib/api/client.ts`) при 401 автоматически вызывает `/auth/refresh` (singleton, защита от race condition при параллельных запросах) и повторяет исходный запрос.
- Rotation: каждый успешный `/auth/refresh` revoke'ает использованный токен и выдаёт новую пару. Повторное использование revoked-токена → revoke всех активных токенов пользователя + 401 (защита от reuse-атак).
- Cleanup: Celery beat задача `prune_refresh_tokens` ежедневно в 04:30 UTC удаляет записи с `expires_at < now`.

## Подготовка чистого архива

Для повторной очистки проекта перед упаковкой можно использовать:

```bash
bash scripts/prepare_clean_archive.sh
```

Скрипт удаляет локальные env-файлы, кэш, артефакты сборки и создаёт архив `financeapp_clean.zip` уровнем выше корня проекта.
