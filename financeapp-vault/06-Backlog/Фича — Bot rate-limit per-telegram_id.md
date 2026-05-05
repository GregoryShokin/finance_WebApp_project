# Фича — Bot rate-limit per-telegram_id
#бэклог #пост-mvp #телеграм-бот #rate-limit
> Per-telegram_id rate-limit на `/telegram/bot/upload` вместо текущего per-IP.
---
## Контекст (2026-05-04)
В Этапе 0.3 принято решение применять `key_func=ip_key` к `/telegram/bot/upload`. Аргумент: per-telegram_id key потребовал бы парсинга 25 MB multipart body **дважды** — один раз в `key_func` для извлечения `telegram_id`, второй раз в роуте для `await file.read()`. Slowapi key_func синхронный, multipart парсится асинхронно — невозможно без переусложнения.

Текущий статус: bot-traffic с одного IP бот-инстанса делит **один** counter на 30/час. Если в продакшене используется один общий бот для всех юзеров — все юзеры конкурируют за одну квоту.

## Проблема
Multi-bot deployment или partner-bot integration: разные юзеры с одного бот-IP не должны блокировать друг друга. Per-IP лимит 30/час делится между ВСЕМИ юзерами одного бот-инстанса.

## Планируемое
### Вариант A: telegram_id в URL path
- `POST /telegram/bot/{telegram_id}/upload` — telegram_id становится path parameter.
- `key_func` синхронно читает из `request.path_params`, без парсинга body.
- Ломает текущий API контракт — bot нужно обновить одновременно с backend (deploy lockstep).

### Вариант B: telegram_id в header
- `X-Telegram-User-Id: <id>` header добавляется bot'ом.
- `key_func` читает из `request.headers` (синхронно, дешёво).
- Не ломающее изменение, можно сделать opt-in: header отсутствует → fallback на per-IP (текущее поведение).

### Вариант C: SpooledTemporaryFile для multipart с двойным чтением
- Парсить body один раз в middleware/dependency, кешировать в `request.state`.
- Key_func читает из state.
- Сложно, требует изменения порядка multipart-парсинга в Starlette/FastAPI.

**Рекомендация: вариант B** — non-breaking, простой, opt-in.

### Backend
- Расширить `app/core/keys.py`: новая `bot_telegram_or_ip_key(request)` — читает `X-Telegram-User-Id`, fallback на `ip_key` если отсутствует/невалиден.
- На `/telegram/bot/upload`: `@limiter.limit(settings.RATE_LIMIT_BOT_UPLOAD, key_func=bot_telegram_or_ip_key)`.
- Тесты: per-telegram_id isolation, fallback на IP при отсутствии header.

### Bot
- В `bot/main.py` — добавить header `X-Telegram-User-Id: {update.effective_user.id}` ко всем upload-запросам.

### Документация
- Обновить README раздел «Rate limits» — bot колонка станет per-telegram_id.
- Обновить memory `architecture_decisions.md`.

## Оценка
~0.5-1 день (helper + декоратор + тесты + bot-side header).

## Критичность
**Низкий приоритет** — серверная защита уже работает (per-IP), реальная проблема возникает только при scale > 1 бота или high-volume single-bot. Не блокер MVP.

## Ссылки
- Этап 0.3 mini-step 1.5 (investigation): `app/core/keys.py`, decision in `architecture_decisions.md` block "Rate limits".
- Связано: [[Фича — Bot-side upload validation]] (UX-валидация на стороне бота, тоже про bot/).
