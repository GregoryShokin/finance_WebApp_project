# Технический план: Отложенный учёт кредитных покупок

**Статус:** Ожидает ревью  
**Версия:** 1.0  
**Зависит от:** `docs/specs/deferred-credit-purchases.md`  
**Дата:** 2026-04-11

---

## Что нашли в кодовой базе

Прежде чем смотреть что добавлять — что уже есть:

| Что нужно | Статус |
|-----------|--------|
| `Transaction.affects_analytics` | ✅ Уже есть — именно этот флаг фильтрует всю аналитику |
| `Transaction.credit_principal_amount` | ✅ Уже есть |
| `Transaction.credit_interest_amount` | ✅ Уже есть |
| `Transaction.goal_id` → FK на Goal | ✅ Уже есть |
| `TransactionOperationType.credit_payment` | ✅ Уже есть |
| `TransactionOperationType.credit_early_repayment` | ✅ Уже есть — и уже в `NON_ANALYTICS_OPERATION_TYPES` (не в аналитике) |
| `Account.account_type` как строка | ✅ Уже есть (значения: `regular`, `credit`, `credit_card`, `cash`, `deposit`, `broker`) |
| `Goal.is_system` / `system_key` | ✅ Уже есть, подушка — `system_key = "safety_buffer"` |
| Тип счёта `installment_card` | ❌ Нет |
| Флаг отложенной покупки на транзакции | ❌ Нет |
| Отслеживание остатка отложенной покупки | ❌ Нет |
| Флаг крупной покупки из свободных средств | ❌ Нет |
| `Goal.category_id` | ❌ Нет |
| Настройки пользователя `UserSettings` | ❌ Нет |
| Системная категория «Проценты по кредитам» | ❌ Нет |

### Важное наблюдение: изменение поведения `credit_payment`

Сейчас `credit_payment` **попадает в аналитику** (не входит в `NON_ANALYTICS_OPERATION_TYPES`). Новая логика:

- Для кредитов/рассрочки с активными отложенными покупками → платёж разбивается на атрибуционные записи по категориям. Оригинальная транзакция `credit_payment` получает `affects_analytics = False`.
- Для кредитов/рассрочки без активных отложенных покупок (все покупки были малыми) → основной долг **не** идёт в аналитику (иначе двойной счёт с уже учтёнными покупками). Только проценты → создаётся отдельная запись «Проценты по кредитам».

**Это breaking change для существующих данных.** Существующие `credit_payment` транзакции остаются с `affects_analytics = True` (назад-совместимость). Новые транзакции следуют новым правилам. Отдельной миграции данных нет — историческая аналитика незначительно расходится с новой, это допустимо.

---

## Часть 1: Изменения в базе данных (миграции)

### Миграция 0027 — Новые поля на `Transaction`

```sql
ALTER TABLE transactions
  ADD COLUMN is_deferred_purchase   BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN deferred_remaining_amount NUMERIC(14, 2),
  ADD COLUMN is_large_purchase      BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN source_payment_id      INTEGER REFERENCES transactions(id) ON DELETE SET NULL;

CREATE INDEX idx_transactions_is_deferred_purchase
  ON transactions(account_id, is_deferred_purchase)
  WHERE is_deferred_purchase = TRUE;
```

**Поля:**
- `is_deferred_purchase` — флаг отложенной покупки. `True` = эта покупка не в аналитике напрямую; аналитика идёт через атрибуционные записи платежей.
- `deferred_remaining_amount` — остаток непогашенного долга по этой отложенной покупке. `NULL` для обычных транзакций. Заполняется при создании отложенной покупки (`= amount`), уменьшается при каждом платеже.
- `is_large_purchase` — флаг крупной покупки из свободных средств. `True` = транзакция отображается в разделе «Крупные покупки», `affects_analytics = False`.
- `source_payment_id` — FK на транзакцию-платёж, породившую эту атрибуционную запись. Используется только для `operation_type = "credit_principal_attribution"`. При удалении платежа атрибуционные записи не каскадируются автоматически — сервис обрабатывает это явно.

### Миграция 0028 — Новый тип операции в `TransactionOperationType` + поле `Goal.category_id`

```sql
-- Enum credit_principal_attribution добавляется как новое значение в TransactionOperationType.
-- В PostgreSQL Enum нельзя добавить значение внутри транзакции — делаем отдельно:
ALTER TYPE transactionoperationtype ADD VALUE IF NOT EXISTS 'credit_principal_attribution';

-- Категория цели для пользовательских целей
ALTER TABLE goals
  ADD COLUMN category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL;
```

### Миграция 0029 — `UserSettings`

```sql
CREATE TABLE user_settings (
    id                          SERIAL PRIMARY KEY,
    user_id                     INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    large_purchase_threshold_pct NUMERIC(4, 3) NOT NULL DEFAULT 0.200,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

По одной строке на пользователя. Создаётся лениво при первом обращении (если строки нет — возвращаем дефолт 0.20).

---

## Часть 2: Изменения в моделях (`app/models/`)

### `app/models/transaction.py`

```python
# Добавить в класс Transaction:
is_deferred_purchase: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false", index=True)
deferred_remaining_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
is_large_purchase: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
source_payment_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, index=True)

# Добавить в TransactionOperationType:
credit_principal_attribution = "credit_principal_attribution"
```

### `app/models/goal.py`

```python
# Добавить в класс Goal:
category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
category = relationship("Category")
```

### `app/models/user_settings.py` (новый файл)

```python
class UserSettings(Base):
    __tablename__ = "user_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    large_purchase_threshold_pct: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.200"))
    created_at / updated_at — стандартно
```

---

## Часть 3: Изменения в схемах (`app/schemas/`)

### `app/schemas/account.py`

```python
# AccountType: добавить 'installment_card'
AccountType = Literal['regular', 'credit', 'credit_card', 'installment_card', 'cash', 'deposit', 'broker']
```

### `app/schemas/transaction.py`

```python
# В TransactionCreate добавить:
is_deferred_purchase: bool = False
is_large_purchase: bool = False

# В TransactionResponse добавить:
is_deferred_purchase: bool
deferred_remaining_amount: Decimal | None
is_large_purchase: bool
source_payment_id: int | None
```

### `app/schemas/goal.py`

```python
# В GoalCreate/GoalUpdate добавить:
category_id: int | None = None

# В GoalResponse добавить:
category_id: int | None
```

### `app/schemas/user_settings.py` (новый файл)

```python
class UserSettingsResponse(BaseModel):
    large_purchase_threshold_pct: float

class UserSettingsUpdate(BaseModel):
    large_purchase_threshold_pct: float  # validator: 0.05 ≤ v ≤ 0.50
```

---

## Часть 4: Изменения в сервисах

### `app/services/transaction_service.py`

**4.1 Константы**

```python
# ALLOWED_CREDIT_TYPES: добавить 'installment_card'
ALLOWED_CREDIT_TYPES = {"credit", "credit_card", "installment_card"}

# NON_ANALYTICS_OPERATION_TYPES: добавить attribution как НЕ-аналитику (контролируем вручную)
# credit_principal_attribution — в аналитику попадает через affects_analytics=True на самой записи,
# поэтому НЕ добавляем в NON_ANALYTICS_OPERATION_TYPES.
# Добавляем только, чтобы он не участвовал в стандартных проверках:
NON_ANALYTICS_OPERATION_TYPES = {
    "transfer", "investment_buy", "investment_sell",
    "credit_disbursement", "credit_early_repayment", "debt",
}
```

**4.2 `_affects_analytics()` — изменить логику**

```python
@staticmethod
def _affects_analytics(operation_type: str | None, is_deferred: bool = False, is_large: bool = False) -> bool:
    if is_deferred or is_large:
        return False  # Отложенные и крупные — не в обычную аналитику
    if operation_type == "credit_principal_attribution":
        return True  # Атрибуционные записи — явно в аналитику
    return operation_type not in NON_ANALYTICS_OPERATION_TYPES
```

**4.3 Новый метод `_get_active_deferred_purchases(account_id) -> list[Transaction]`**

Возвращает транзакции с `is_deferred_purchase = True` и `deferred_remaining_amount > 0` по указанному счёту, отсортированные по дате (для понятного порядка).

**4.4 Новый метод `_create_principal_attributions(payment, deferred_purchases, principal_amount) -> None`**

Логика:
1. Считает пропорции: `ratio_i = deferred_purchases[i].deferred_remaining_amount / sum_of_all_remaining`.
2. Вычисляет долю каждой покупки: `floor(principal_amount × ratio_i)`.
3. Находит разницу от округления, добавляет к доле с наибольшим остатком.
4. Для каждой покупки создаёт транзакцию `expense` с:
   - `operation_type = "credit_principal_attribution"`
   - `affects_analytics = True`
   - `amount = доля`
   - `category_id = deferred_purchase.category_id`
   - `account_id = payment.account_id`
   - `source_payment_id = payment.id`
   - `transaction_date = payment.transaction_date`
5. Уменьшает `deferred_remaining_amount` на каждой отложенной покупке.
6. Добавляет всё в `self.db`.

**4.5 Новый метод `_create_interest_expense(payment) -> None`**

Если `payment.credit_interest_amount > 0`:
1. Находит или создаёт системную категорию «Проценты по кредитам» (через `category_service`).
2. Создаёт транзакцию `expense` с:
   - `operation_type = "credit_interest"` (уже существует как тип)
   - `affects_analytics = True`
   - `amount = credit_interest_amount`
   - `category_id = system_interest_category.id`
   - `source_payment_id = payment.id`
   - `transaction_date = payment.transaction_date`

**4.6 Изменение `create_transaction()` — обработка credit_payment**

После создания транзакции типа `credit_payment` для счёта `credit` или `installment_card`:

```python
if (transaction.operation_type == "credit_payment"
        and account_type in {"credit", "installment_card"}):

    # 1. Установить affects_analytics = False на самом платеже
    transaction.affects_analytics = False

    deferred = self._get_active_deferred_purchases(credit_account_id)

    principal = transaction.credit_principal_amount or transaction.amount
    interest = transaction.credit_interest_amount or Decimal("0")

    # 2. Атрибуция основного долга
    if deferred and principal > 0:
        self._create_principal_attributions(transaction, deferred, principal)

    # 3. Запись процентов
    if interest > 0:
        self._create_interest_expense(transaction)
```

**4.7 Изменение `create_transaction()` — отложенная покупка**

Если пришёл запрос с `is_deferred_purchase = True`:
```python
if data.is_deferred_purchase:
    transaction.is_deferred_purchase = True
    transaction.deferred_remaining_amount = transaction.amount
    transaction.affects_analytics = False
```

Если пришёл запрос с `is_large_purchase = True`:
```python
if data.is_large_purchase:
    transaction.is_large_purchase = True
    transaction.affects_analytics = False
```

**4.8 Изменение `delete_transaction()`**

Перед удалением транзакции типа `credit_payment`:
1. Найти все атрибуционные записи с `source_payment_id = transaction.id`.
2. Для каждой: восстановить `deferred_remaining_amount` на соответствующей отложенной покупке, удалить атрибуционную запись.
3. Удалить запись процентов (`source_payment_id = transaction.id` и `operation_type = "credit_interest"`).

**4.9 Изменение `create_transaction()` — `credit_early_repayment`**

```python
if transaction.operation_type == "credit_early_repayment":
    deferred = self._get_active_deferred_purchases(credit_account_id)
    if deferred:
        # Есть что атрибутировать — распределяем как обычный платёж
        # и помечаем как крупную покупку (не в DTI, в раздел "Крупные покупки")
        self._create_principal_attributions(transaction, deferred, transaction.amount)
        transaction.is_large_purchase = True
    # Иначе: досрочка без отложенных — оставляем affects_analytics = False (уже в NON_ANALYTICS)
```

**4.10 Новый метод `check_large_purchase(user_id, amount) -> dict`**

```python
def check_large_purchase(self, user_id: int, amount: Decimal) -> dict:
    settings = UserSettingsService(self.db).get_or_default(user_id)
    avg_expenses = MetricsService(self.db).get_avg_monthly_expenses(user_id)
    threshold = avg_expenses * settings.large_purchase_threshold_pct
    return {
        "is_large": amount >= threshold,
        "threshold_amount": float(threshold),
        "avg_monthly_expenses": float(avg_expenses),
    }
```

---

### `app/services/user_settings_service.py` (новый файл)

```python
class UserSettingsService:
    def get_or_default(self, user_id: int) -> UserSettings:
        ...  # Возвращает существующую строку или объект с дефолтами (без записи в БД)

    def update(self, user_id: int, data: UserSettingsUpdate) -> UserSettings:
        ...  # Upsert строки настроек
```

---

### `app/services/financial_health_service.py`

**Минимальные изменения — аналитика уже фильтрует по `affects_analytics`.**

Единственное что нужно добавить: **метод `get_large_purchases(user_id, filters)`** для раздела «Крупные покупки».

```python
def get_large_purchases(self, user_id: int, ...) -> list[LargePurchase]:
    # Выбирает транзакции где:
    # (is_deferred_purchase = True) OR (is_large_purchase = True)
    # Для отложенных покупок — добавляет прогресс: (amount - deferred_remaining_amount) / amount
    # Для крупных — просто сумма и категория
```

Предупреждение рядом с FI-score/подушкой — добавить вычисление суммы `is_large_purchase = True` за последние 6 месяцев в ответе `financial_health`.

---

### `app/services/goal_service.py`

**`_compute_saved()`** — не меняется (уже фильтрует по `affects_analytics = True`).

**`create_goal()`** — принимать `category_id`, сохранять.

**`validate_goal_for_transaction()`** — добавить проверку: если цель типа `system_key = "safety_buffer"`, транзакции на неё идут как `affects_analytics = False`. Для остальных (пользовательских) — `affects_analytics = True`.

**`check_and_achieve()`** — вызывается после каждого взноса; при достижении цели закрывает её (`status = "achieved"`). Не меняется.

---

### `app/services/category_defaults.py` — системная категория

Добавить при инициализации пользователя (или лениво при первом `credit_payment`):

```python
SYSTEM_CATEGORIES = [
    ...
    {"name": "Проценты по кредитам", "is_system": True, "priority": "mandatory_expense"},
]
```

---

## Часть 5: Изменения в API (`app/api/v1/`)

### `POST /api/v1/transactions/` — расширить схему запроса

```python
is_deferred_purchase: bool = False
is_large_purchase: bool = False
# credit_principal_amount и credit_interest_amount — уже есть
```

Валидация: если `is_deferred_purchase = True`, account_type счёта должен быть `credit` или `installment_card`. Иначе — 422.

### `GET /api/v1/transactions/large-purchase-check` (новый endpoint)

```
GET /api/v1/transactions/large-purchase-check?amount=150000
Authorization: Bearer <token>

Response: { "is_large": true, "threshold_amount": 12000.0, "avg_monthly_expenses": 60000.0 }
```

### `GET /api/v1/analytics/large-purchases` (новый endpoint)

```
GET /api/v1/analytics/large-purchases?from=2026-01-01&to=2026-04-30&account_id=5&category_id=3

Response: list[LargePurchaseItem]
  - id, date, amount, category_name, account_name, type ("deferred"|"large"|"early_repayment"),
    paid_amount (для deferred), remaining_amount (для deferred), progress_pct (для deferred)
```

### `GET /api/v1/users/settings` (новый endpoint)

```
Response: { "large_purchase_threshold_pct": 0.20 }
```

### `PATCH /api/v1/users/settings` (новый endpoint)

```
Body: { "large_purchase_threshold_pct": 0.15 }
Response: { "large_purchase_threshold_pct": 0.15 }
```

### `PATCH /api/v1/accounts/{id}` — добавить `installment_card`

В ответе и запросе `account_type` теперь принимает `"installment_card"` как валидное значение.

### `PATCH /api/v1/goals/{id}` — принимать `category_id`

---

## Часть 6: Изменения на фронтенде

Описание на уровне «что делать», без деталей реализации:

### Форма создания транзакции

1. При выборе счёта `credit`/`installment_card` и вводе суммы → дёргать `/large-purchase-check?amount=X` (debounce 500ms).
2. При `is_large = true` → показывать кнопки-переключатели «Учесть сейчас / Учесть через платежи». По умолчанию — «Через платежи».
3. При выборе `credit_payment` → показывать поля «Основной долг» и «Проценты» (ОД + проценты = итого).
4. При выборе дебетового счёта с суммой ≥ порога → показывать переключатель «Обычный расход / Крупная покупка».

### Раздел «Крупные покупки» (новая страница/вкладка в аналитике)

- Список карточек с фильтрами (дата, счёт, категория).
- Карточки отложенных покупок с прогресс-баром «оплачено X из Y ₽».
- Бейджи: «Кредит» / «Рассрочка» / «Крупная покупка» / «Досрочное погашение».

### Страница настроек

- Слайдер «Порог крупной покупки» (5–50%, шаг 5%).
- Подпись: «Сейчас это ~X ₽».

### Виджеты FI-score и Подушка безопасности

- Плашка-предупреждение при наличии крупных покупок за последние 6 мес: «Крупных разовых расходов на X ₽ — учитывай при планировании буфера».

### Форма создания/редактирования цели

- Добавить поле «Категория расходов» (обязательное для новых целей, не обязательное для подушки).

---

## Часть 7: Порядок реализации

Рекомендуемый порядок — от базы к UI, каждый шаг независимо деплоится и тестируется.

**Шаг 1 — Миграции и модели** *(база)*
- Миграция 0027: новые поля на Transaction.
- Миграция 0028: `credit_principal_attribution` в enum, `Goal.category_id`.
- Миграция 0029: таблица `user_settings`.
- Обновить Python-модели (`transaction.py`, `goal.py`, `user_settings.py`).

**Шаг 2 — Сервисы (без поломки существующего поведения)** *(бэкенд)*
- `UserSettingsService` — полностью новый.
- `CategoryDefaults` — добавить системную категорию «Проценты по кредитам».
- `AccountType` schema — добавить `installment_card`.
- `transaction_service.py`:
  - `ALLOWED_CREDIT_TYPES` — добавить `installment_card`.
  - `check_large_purchase()` — новый метод.
  - `_get_active_deferred_purchases()` — новый метод.
  - `_create_principal_attributions()` — новый метод.
  - `_create_interest_expense()` — новый метод.
  - `create_transaction()` — новая ветка для `credit_payment`.
  - `create_transaction()` — новая ветка для `is_deferred_purchase`.
  - `create_transaction()` — новая ветка для `is_large_purchase`.
  - `create_transaction()` — новая ветка для `credit_early_repayment`.
  - `delete_transaction()` — откат атрибуционных записей.
- `goal_service.py` — поддержка `category_id`, логика `affects_analytics` по типу цели.
- `financial_health_service.py` — `get_large_purchases()`, расчёт суммы для плашки.

**Шаг 3 — API endpoints** *(бэкенд)*
- `GET /large-purchase-check`
- `GET /analytics/large-purchases`
- `GET/PATCH /users/settings`
- Расширить `POST /transactions/` и `PATCH /goals/{id}`.

**Шаг 4 — Фронтенд** *(последним, всё API уже есть)*
- Форма транзакции: логика large-purchase-check, переключатели, поля ОД/проценты.
- Новая страница/вкладка «Крупные покупки».
- Страница настроек: слайдер порога.
- Виджеты FI-score/подушки: плашка-предупреждение.
- Форма цели: поле категории.

---

## Риски и важные замечания

1. **Breaking change для `credit_payment`**: исторические транзакции остаются с `affects_analytics = True`, новые — с `False` (аналитика идёт через атрибуции). Первые N месяцев у пользователей, которые уже пользовались кредитами, возможно небольшое расхождение в цифрах.

2. **Откат атрибуций при редактировании платежа**: если пользователь редактирует сумму `credit_payment` или `credit_principal_amount` — нужно пересчитать атрибуционные записи. При `update_transaction()` добавить логику: если операция `credit_payment` и изменился `credit_principal_amount` → удалить старые атрибуции, создать новые.

3. **Дробные рубли при распределении**: всегда округляем вниз, остаток — к наибольшей доле. Проверить крайний случай: единственная отложенная покупка → вся сумма целиком.

4. **Системная категория «Проценты по кредитам»**: создаётся один раз при инициализации или лениво. Нельзя удалить или переименовать пользователем. Добавить проверку в `category_service.delete()`.

5. **`goal.category_id` — не обязательное поле**: существующие цели без категории продолжают работать как раньше (взносы не идут в категорный пирог, или идут в «Без категории» — нужно уточнить при реализации).

6. **DTI для `installment_card`**: `_calc_dti_payments()` в `financial_health_service.py` проверяет `account_type in {"credit", "credit_card"}`. Добавить `installment_card` в это условие.
