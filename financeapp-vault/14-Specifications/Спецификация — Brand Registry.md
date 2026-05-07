# Спецификация: Brand Registry

#спецификация #импорт #бренды #архитектура

**Версия:** 1.0
**Дата:** 7 мая 2026
**Статус:** Утверждена

**История версий:**
- v1.0 (2026-05-07) — первая утверждённая версия. Фиксирует фактическое состояние Brand Registry после фаз Ph1–Ph8b, включая auto-learn `text`-паттернов от подтверждений (commit `cacd3a1`) и двухрежимный moderator UI («Группы» / «По дате», commit `3c2b192`). До этого Brand Registry упоминался в [[Спецификация — Пайплайн импорта]] §6.10 только в контексте UI-агрегации, без описания внутреннего устройства.

> Этот документ — **единственный источник истины** о том, как работает распознавание брендов: модель данных, резолвер, подтверждение, обучение паттернов, UI-флоу. Любое расхождение между реализацией и спекой — баг реализации, не спеки. Связанные документы: [[Спецификация — Пайплайн импорта]] §6.10 (брендовая агрегация в кластерной сетке), `app/services/brand_*.py`, `frontend/components/import-redesign/brand-*.tsx`.

---

## Содержание

1. [Философия и роль в пайплайне](#1-философия-и-роль-в-пайплайне)
2. [Модель данных](#2-модель-данных)
3. [Извлечение бренд-ключа из skeleton](#3-извлечение-бренд-ключа-из-skeleton)
4. [Резолвер: сопоставление skeleton'а с брендом](#4-резолвер-сопоставление-skeletonа-с-брендом)
5. [Подтверждение и отказ](#5-подтверждение-и-отказ)
6. [Bulk-применение бренда к сессии](#6-bulk-применение-бренда-к-сессии)
7. [Auto-learn `text`-паттернов от подтверждений](#7-auto-learn-text-паттернов-от-подтверждений)
8. [CRUD приватных брендов](#8-crud-приватных-брендов)
9. [Per-user category override](#9-per-user-category-override)
10. [UI-флоу модератора](#10-ui-флоу-модератора)
11. [Двухрежимный moderator: «Группы» vs «По дате»](#11-двухрежимный-moderator-группы-vs-по-дате)
12. [API surface](#12-api-surface)
13. [Жёсткие инварианты](#13-жёсткие-инварианты)
14. [Известные ограничения](#14-известные-ограничения)
15. [Глоссарий](#15-глоссарий)

---

## 1. Философия и роль в пайплайне

Brand Registry сидит **между** нормализатором и counterparty-биндингом. Его задача — дать стабильное человекочитаемое имя мерчанта поверх сырого описания банковской выписки и материализовать это имя в `Counterparty` + категорию для пользователя.

Ключевая идея: один реальный мерчант может появляться в выписках под десятком разных формулировок (`PYATEROCHKA 14130 Volgodonsk RUS`, `26033 MOR SBP 0387`, `Оплата товаров пятёрочка-у-дома`). Каждая формулировка даёт свой skeleton и свой fingerprint. Без объединяющего слоя пользователь видит разрозненные кластеры и должен подтверждать одно и то же десять раз.

**Что Brand Registry делает:**
- Резолвер ставит на строку `brand_id` ещё на этапе нормализации, если уверенно матчит.
- Подтверждение бренда на ОДНОЙ строке материализует `Counterparty`, биндит её fingerprint, **обучает новый паттерн** и подметает siblings во всей сессии одним проходом.
- Глобальные бренды (Пятёрочка, Магнит, Yandex Plus, …) приходят сидером и доступны всем юзерам с момента старта аккаунта.
- Приватные бренды (твоя локальная кофейня, МРТ-клиника, репетитор) живут в БД того же юзера и не утекают между пользователями.

**Что Brand Registry НЕ делает:**
- Не пишет ничего в `Transaction` напрямую. Brand → Counterparty → Transaction.counterparty_id.
- Не делает fuzzy-matching между skeleton'ами одного бренда (см. §14).
- Не заменяет правила категоризации (`transaction_category_rules`) — Brand даёт `category_hint`, который применяется только если у юзера такая категория есть и нет более сильного сигнала.
- Не работает на transfer-строках (skeleton содержит `перевод` / `transfer` / `c2c` / `внешний/внутренний`) — у них нет «бренда», есть получатель по идентификатору.

**Соответствие принципам [[Спецификация — Пайплайн импорта]]:**
- §1.1 (иерархия барьеров): Brand Registry — часть резолвинга на этапе нормализации (один из верхних барьеров), его подтверждение поднимает строку в `ready` без LLM.
- §1.2 (честность важнее автоматизации): резолвер с низкой confidence (< 0.65) не показывает inline-prompt — лучше промолчать, чем спросить «Это X?» с шансом 50/50.
- §1.3 (детерминизм): pattern-match — substring/exact, без LLM, идемпотентен в рамках состояния registry.

---

## 2. Модель данных

Три таблицы (`alembic/versions/0050_brands.py`, `0051_brand_patterns.py`, `0061_user_brand_category_overrides.py`).

### 2.1 `Brand`

Каноничная личность мерчанта.

| Поле | Тип | Заметки |
|---|---|---|
| `id` | int PK | |
| `slug` | str(64) UNIQUE | ASCII-транслит canonical_name + `_u<id>_<n>`. Per-user namespace для приватных. |
| `canonical_name` | str(128) | Имя, которое видит юзер. Может быть кириллица, эмодзи и т.п. |
| `category_hint` | str(64) NULL | Default-категория, имя строкой (не FK). Резолвится по case-fold к существующим категориям юзера на confirm. |
| `is_global` | bool | `true` — сидером, видно всем. `false` — приватный одного юзера. |
| `created_by_user_id` | int NULL | FK `users.id ON DELETE SET NULL`. NULL у глобальных. |

**Slug-генерация** ([brand_management_service.py:630-643](file:///d:/projects/financeapp/app/services/brand_management_service.py)): для приватных брендов `slug = slugify(canonical_name) + "_u" + user_id`, при коллизии — суффикс `_2`, `_3`. Каноническое имя НЕ уникально (двое юзеров могут оба создать «Пятёрочка»; глобальный + приватный могут совпадать).

### 2.2 `BrandPattern`

Конкретный способ как Brand появляется в сыром описании.

| Поле | Тип | Заметки |
|---|---|---|
| `id` | int PK | |
| `brand_id` | int FK | `brands.id ON DELETE CASCADE` |
| `kind` | str(32) | `text` / `sbp_merchant_id` / `org_full` / `alias_exact` |
| `pattern` | str(256) | Содержимое паттерна. Формат зависит от `kind` (см. §4.2). |
| `priority` | int | Default 100. Тай-брейк среди патернов одного kind. |
| `is_regex` | bool | Только для `kind='text'`. Maintainer-curated; API всегда пишет `false`. |
| `confirms` | Numeric(10,2) | Счётчик user-confirm'ов для этого паттерна. |
| `rejections` | Numeric(10,2) | Счётчик user-reject'ов. |
| `is_active` | bool | Off-switch без удаления (для авто-деактивации в будущем). |
| `is_global` | bool | См. правило scope ниже. |
| `scope_user_id` | int NULL | `users.id ON DELETE CASCADE`. См. правило scope ниже. |

**CHECK constraint scope-consistency** (`ck_brand_patterns_scope_consistency`):
```
(is_global = true AND scope_user_id IS NULL)
OR (is_global = false AND scope_user_id IS NOT NULL)
```

То есть паттерн **либо** глобальный (без owner), **либо** приватный (с owner). Никаких полу-состояний. Приватный паттерн МОЖЕТ висеть на ГЛОБАЛЬНОМ бренде — это user override (см. §4.3).

**Уникальность** (`uq_brand_patterns_brand_kind_pattern_scope`): `(brand_id, kind, pattern, scope_user_id)` уникально. Это значит:
- Один глобальный паттерн на бренд+kind+значение (sigleton при `scope_user_id=NULL`).
- Один приватный паттерн на пользователя на бренд+kind+значение.
- Два разных юзера могут иметь свои private-паттерны с одинаковым значением — они не конфликтуют.

### 2.3 `UserBrandCategoryOverride`

Per-user pin категории для бренда.

| Поле | Тип | Заметки |
|---|---|---|
| `id` | int PK | |
| `user_id` | int FK | |
| `brand_id` | int FK | |
| `category_id` | int FK | Должна принадлежать тому же `user_id`. |
| `created_at`, `updated_at` | timestamptz | |

UNIQUE `(user_id, brand_id)`. Default — берётся `Brand.category_hint`. Override активируется явным выбором категории в confirm-prompt'е или через `POST /brands/{id}/apply-category`.

---

## 3. Извлечение бренд-ключа из skeleton

`extract_brand(skeleton)` в [`brand_extractor_service.py`](file:///d:/projects/financeapp/app/services/brand_extractor_service.py) — чистая функция без БД. Используется в трёх местах:

1. `ImportClusterService._group_by_brand` — формирует `BrandCluster` уровня UI-агрегации (см. [[Спецификация — Пайплайн импорта]] §6.10).
2. `BrandManagementService.suggest_from_row` — подсказка для prefilling «Создать бренд» формы.
3. `BrandManagementService.list_unresolved_groups` — группирует unresolved-строки в виджет «Создать бренд из N строк?».
4. **`BrandConfirmService._learn_pattern_from_row`** — auto-learn нового паттерна от подтверждения (см. §7).

**Алгоритм:**
1. Если skeleton содержит transfer-keyword (`перевод` / `transfer` / `c2c` / `внешний` / `внутренний` / `внутрибанковский`) — return None (у transfer'ов нет бренда).
2. Идём по токенам слева направо (regex `<\w+>|[A-Za-zА-Яа-яЁё]{2,}`).
3. Скипаем filler-токены: legal forms (ООО, ИП, …), locale/city (`rus`, `volgodonsk`, …), legal-form-codes (`gm`, `mm`, `hm`), payment-method words (`pos`, `atm`, `оплата`, `покупка`, …), refund-keywords (`возврат`, `отмена`, `refund`, …), placeholder'ы (`<ORG>`, `<PERSON>`, …).
4. Скипаем токены с менее чем 3 alpha-символами.
5. Возвращаем первый прошедший все фильтры токен в `lower()`.

**Примеры:**
- `"оплата в pyaterochka 14130 volgodonsk rus"` → `"pyaterochka"`
- `"оплата в ip drugov ms volgodonsk rus"` → `"drugov"` (skip `оплата`, `в`, `ip`, `drugov` — 6 chars OK)
- `"внешний перевод номеру телефона <phone>"` → `None` (transfer)
- `"оплата в dts mrt g"` → `"dts"` (skip `оплата`, `в`, `dts` — 3 chars exactly, OK)
- `"оплата в mrtshka volgodonsk rus"` → `"mrtshka"`

**Дизайн-инвариант (см. модуль docstring):** false-positives хуже false-negatives. Лучше пропустить бренд, чем склеить два разных мерчанта в один. Поэтому:
- Никакого fuzzy-matching (Levenshtein и пр.). Если банк один раз пишет `ПЯТЁРОЧКА`, другой `ПЯТЕРОЧКА` — оба нормализуются в `pyaterochka` транслитом в нормализаторе, не в extract_brand.
- Минимум 3 alpha-символа (`kfc`, `wb` короче — должны заводиться как `alias_exact`-паттерны).
- Только первый non-filler токен — не пытаемся угадать «бренд» по второму или третьему слову.

---

## 4. Резолвер: сопоставление skeleton'а с брендом

[`BrandResolverService`](file:///d:/projects/financeapp/app/services/brand_resolver_service.py). Вход: `(skeleton, tokens, user_id)`. Выход: `BrandMatch | None`.

### 4.1 Конвейер kind-priority

Резолвер пробует kind'ы в строгом порядке, **первый матч побеждает**:

```
sbp_merchant_id  →  org_full  →  text  →  alias_exact
```

Внутри одного kind — сортировка:
1. user-scope first (приватный override бьёт глобальный паттерн).
2. длина паттерна DESC (`pyaterochka` бьёт `pyat`).
3. `(confirms - rejections)` DESC (паттерн с историей подтверждений выигрывает).
4. `id` ASC (детерминированный тай-брейк).

### 4.2 Скоринг по kind

Из [`brand_resolver_service.py:209-267`](file:///d:/projects/financeapp/app/services/brand_resolver_service.py):

| Kind | Сравнение | Base confidence | Length factor |
|---|---|---|---|
| `sbp_merchant_id` | `tokens.sbp_merchant_id == pattern_value` (exact) | 0.99 | — |
| `org_full` | `_normalize_org(tokens.counterparty_org) == _normalize_org(pattern_value)` | 0.95 | — |
| `text` (default) | `pattern.lower() in skeleton.lower()` (substring) | 0.80 | `min(1.0, len(pattern)/6)` |
| `text` (`is_regex=true`) | `re.search(pattern, skeleton.lower(), IGNORECASE)` | 0.80 | как у обычного text |
| `alias_exact` | `skeleton.strip() == pattern.lower().strip()` | 0.85 | — |

**Length factor для `text`** калибрована по сид-реестру:
- `pyaterochka` (11 chars) → 1.00 → confidence 0.80 ✓
- `magnit` (6) → 1.00 → 0.80 ✓
- `lenta` (5) → 0.83 → 0.67 ✓ (чуть выше threshold)
- `kfc` (3) → 0.50 → 0.40 ✗ (должен быть `alias_exact`)
- `wb` (2) → 0.33 → 0.27 ✗ (должен быть `alias_exact`)

### 4.3 Confidence factor (smoothing)

```
confidence_factor = (confirms + 1) / (confirms + rejections + 1)
```

Свежий seed-паттерн (0/0) стартует с `cf=1.0` — получает полную base confidence на первом проходе. Rejection'ы тянут вниз монотонно. Без +1 в числителе чисто-rejected паттерны давали бы 0 (мертвы), а с +1 они стремятся к 0 асимптотически (живут, но почти невидимы).

Финальная confidence: `score × confidence_factor`.

### 4.4 Threshold `BRAND_PROMPT_THRESHOLD = 0.65`

Ниже 0.65 резолвер возвращает `None`. **Зачем:** выше threshold — это «можно показать `Это <brand>?`-prompt не выглядя дураком». Ниже — лучше промолчать.

**Прямое следствие:** короткие `text`-паттерны (`dts` 3 chars: 0.40, `wave` 4 chars: 0.53) ниже threshold → резолвер их не предлагает auto-prompt'ом. Они работают **только** через bulk-apply (см. §6) и через явный picker-confirm.

Это не баг — это сознательная защита от «MRT таможня» получит prompt «Это МРТшка?» из-за подстроки `mrt`.

### 4.5 Видимость паттернов

`BrandRepository.list_active_patterns_for_user(user_id)`:
- Все `is_global=true AND is_active=true`
- Плюс `scope_user_id=user_id AND is_active=true`

Чужие приватные паттерны (от других юзеров) **никогда** не видны. Глобальный паттерн + private user override создают двойной матч — порядок сортировки (user-scope first) делает override приоритетным.

### 4.6 Кэширование

`BrandResolverService` создаётся per-request. Внутри — два кэша:
- `_patterns_cache: dict[user_id, list[BrandPattern]]` — список паттернов на юзера.
- `_brands_cache: dict[brand_id, Brand]` — preloaded brands для всех brand_id из паттернов.

Один `resolve()`-call по строке → один `dict[user_id]` lookup + substring tests. Для типичной выписки в 600 строк × ~80 активных паттернов на юзера это пренебрежимо.

`PreviewRowProcessor` дёргает `resolve()` один раз на строку при нормализации. Результат стампится в `nd.brand_id`, `nd.brand_pattern_id`, `nd.brand_canonical_name`, `nd.brand_category_hint`, `nd.brand_kind`, `nd.brand_confidence`.

---

## 5. Подтверждение и отказ

[`BrandConfirmService`](file:///d:/projects/financeapp/app/services/brand_confirm_service.py).

### 5.1 Confirm flow (`confirm_brand_for_row`)

Триггер: юзер кликнул `Это X? — Да` (inline-prompt) или выбрал бренд через picker.

Шаги:

1. **Validation.** Сессия не committed, строка не committed, бренд видим юзеру (свой private или глобальный).
2. **Strength bump.** Если `predicted_pattern_id != null AND predicted_brand_id == brand.id` → `pattern.confirms += 1`. Иначе если `predicted_pattern_id != null` (юзер выбрал ДРУГОЙ бренд) → `pattern.rejections += 1` (резолвер был неправ).
3. **Materialize Counterparty.** `_find_or_create_counterparty(user_id, brand)`: case-fold поиск по имени → существующая или новая `Counterparty(user_id, name=brand.canonical_name)`. Существующая выигрывает — это даёт юзер-edited имена («Пятёрочка у дома») переживать confirm'ы.
4. **Resolve Category.** Приоритет: явная категория из prompt'а (если выбрана) > `UserBrandCategoryOverride` > `Brand.category_hint` (case-fold lookup в категориях юзера). None если нет матча — строка остаётся без категории.
5. **Backfill brand display fields.** Если у строки нет `brand_canonical_name` (резолвер не предсказал бренд, юзер выбрал вручную через picker), стампим `brand_id`, `brand_slug`, `brand_canonical_name`, `brand_category_hint` для UI.
6. **Stamp row.** `user_confirmed_brand_id = brand.id`, `user_confirmed_brand_at = now`, `counterparty_id = cp.id`. `category_id` — только если ещё пуст (юзерский выбор категории всегда сильнее brand hint).
7. **Bind fingerprint.** `CounterpartyFingerprintService.bind(user_id, fingerprint, counterparty_id)`. Это влияет на ВСЕ будущие импорты юзера: строки с тем же fingerprint автоматически прилипнут к counterparty.
8. **Auto-learn pattern.** `_learn_pattern_from_row(user_id, brand, skeleton)` — см. §7.
9. **Propagate to siblings.** Только если `predicted_brand_id == brand.id` (резолвер предсказал тот же бренд). Иначе пропуск.
10. **Commit.**

### 5.2 Propagation (`_propagate_confirm`)

В рамках ОДНОЙ сессии (`session_id == row.session_id`), для всех строк кроме confirm'нутой:

1. Skip если `nd.brand_id != brand_id` — пропагация работает ТОЛЬКО для строк, которые резолвер уже отметил как этот бренд.
2. Skip если уже `user_confirmed_brand_id == brand_id`.
3. Stamp `user_confirmed_brand_id`, `counterparty_id`. Очистить `user_rejected_brand_id` если был.
4. Category propagation:
   - `force_category=true` (юзер явно выбрал категорию в prompt'е) → перетираем существующую.
   - `force_category=false` (default) → заполняем только если пусто.
5. Bind sibling's fingerprint к тому же counterparty.

**Острый угол propagation'а:** требует чтобы резолвер уже предсказал бренд на siblings. Если резолверный матч был ниже threshold (короткий текстовый паттерн) или паттерн не substring-matches sibling skeleton — `brand_id` у sibling пуст и propagation его пропустит. Этот gap закрывает auto-learn (§7) + bulk-apply (§6).

### 5.3 Reject flow (`reject_brand_for_row`)

Триггер: юзер кликнул `Это X? — Нет`.

1. Сессия/строка валидны, `predicted_pattern_id` и `predicted_brand_id` не пусты (нечего отвергать на пустом prompt'е).
2. `pattern.rejections += 1`.
3. Stamp `user_rejected_brand_id = predicted_brand_id`, `user_rejected_brand_at = now`. Очистить `user_confirmed_brand_id` если был.
4. **Не propagate.** Reject — row-local: юзер отвергнул бренд **на этой строке**, но это не значит что siblings'ам тоже не подходит.

`user_rejected_brand_id` далее блокирует строку от подбора в `apply_brand_to_session` (§6.1).

---

## 6. Bulk-применение бренда к сессии

[`BrandManagementService.apply_brand_to_session`](file:///d:/projects/financeapp/app/services/brand_management_service.py). Триггерится:
- После `createBrand` в `BrandCreateModal` (с `session_id` текущей сессии).
- После `confirmRowBrand` в `BrandPickerModal` (с `session_id`).
- Из `BrandEditModal` — кнопка «Применить ко всем строкам» (без `session_id` — sweep по всем активным сессиям).

### 6.1 Алгоритм

1. Загрузить активные паттерны бренда (видимые юзеру: глобальные + own private).
2. Запросить строки: `import_rows JOIN import_sessions WHERE user_id=user.id AND status != 'committed'` (если `session_id` указан — добавить фильтр).
3. Для каждой строки:
   - Skip если `user_confirmed_brand_id` или `user_rejected_brand_id` уже стоит (юзерское решение). Counter `skipped_user_decision`.
   - Skip если `brand_id` указывает на ДРУГОЙ бренд. Counter `skipped_already_resolved`.
   - Прогон `_score_match` по каждому паттерну. Любой ненулевой score — матч (winning = max). **Threshold НЕ применяется**.
   - Если матч — стамп `brand_id`, `brand_pattern_id`, `brand_slug`, `brand_canonical_name`, `brand_category_hint`, `brand_kind`, `brand_confidence` → вызов `BrandConfirmService.confirm_brand_for_row` для полного flow (counterparty, category, fingerprint binding, auto-learn, propagation).

**Возвращает:** `{matched, confirmed, skipped_user_decision, skipped_already_resolved}`.

### 6.2 Почему bulk-apply обходит `BRAND_PROMPT_THRESHOLD`

Цитата из docstring (`brand_management_service.py:470-484`):

> Resolver applies BRAND_PROMPT_THRESHOLD (0.65) — meant to decide whether to AUTO-ASK «Это X?» on a row. A short text pattern like `wave` (extracted from «Wave Coffee 1 Volgodonsk») scores 0.80 × min(1.0, 4/6) ≈ 0.533, which is correctly below threshold for resolver-driven prompts but is the WRONG cutoff for user-driven «I just created this brand, apply to my rows».

Иначе говоря: threshold защищает inline-prompt от шума. Bulk-apply — **явное намерение пользователя** «применить мой бренд везде где он матчится», и тут любой ненулевой score — валидный сигнал. Резолвер выбирал бы лучший бренд при коллизии; bulk-apply выбирает лучший паттерн ВНУТРИ одного бренда — коллизий между брендами нет по определению.

Регрессионный тест: `tests/test_brand_management_service.py::test_apply_brand_to_session_matches_short_pattern_below_resolver_threshold`.

---

## 7. Auto-learn `text`-паттернов от подтверждений

(Введён в commit `cacd3a1`, [[Спецификация — Пайплайн импорта]] v1.22.)

### 7.1 Триггер

Без auto-learn возникал классический gap. Бренд имеет один паттерн (например `text:mrtshka`, заведённый при создании). У того же мерчанта в выписке есть строки с другим skeleton'ом (`оплата в dts mrt g`, `оплата в dts mrt`). Substring `mrtshka` не матчит этих skeleton'ов.

Юзер picker-кликает «МРТшка» на DTS MRT-строке:
- `confirm_brand_for_row` стампит её одну.
- `_propagate_confirm` идёт по siblings, но фильтр `nd.brand_id == brand_id` отметает их (резолвер не предсказал — паттерн не матчил).
- `applyBrandToSession` после confirm-call'а тоже не помогает: тот же mismatch.

DTS MRT-сторона остаётся висеть. Юзер видит «я же сказал что это МРТшка, почему вы не понимаете?».

### 7.2 Решение

`BrandConfirmService._learn_pattern_from_row(user_id, brand, skeleton)` ([brand_confirm_service.py:488-527](file:///d:/projects/financeapp/app/services/brand_confirm_service.py)):

1. `candidate = extract_brand(skeleton)`. Если None — silent skip.
2. Загрузить ВСЕ паттерны бренда (любого scope).
3. Если есть `text`-паттерн с `pattern.casefold() == candidate.casefold()` — silent skip (не плодим private-дубликат глобального).
4. Иначе `repo.upsert_pattern(brand_id, kind='text', pattern=candidate, is_global=False, scope_user_id=user_id)`.

**Свойства:**
- Идемпотентность: повторный confirm на той же строке с тем же skeleton'ом ничего не делает.
- Silent-on-failure: исключения логируются и проглатываются. Pattern learning — opportunistic side-effect, никогда не часть контракта confirm'а.
- Только `kind='text'`. SBP merchant_id и org_full попадают в registry **только** через явный `add_pattern_to_brand` или сидер.
- Always private. Глобальные паттерны автор'ятся только сидером (см. §13).

### 7.3 UX-эффект

Picker-confirm на любом fingerprint'е бренда теперь самообучает паттерн. **`applyBrandToSession`, который вызывается picker-frontend'ом сразу после confirm'а, использует свежий паттерн** и подметает все siblings с тем же skeleton'ом.

Один клик закрывает кластер. Раньше требовалось вручную привязывать каждый fingerprint.

### 7.4 Регрессионные тесты

- `tests/test_brand_confirm_service.py::test_confirm_auto_learns_text_pattern_when_skeleton_carries_new_brand_token`
- `tests/test_brand_confirm_service.py::test_confirm_auto_learn_is_idempotent_when_pattern_already_exists`
- `tests/test_brand_confirm_service.py::test_confirm_auto_learn_skips_when_skeleton_has_no_brand_candidate`
- `tests/test_brand_confirm_service.py::test_confirm_auto_learn_does_not_duplicate_global_pattern`
- `tests/test_brand_management_service.py::test_picker_confirm_then_apply_catches_sibling_skeleton_via_auto_learned_pattern` — интеграционный repro MRTшка-кейса.

---

## 8. CRUD приватных брендов

[`BrandManagementService`](file:///d:/projects/financeapp/app/services/brand_management_service.py).

### 8.1 Create (`create_private_brand`)

`POST /brands {canonical_name, category_hint?}`:
- `canonical_name` обязателен, trim'ится, не должен быть пустым.
- `category_hint` опционален, blank trimmed → null.
- `slug = _generate_unique_slug(canonical_name, user_id)`.
- `is_global=False`, `created_by_user_id=user_id`.

**API never sets `is_global=True`.** Глобальные бренды только из сидера.

После создания фронт обычно вызывает `addBrandPattern(brand.id, ...)` чтобы заложить первый паттерн (см. §10.3).

### 8.2 Update (`update_private_brand`)

`PATCH /brands/{id} {canonical_name?, category_hint?}`:
- Только владелец может править свой private. Глобальные — read-only через API.
- Изменение `canonical_name` запускает `_refresh_display_fields_for_brand` — sweep по всем `ImportRow` юзера: у всех с этим `brand_id` обновляется `nd.brand_canonical_name` и `nd.brand_category_hint` в `normalized_data_json`. Без этого UI продолжал бы показывать старое имя до следующего пересчёта.
- Counterparty НЕ переименовывается. Юзер мог отредактировать имя counterparty («Пятёрочка у дома»), и rename бренда не должен этого затирать.

### 8.3 Delete (`delete_private_brand`)

`DELETE /brands/{id}`:
- Только владелец, только private.
- Hard-delete: FK CASCADE удаляет `BrandPattern` (любого scope) + `UserBrandCategoryOverride`.
- `_clear_brand_traces_on_rows`: проход по ImportRow'ам, у строк с `brand_id == this` или `user_confirmed_brand_id == this` или `user_rejected_brand_id == this` стираются ВСЕ ключи `brand_*` + `user_confirmed_brand_*` + `user_rejected_brand_*`.
- Counterparty + category НЕ трогаются — это юзер-классификация строки, отдельная от бренда.

### 8.4 Add pattern (`add_pattern_to_brand`)

`POST /brands/{id}/patterns {kind, pattern, is_regex?}`:
- На свой private — OK.
- На глобальный — OK, но запись идёт как `is_global=False, scope_user_id=user_id` (приватный override).
- На чужой private — 403.
- API всегда пишет `is_global=False`. Глобальные паттерны только из сидера.
- `is_regex` — для maintainer-curated паттернов (split-token описания типа `yandex.{0,30}plus`). API теоретически принимает, на практике все text-паттерны от пользователя — substring'и.

### 8.5 Suggest (`suggest_from_row`)

`GET /brands/suggest-from-row?row_id=X`. Prefill для формы `BrandCreateModal`:

Логика:
1. Грузим строку.
2. `tokens.sbp_merchant_id` есть → `(canonical=extract_brand(skeleton).title() or None, kind='sbp_merchant_id', value=str(merchant_id))`.
3. Иначе `extract_brand(skeleton)` → `(canonical=candidate.title(), kind='text', value=candidate)`.
4. Иначе `(None, None, None)` — фронт всё равно даёт fully-manual create.

### 8.6 Suggested groups (`list_unresolved_groups`)

`GET /brands/suggested-groups?session_id=X`. Питает виджет «Мы видим N строк, похожих на X — создать бренд?».

Алгоритм:
1. Запрос `import_rows JOIN import_sessions WHERE user_id=user.id AND status != 'committed'`. С `session_id` — сужение.
2. Filter:
   - `nd.brand_id is None`.
   - `nd.user_confirmed_brand_id is None AND nd.user_rejected_brand_id is None`.
   - `nd.operation_type IN (regular, refund, None)`.
3. Группируем по `extract_brand(skeleton)`. Skeleton'ы с None отбрасываются.
4. Группа эмитится только при `len(rows) >= MIN_SUGGESTION_ROWS = 3` (single-shots не повод заводить бренд).
5. Сортировка: `(-row_count, candidate)` — самые насыщенные сверху.

---

## 9. Per-user category override

[`BrandConfirmService.apply_brand_category_for_user`](file:///d:/projects/financeapp/app/services/brand_confirm_service.py).

`POST /brands/{id}/apply-category {category_id}`. Юзер уже подтвердил «Dodo Pizza» как «Кафе и рестораны» (default hint), теперь хочет «Доставка еды» по всем 26 историческим операциям + всем будущим.

Эффект:
1. `UserBrandCategoryOverride` upsert (один на пару `user_id, brand_id`).
2. Sweep по всем активным ImportRow с `brand_id == this`: `nd.category_id = category.id`. Существующая категория ПЕРЕТИРАЕТСЯ (это brand-level decision).
3. Будущие импорты бренда автоматически получат эту категорию через override-aware lookup в `_lookup_category_for_brand`.

`Brand.category_hint` остаётся как был — это «базовая подсказка», override — пользовательский выбор.

---

## 10. UI-флоу модератора

`frontend/components/import-redesign/`.

### 10.1 Inline `BrandPrompt`

`brand-prompt.tsx`. Появляется в `TxRow` когда:
```
nd.brand_id != null
AND nd.user_confirmed_brand_id == null
AND nd.user_rejected_brand_id == null
```

Резолвер уверенно матчил бренд (выше threshold), юзер ещё не отвечал — рендерится строка вида:

> 🔵 Это **«Пятёрочка»**? [Да] [Не тот бренд]

«Да» → `confirmRowBrand(row.id, brand.id, null)`. «Не тот бренд» → `rejectRowBrand(row.id)`.

### 10.2 Picker (`BrandPickerModal`)

`brand-picker-modal.tsx`. Появляется когда юзер кликнул «Выбрать бренд» на строке без резолверного матча или с rejected-меткой.

UI: search input + список брендов (private + global), кнопка `+ Создать новый бренд` снизу.

Клик по бренду → `confirmRowBrand(row.id, brand.id, null) → applyBrandToSession(brand.id, sessionId)`.

Toast: `Привязано к «X» + N строк` (N = `apply.confirmed`).

### 10.3 Create modal (`BrandCreateModal`)

`brand-create-modal.tsx`. Открывается из picker'а ИЛИ из suggested-groups widget'а ИЛИ как entry-point на TxRow.

Поля:
- **Канонiческое имя** (обязательно). Prefill из `suggest_from_row`.
- **Категория** (опционально, single-select из юзерских категорий).
- **Pattern kind + value** (обязательно). Prefill из `suggest_from_row` — `text:<extract_brand>` или `sbp_merchant_id:<token>`.

Submit:
1. `createBrand({canonical_name, category_hint: null})`. (Категория не в `category_hint` — она пишется как override.)
2. `addBrandPattern(brand.id, {kind, pattern, is_regex: false})`.
3. `confirmRowBrand(rowId, brand.id, categoryId)` — если выбрана категория, она ляжет как `UserBrandCategoryOverride`.
4. `applyBrandToSession(brand.id, sessionId)` — sweep сессии через свежий паттерн.

### 10.4 Edit modal (`BrandEditModal`)

`brand-edit-modal.tsx`. Открывается с подтверждённой строки через кнопку «✏️ Изменить бренд».

UI:
- **Имя** (редактируемо для private, заблокировано для global).
- **Категория-подсказка**.
- **Кнопка «Применить ко всем строкам»** (✨) — ретроактивный sweep по ВСЕМ активным сессиям юзера через `applyBrandToSession(brand.id, undefined)`. Без этого picker-confirm подметает только текущую сессию.
- **Кнопка «Удалить бренд»** (красная). Soft-confirm: первый клик → «Точно удалить?» → второй клик → hard-delete.

Sweep после rename: `_refresh_display_fields_for_brand` обновляет `brand_canonical_name` во всех `ImportRow`. UI сразу видит новое имя.

### 10.5 Suggestions widget (`BrandSuggestionsWidget`)

`brand-suggestions-widget.tsx`. Показывается над списком атеншн-кластеров когда `GET /brands/suggested-groups` возвращает ≥1 группу.

Карточка на группу:
- `«{candidate}» · {row_count} строк`
- Sample descriptions (3 шт).
- CTA: «Создать бренд из этих строк» → открывает `BrandCreateModal` с `rowId` первой sample-строки.

### 10.6 BrandCategoryEdit pill

`brand-category-edit.tsx`. На confirmed-строке справа от названия бренда висит pill «Категория для «X»». Клик → выбор категории → `applyBrandCategory(brand.id, category.id)` — пишет override и sweep'ит по строкам (см. §9).

---

## 11. Двухрежимный moderator: «Группы» vs «По дате»

`import-page.tsx:483-535`. Toggle справа над контентной секцией. Состояние persisted в `localStorage['import.view']`. Default — **`chronological`** (новый primary UX, Brand registry plan §7). `clusters` — opt-in fallback для bulk-by-brand workflow.

### 11.1 Режим «Группы» (`clusters`)

Стандартный кластер-сетка из `cluster-grid.tsx` + attention-feed снизу. Описан в [[Спецификация — Пайплайн импорта]] §6.10. Группирует строки по counterparty / brand / fingerprint и показывает карточки.

**Когда полезен:** 600+ строк выписки, юзер хочет one-click bulk-confirm крупных мерчантов («Яндекс Такси × 47», «Магнит × 23»). Brand Registry здесь работает через `BrandCluster` (если ≥2 fingerprint'ов одного бренда).

### 11.2 Режим «По дате» (`chronological`)

[`ChronologicalView`](file:///d:/projects/financeapp/frontend/components/import-redesign/chronological-view.tsx). Плоский список ВСЕХ операций сессии, отсортированный по `transaction_date DESC` (свежие сверху). Никакой иерархии, никакой группировки по брендам/контрагентам.

**Дизайн-логика (отличается от cluster-режима):**

1. **Visibility filter (как в AttentionFeed):**
   - Показываем: `ready`, `warning`, `error`.
   - Скрываем: `committed`, `duplicate`, `parked`, `skipped` (терминальные статусы).
   - Скрываем: `transfer`-строки (`nd.transfer_match` или `nd.operation_type === 'transfer'`) — они живут в виджете «Переводы и дубли».

2. **Сортировка.** Client-side. `transaction_date` DESC лексикографически (ISO-строки сортируются как даты). Тай-брейк по `id` DESC — последняя добавленная сверху при равенстве дат.

3. **Никакой группировки по счётам.** Single flat list через всю сессию (юзер-feedback против per-account split: при 6 счетах 30 разделов с 5 строками каждый — bulk-операции невозможны).

4. **Пагинация client-side.** `PAGE_STEP = 50`, кнопка «Показать ещё 50» в footer'е. Для 600-строчных выписок это 12 кликов — приемлемо, серверной пагинации нет.

5. **Per-row actions те же что в cluster-modal'е:**
   - `BrandPrompt` рендерится в `TxRow`, если резолвер матчил бренд (`nd.brand_id != null && nd.user_confirmed_brand_id == null && nd.user_rejected_brand_id == null`).
   - Picker, edit, split, exclude, park, delete — те же кнопки.
   - Автоматического sibling-sweep'а нет: каждая строка confirm'ится индивидуально (через `BrandPrompt` или picker), но **picker всё равно вызывает `applyBrandToSession`**, так что sibling-эффект происходит на уровне сессии независимо от режима.

**Когда полезен:** короткие выписки (< 50 строк), workflow «листаю выписку как в банке», или когда юзер хочет видеть транзакцию в контексте по дате (близкие переводы для refund-pairing на глаз).

**Что общего с «Группами»:** тот же `preview.rows` payload с бэкенда. Никакого специального API. Резолверные матчи `brand_id` те же (нормализатор стампит при импорте). Разница чисто UI — как рендерить.

### 11.3 Persistence и default

```typescript
const [importView, setImportView] = useState<'clusters' | 'chronological'>(
  () => {
    if (typeof window === 'undefined') return 'chronological';
    const stored = window.localStorage.getItem('import.view');
    return stored === 'clusters' ? 'clusters' : 'chronological';
  },
);
```

Default `chronological`. SSR-safe (на сервере `window` нет → возвращаем default).

`setImportViewPersistent(v)` пишет в `localStorage['import.view']` атомарно с `setState`.

### 11.4 Почему два режима, а не один

«Группы» — мощный bulk-tool, но требует ментального переключения «думаю не про конкретную операцию, а про мерчанта». «По дате» — естественный для new юзеров (как в банковском приложении). Обе раскладки нужны: power users хотят `clusters`, casual users хотят `chronological`. Опт-аут навязанный сверху ломает onboarding.

Default `chronological` выбран потому что новые юзеры регулярно жаловались на cluster-overhead на маленьких выписках. Power users однажды переключатся на `clusters` и больше не вспомнят (localStorage помнит).

---

## 12. API surface

`app/api/v1/brands.py` + `app/api/v1/imports.py` (части бренд-confirm/reject).

| Endpoint | Метод | Назначение |
|---|---|---|
| `/brands` | POST | Create private brand |
| `/brands` | GET `?q=&scope=&limit=` | Search/list brands visible to user |
| `/brands/suggest-from-row` | GET `?row_id=` | Prefill для create form |
| `/brands/suggested-groups` | GET `?session_id=` | Виджет «создать бренд из N строк?» |
| `/brands/{id}` | GET | Brand + visible patterns |
| `/brands/{id}` | PATCH | Rename / re-hint |
| `/brands/{id}` | DELETE | Hard-delete + clear traces |
| `/brands/{id}/patterns` | POST | Add private pattern |
| `/brands/{id}/apply-to-session` | POST `?session_id=` | Bulk-apply (без `session_id` — sweep всех активных) |
| `/brands/{id}/apply-category` | POST `{category_id}` | Set per-user category override |
| `/imports/rows/{id}/confirm-brand` | POST `{brand_id, category_id?}` | Confirm brand on row |
| `/imports/rows/{id}/reject-brand` | POST | Reject brand on row |

---

## 13. Жёсткие инварианты

1. **API никогда не пишет `is_global=True`.** Ни на бренде, ни на паттерне. Глобальные — только сидер `scripts/seed_brand_registry.py`.
2. **Scope-consistency check в БД** (`ck_brand_patterns_scope_consistency`): паттерн либо `(is_global=true, scope_user_id=null)`, либо `(is_global=false, scope_user_id=set)`. Половинчатых состояний не бывает — нарушит CHECK.
3. **Чужие приватные паттерны/бренды никогда не видны.** `list_active_patterns_for_user` фильтрует по scope, `_validate_brand` проверяет ownership.
4. **Auto-learn только `kind='text'`.** SBP merchant_id, org_full, alias_exact — только через явный API/сидер.
5. **Brand Registry никогда не пишет в `Transaction` напрямую.** Brand → Counterparty → Transaction.counterparty_id.
6. **Transfer-строки не имеют бренда.** `extract_brand` возвращает None, резолвер не дёргается, `BrandCluster` их не агрегирует. У transfer есть identifier (phone/contract/iban/card), не бренд.
7. **`apply_brand_to_session` обходит `BRAND_PROMPT_THRESHOLD`.** Cм. §6.2. Это сознательное решение, регрессионный тест защищает.
8. **`confirm_brand_for_row` и `apply_brand_to_session` идемпотентны.** Повторный call на ту же строку с тем же брендом не плодит counterparty/паттерны/binding'и.
9. **`user_rejected_brand_id` блокирует `apply_brand_to_session`** для этой строки целиком, независимо от того какой бренд был отвергнут. Семантика: «юзер один раз сказал что прогноз неправ → не пытайся применять любые бренды через bulk на этой строке».

---

## 14. Известные ограничения

1. **Никакого fuzzy-matching между skeleton'ами.** `mrtshka` и `dts mrt` для одного мерчанта остаются разными бренд-токенами. Auto-learn закрывает это через явный picker-confirm на каждом fingerprint'е. Альтернативы рассматривались (prefix-learn из canonical_name, transliteration-equivalence, Levenshtein) — отклонены из-за false-positive риска.
2. **Дубликаты бренда по canonical_name.** Юзер может создать «Вэйв Кофе» дважды если первый create залип/таймаутнул на UI; нет дедуп'а по casefold(canonical_name) на create. Безопасно (slug уникален), но засоряет picker. Ticket pending.
3. **Auto-learn НЕ ретроактивен.** Только что выученный паттерн `text:dts` НЕ перепроходит уже-confirmed строки. На практике не проблема: они уже привязаны к тому же counterparty и группируются в Layer 1.
4. **Глобальный паттерн с `is_active=False` всё равно блокирует auto-learn private-дубликата.** `_learn_pattern_from_row` проверяет паттерны любого scope/active-state. Если кто-то деактивировал глобальный `text:foo`, юзер не сможет его «переоткрыть» через auto-learn, паттерн не добавится. На практике глобальные паттерны не деактивируются часто — accepted edge case.
5. **`category_hint` на бренде — строка, не FK.** Резолвится через case-fold lookup в категориях юзера. Если у юзера нет категории `«Кафе и рестораны»`, hint молчит — строка остаётся без категории. Альтернатива (FK) ломала бы global-сидер, у которого нет user-context'а.
6. **Slug coliisions могут расти.** При collision'е суффикс `_2`, `_3`, … растёт линейно при попытках создания. На практике — единичные случаи; если юзер создаст 100 одинаковых брендов, slug станет уродливым. Ограничения нет, ticket pending.

---

## 15. Глоссарий

- **Brand** — каноничная личность мерчанта. Глобальная (сидер) или приватная (юзер).
- **BrandPattern** — конкретное представление бренда в сыром описании (`text:pyaterochka`, `sbp_merchant_id:26033`, …).
- **Kind** — тип паттерна: `text` / `sbp_merchant_id` / `org_full` / `alias_exact`.
- **Scope** — `(is_global=true, scope_user_id=null)` для глобальных или `(is_global=false, scope_user_id=set)` для приватных.
- **Resolver** — `BrandResolverService.resolve(skeleton, tokens, user_id) → BrandMatch | None`. Применяет threshold для авто-prompt.
- **Confidence factor** — smoothed `(confirms+1)/(confirms+rejections+1)`. Множитель к base confidence.
- **`BRAND_PROMPT_THRESHOLD`** — 0.65. Минимальная финальная confidence для inline `BrandPrompt`. `apply_brand_to_session` его не применяет.
- **Auto-learn** — авто-добавление приватного `text`-паттерна из `extract_brand(row.skeleton)` на confirm. См. §7.
- **Propagation** — на confirm, sweep по siblings в той же сессии с уже-stamp'нутым `brand_id == this brand`. См. §5.2.
- **Bulk-apply** — `apply_brand_to_session`, sweep по всем строкам сессии (или всех активных) через паттерны бренда. Без threshold. См. §6.
- **`UserBrandCategoryOverride`** — per-user pin категории на бренд. Перетирает `Brand.category_hint`.
- **Fingerprint binding** — `CounterpartyFingerprint(user_id, fingerprint, counterparty_id)`. Эффект на будущие импорты юзера.
- **Suggested groups** — виджет «Создать бренд из N строк?». Группирует unresolved-строки по `extract_brand(skeleton)`, threshold ≥ 3.
- **`chronological` view** — плоский список операций сессии, отсортированный по `transaction_date DESC`. Default для нового юзера.
- **`clusters` view** — counterparty/brand/fingerprint группировка. Opt-in для power-users.
