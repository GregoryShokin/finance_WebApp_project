# Фича — Frontend error-codes typings
#бэклог #пост-mvp #frontend #ux
> TypeScript-типизация union'а серверных error codes для type-safe обработки на фронте.
---
## Контекст (2026-05-03)
Этап 0.2 ввёл structured error-payload'ы из бэка: `{detail, code, max_size_mb, actual_size_mb, kind, ...}`. На фронте это сейчас обрабатывается через runtime-typeof guards:

```ts
const code = typeof p.code === 'string' ? p.code : undefined;
if (code === 'global_body_size_exceeded' || code === 'upload_too_large') { ... }
```

Минусы:
- TS-компилятор не проверяет, что все известные коды покрыты в `formatUploadError`. Backend добавит `xlsx_signature_invalid` — фронт молча пропустит и покажет generic message.
- Нет автокомплита при наборе `code === '...'`.
- Расхождение backend-кодов (Python: `code = "xlsx_decompression_too_large"`) и frontend-литералов поймать только grep'ом.

## Планируемое
### Source of truth
- В `app/services/upload_validator.py` — добавить `class UploadErrorCode(StrEnum)` со всеми кодами.
- На фронте — `frontend/types/server-errors.ts`:
  ```ts
  export type UploadErrorCode =
    | 'upload_too_large'
    | 'global_body_size_exceeded'
    | 'extension_content_mismatch'
    | 'empty_file'
    | 'unsupported_upload_type'
    | 'xlsx_decompression_too_large'
    | 'xlsx_missing_manifest'
    | 'xlsx_invalid_archive';
  ```
- Discriminated union для payload'а: `UploadErrorPayload`, у каждого кода свой shape (например, `xlsx_decompression_too_large` обязан иметь `actual_decompressed_mb`).

### Generation (опционально)
- Скрипт `scripts/generate_frontend_error_codes.py` парсит Python-enum'ы и пишет TS-типы — гарантирует соответствие.
- Запускается в pre-commit hook'е.

### Refactor
- `formatUploadError(err)` использует `switch (code) { ... }` с `assertNever(code)` в default — TS-ошибка при появлении нового неcaught кода.

## Оценка
- Без генератора: ~2 часа на ручные типы + рефакторинг 1 mapper'а.
- С генератором: +0.5 дня на скрипт и pre-commit setup.

## Критичность
**Низкий приоритет** — текущий runtime-guards код работает. Type-safety даёт защиту от регрессии при росте числа эндпоинтов с structured errors (>3-5).

## Ссылки
- Этап 0.2: `app/services/upload_validator.py:to_payload()`, `frontend/components/import-redesign/import-page.tsx:formatUploadError`.
- Связано с [[Фича — Frontend test infra]] — тесты на mapper не имеют смысла без типизации union'а.
