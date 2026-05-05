# Фича — Bot reads structured error messages
#бэклог #высокий-приоритет #импорт #bot
> Бот должен читать `bot_message` из backend-ответа и отвечать пользователю содержательным русским текстом — а не молча принимать или отвечать generic «не удалось».
---
## Контекст (2026-05-04)
В Этапах 0.5 + 1.6 backend научился возвращать `bot_message: str | None` в ответе `/telegram/bot/upload` — server-formatted Russian text, описывающий конкретную ситуацию (duplicate detected, bank unsupported, etc). **Бот же эти поля игнорирует** — `bot/main.py` отвечает default-template'ом, юзер не понимает, что произошло.

Это **HIGH priority** — без фикса duplicate-UX и bank-unsupported-UX в боте легко получить confusion-source для ранних тест-юзеров (которые часто экспериментируют именно через бот, а не web).

Карточка изначально создавалась как «Bot duplicate-statement UX» (Этап 0.5), но теперь Шаг 1.6 добавил вторую error-категорию (bank_unsupported) с тем же `bot_message`-механизмом. Расширяем scope до общей инфраструктуры «bot читает structured backend errors».

## Сценарии, которые backend уже отдаёт

### 1. Duplicate (Этап 0.5)
`POST /telegram/bot/upload` возвращает 201 + `bot_message`:
- CHOOSE: «Эта выписка уже в работе (загружена 21.04.2026). Открой /import в веб-версии чтобы продолжить или удалить старую сессию.»
- WARN: «Эта выписка уже импортирована (загружена 21.04.2026). Если нужно перезагрузить — открой /import в веб-версии.»

См. `app/api/v1/telegram.py:_format_bot_duplicate_message` + §23.7 спеки.

### 2. Bank unsupported (Шаг 1.6)
`POST /telegram/bot/upload` возвращает **HTTP 415** + JSON:
```json
{
  "code": "bank_unsupported",
  "bank_id": 42,
  "bank_name": "Альфа-Банк",
  "extractor_status": "pending",
  "detail": "...",
  "bot_message": "Импорт из банка «Альфа-Банк» пока не поддерживается. Открой /import в веб-версии и нажми «Запросить поддержку банка»..."
}
```

См. `app/api/v1/telegram.py` upload route + §21.6 спеки.

### 3. Будущие structured errors (нужны backend-additions)
- Rate-limit 429 (Этап 0.3) — payload содержит `retry_after_seconds`. Bot мог бы отрисовать «Подожди N секунд». **Сейчас `bot_message` НЕ выдаётся** — добавить через formatter.
- Upload validation 413/415 (Этап 0.2) — `code='upload_too_large'` etc. **Сейчас `bot_message` НЕ выдаётся** — bot отвечает generic. Добавить через formatter.

## Планируемое (bot side)
В `bot/main.py` после получения JSON ответа от backend:

```python
if response.status_code == 201 and data.get("bot_message"):
    # Successful upload + duplicate marker (Этап 0.5)
    await message.reply(data["bot_message"])
elif response.status_code in (413, 415, 429) and data.get("bot_message"):
    # Structured error with bot-formatted text (Шаг 1.6 + future)
    await message.reply(data["bot_message"])
elif response.status_code in (413, 415, 429):
    # Structured error без bot_message — формируем generic из code
    await message.reply(_format_bot_error_fallback(data))
elif response.status_code == 201:
    # Plain success
    await message.reply(_default_uploaded_template(data))
else:
    await message.reply("Не удалось загрузить выписку. Попробуй ещё раз.")
```

Опционально для CHOOSE / bank_unsupported: inline-кнопка «Открыть в web» (deep-link на `/import?session_id=N` или `/import`). Требует env `WEB_BASE_URL` в bot.

## Планируемое (backend-side, опционально в том же PR)
Добавить `bot_message` для остальных structured error-кодов:
- `upload_too_large` / `xlsx_decompression_too_large` — «Файл слишком большой ({actual} МБ при лимите {max} МБ).»
- `extension_content_mismatch` — «Файл с расширением .csv похож на PDF — проверь, что отправляешь правильный.»
- `rate_limit_exceeded` — «Слишком много загрузок подряд. Попробуй через {retry_after} сек.»

Helper в `app/services/bot_message_formatter.py`, маппит `code` → Russian text. Один formatter — все routes.

## Известные ограничения после фикса
- `force_new=true` для duplicate всё ещё web-only: bot не позволит «всё-таки загрузить как новую» из чата (см. §23.4 спеки). Юзер идёт в /import.
- Если backend изменит формулировку `bot_message` — bot сразу подхватит (server-side rendering, не нужен deploy bot для копирайтинг-правок).

## Тесты
- Bot integration: stub backend ответом с `bot_message`, проверить, что `message.reply()` вызывается с этим текстом.
- Backend test для каждого нового `bot_message` formatter: snapshot Russian-text строки.

## Оценка
- Bot-side: 0.5 дня (один if-elif в bot/main.py + 2-3 теста + manual smoke в Telegram).
- Backend-side: 0.5 дня (formatter helper + 4 кода + тесты).
- Итого: 1 день.

## Критичность
**HIGH** — closing item для bot-equivalent UX как Этапа 0.5, так и Шага 1.6 (и потенциально Этапов 0.2/0.3). Без этого 0.5 + 1.6 нельзя считать «complete» для bot-юзеров.

## Ссылки
- §23.7 «Bot route — read-only signaling» в `Спецификация — Пайплайн импорта.md`
- §21.6 «Жёсткий guard на upload» в той же спеке
- `app/api/v1/telegram.py:_format_bot_duplicate_message` + bank_unsupported handler — готовые server-side helpers
- Memory `architecture_decisions.md` — блоки «Duplicate-statement UX» + «Bank whitelist» + «Rate limits»
