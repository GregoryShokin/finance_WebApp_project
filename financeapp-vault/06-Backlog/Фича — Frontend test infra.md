# Фича — Frontend test infra
#бэклог #пост-mvp #frontend #infra
> Поднять Vitest (или Jest) для unit-тестов чистых TS-функций на фронте.
---
## Контекст (2026-05-03)
Сейчас фронт не имеет test-runner'а: ни `vitest.config`, ни `jest.config`, в `package.json` команды `test` нет. Все проверки фронта — `tsc --noEmit` (типы) + manual smoke в браузере.

В Этапе 0.2 Шаг 4 это всплыло: `frontend/lib/upload/limits.ts` содержит `validateUploadSize` и `inferKindFromName` — чистые функции с явными edge cases (пустой файл, uppercase extension, boundary at exact limit). Без тестов регрессия будет ловиться только manual smoke'ом.

## Планируемое
### Setup
- **Vitest** (рекомендуется — нативно работает с Next.js + ESM, быстрее Jest на старте).
- `vitest.config.ts` с jsdom-окружением для DOM-тестов (если потребуется).
- `package.json`: `"test": "vitest run"`, `"test:watch": "vitest"`.
- `tsconfig.json` — отдельный `tsconfig.test.json` если конфигурация типов отличается.

### Минимальный набор тестов на старт
- `frontend/lib/upload/limits.test.ts`:
  - `validateUploadSize`: csv/xlsx/pdf within/over/empty/unknown_kind/boundary cases (10 кейсов).
  - `inferKindFromName`: lower/upper/mixed case, no-extension, multi-dot (`tar.gz`).
- `frontend/lib/api/client.test.ts`:
  - `ApiError.payload` корректно сохраняется на JSON-ошибках.
  - 401 interceptor: с refresh / без refresh / на `/auth/refresh` сам по себе.

### CI integration
- GitHub Actions (или текущая CI): `cd frontend && npm test` на каждый PR.

## Оценка
~1 день setup + ~0.5 дня на минимальный набор тестов.

## Критичность
**Низкий приоритет** — не блокер MVP. Manual smoke + `tsc --noEmit` ловят большинство ошибок. Test infra нужна когда:
- появится >5 чистых утилит на фронте,
- регрессии начнут возвращаться через manual проверки.

## Ссылки
- Этап 0.2 Шаг 4 — `frontend/lib/upload/limits.ts` нет unit-тестов.
- `frontend/lib/api/client.ts` — interceptor логика тоже без тестов.
