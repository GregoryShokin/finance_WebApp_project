# Фича — Dismissable unsupported-bank banner
#бэклог #пост-mvp #frontend #ux
> Pre-upload disclaimer на /import должен быть скрываемым (per-bank, per-session или persistent через localStorage), чтобы не спамить опытных юзеров.
---
## Контекст (2026-05-04)
В Шаге 1.6 на странице `/import` появился `<UnsupportedBankBanner>`: amber-баннер сверху с CTA «Запросить поддержку «Bank X»» для каждого unsupported-банка, у которого юзер имеет account.

Текущая логика — **всегда показывать**, если есть mix-accounts (Сбер supported + Альфа pending). Цель — поймать намерение ДО клика «Загрузить».

**Проблема для опытных юзеров:** юзер с одним Альфа-account и одним Сбер-account видит banner навсегда (пока Альфа не станет supported). Через неделю использования это превращается в визуальный шум — юзер давно понял, что Альфа не поддерживается, но баннер продолжает занимать место в UI.

## Планируемое
### Вариант A — per-session dismiss (минимальный)
- `useState<Set<number>>` — какие bank_id юзер закрыл в текущей сессии.
- Кнопка «×» в правом углу баннера.
- При reload страницы — состояние теряется, banner показывается снова.
- Плюс: простое, defensive (юзер не «скроет навсегда и забудет»).
- Минус: всё ещё спам после каждого reload.

### Вариант B — localStorage persistence
- Ключ `unsupported-bank-banner-dismissed-{user_id}` → array of bank_ids.
- При закрытии — добавить bank_id в array.
- При маунте — фильтровать banks, dismissed из localStorage.
- Reset условия:
  - Bank переходит в `supported` (фронт получает свежий accountsQuery с обновлённым extractor_status) — auto-show баннер успеха «Альфа теперь поддерживается!» один раз.
  - Юзер удалил account на этом банке — bank автоматически выпадает из `unsupportedAccountBanks`, баннер не показывается.
- Плюс: «закрыл — больше не вижу», как в production-tools.
- Минус: localStorage — per-browser, миграция на новое устройство пожертвует dismissals (acceptable).

### Вариант C — backend persistence
- Поле `dismissed_unsupported_bank_banners: jsonb` на `User`.
- Sync через PATCH `/users/me`.
- Плюс: per-user, не per-browser. Идеальный UX для multi-device.
- Минус: миграция + endpoint + добавляет user-state. Overkill для MVP edge case.

## Решение (рекомендация)
**Вариант B (localStorage)** — best balance UX vs complexity. Per-session dismiss слишком слаб (юзер закроет → reload → видит снова, разочарован). Backend persistence overkill для не-критичной UI-фичи.

Если юзер сменит браузер и снова увидит баннер — это OK, не катастрофа. CTA «Запросить поддержку» уже idempotent (повторный запрос на тот же банк возвращает существующий → не плодит дубли в `bank_support_requests`).

## Edge cases
- **Banner для нового unsupported-банка после dismiss других**: юзер dismissed Альфу → завёл account на Райффайзене (тоже pending) → Райффайзен в banner появится автоматически (его bank_id ещё не в dismissed-list).
- **Bank уже `supported`**: его accounts в `unsupportedAccountBanks` не попадают — banner для них не рендерится. Dismissed-list очищать не нужно — entry просто становится no-op.
- **Reset banner после promotion**: когда maintainer добавил банк в `SUPPORTED_BANK_CODES` и juzer перезагрузил страницу — banner для этого банка исчезает сам (bank.extractor_status === 'supported'), без специального reset-toast.

## Тесты
- Unit (Vitest, после Frontend test infra): mount banner → click ×, unmount → mount → не показывается.
- localStorage edge case: corrupted JSON → fallback на «показывать всё».
- Manual smoke: dismiss + reload + edit account-bank to supported в admin → banner исчезает.

## Оценка
0.25 дня (один useState + localStorage helper + 2-3 теста).

## Критичность
**LOW (пост-MVP)** — для тест-юзеров с 1-2 unsupported-банками banner появляется реже, не критично. Возвращаемся когда:
- юзеры в support'е жалуются на «надоел этот amber-баннер»;
- screenshots от тест-юзеров показывают баннер как доминирующий элемент UI (UX-debt).

## Ссылки
- §21.6 «Жёсткий guard на upload» в `Спецификация — Пайплайн импорта.md` — фиксирует текущее always-on поведение.
- `frontend/components/import-redesign/import-page.tsx:UnsupportedBankBanner` — компонент.
- `frontend/components/import-redesign/import-page.tsx:unsupportedAccountBanks` useMemo — источник данных.
