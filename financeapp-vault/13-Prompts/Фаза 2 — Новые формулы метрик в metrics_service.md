# Фаза 2 — Новые формулы метрик в metrics_service.py (2026-04-19)

> Промпт для Claude Code. Выполняется ПОСЛЕ Фазы 1.
>
> **Предусловие:** в БД нет транзакций `operation_type='credit_payment'`, системная категория «Проценты по кредитам» существует, pytest установлен (в requirements.txt).

**Результат фазы:** `metrics_service.py` считает трёхслойный Поток (Базовый / Свободные / Полный с компенсатором), Буфер устойчивости вместо Запаса, FI-score v1.4. Окно усреднения везде = 12 мес. API `/metrics/summary` возвращает все новые поля.

---

```
Ты выполняешь Фазу 2 внедрения трёхслойной модели Потока в FinanceApp (решение 2026-04-19).

## Контекст

Спецификация: `financeapp-vault/01-Metrics/Поток.md` — полная методология.
Файл для правки: `app/services/metrics_service.py` — прочитай его целиком перед началом.

## Что уже правильно в metrics_service.py (не ломать)

- `_calc_basic_flow_for_month` — корректен, не трогать
- `_calc_regular_income_for_month` — корректен, не трогать
- `calculate_dti` — логика верная, меняется только окно (см. ниже)
- `calculate_capital` — корректен (liquid + deposit − debt)
- `_build_recommendations`, `_get_fi_zone` — не трогать

## Задача (в порядке выполнения)

### Шаг 1. Исправить окно усреднения: 3 мес → 12 мес

Везде в `metrics_service.py`, где используется `range(1, 4)` (три предыдущих месяца) — заменить на `range(1, 13)` (двенадцать завершённых месяцев).

Конкретно:
- `calculate_flow` — lifestyle_indicator: `range(1, 4)` → `range(1, 13)`, вычислять среднее только по месяцам с данными
- `calculate_dti` — знаменатель: `range(1, 4)` → `range(1, 13)`
- `get_financial_independence` — avg_expenses: `range(1, 4)` → `range(1, 13)`

Правило для avg: если данных меньше 12 мес — использовать доступные (не делить на 12, делить на фактическое число месяцев с данными). Поведение при нуле месяцев с данными — возвращать None.

### Шаг 2. Добавить Свободные средства (GAP #4)

**Формула:**
```python
free_capital = basic_flow - sum(
    Decimal(str(acc.monthly_payment or 0)) * body_ratio(acc)
    for acc in credit_accounts
)
```

Где `body_ratio(acc)`:
- Для `installment_card` (рассрочка 0%): `body_ratio = 1.0` (тело = полный платёж)
- Для `credit_card`: если долг и monthly_payment заданы — `body_ratio = 1.0` (для КК, минимальный платёж = тело + проценты, проценты уже в Базовом, поэтому body = полный платёж. Но если пользователь закрывает полностью = грейс, тело = 0). Используй `acc.monthly_payment` если оно задано, иначе 0.
- Для `credit`, `mortgage`: `body_ratio = 1 - (avg_interest / acc.monthly_payment)`. Проценты уже в Базовом потоке как regular expense, поэтому из monthly_payment вычитаем среднее процентов. Если нет данных по процентам — `body_ratio = 0.8` (эмпирическое: 80% платежа = тело).

Практически: проще всего вычислить `avg_interest_per_account` из транзакций за последние 3 мес (expense, operation_type=regular, credit_account_id=acc.id, category name like «Проценты»). Тело = `monthly_payment - avg_interest_expense`.

Новые методы:

```python
def _calc_avg_interest_per_account(
    self, user_id: int, credit_account_ids: set[int], months: int = 3
) -> dict[int, Decimal]:
    """
    Возвращает {account_id: avg_monthly_interest_expense} за последние `months` мес.
    Берёт expense-транзакции с credit_account_id, категория «Проценты по кредитам».
    """
    ...

def _calc_free_capital_for_month(
    self,
    basic_flow: Decimal,
    credit_accounts: list[Account],
    avg_interest_by_account: dict[int, Decimal],
) -> Decimal:
    """
    free_capital = basic_flow - Σ(тело обязательного платежа)
    тело = monthly_payment - avg_interest_expense (проценты уже в Базовом)
    """
    ...

def calculate_free_capital(self, user_id: int, year: int, month: int) -> dict:
    """
    {
      "free_capital": Decimal,
      "credit_body_payments": Decimal,   # сколько вычли (для отображения в виджете)
    }
    """
    ...
```

### Шаг 3. Добавить компенсатор КК (для декомпозиции Полного потока)

Компенсатор = прирост долга по кредиткам за период. Нужен для декомпозиции в виджете, чтобы «сумма строк = центральное число».

**Формула через транзакции за период:**
```
compensator =
  + Σ(amount, account_id in CC_accounts, type='expense')   # покупки в долг (увеличили долг)
  - Σ(amount, target_account_id in CC_accounts, operation_type='transfer')  # погашения (уменьшили долг)
  - Σ(amount, credit_account_id in CC_accounts, operation_type='credit_early_repayment')  # досрочные
```

Позитивный компенсатор = долг вырос = кэш не ушёл, хотя расход зафиксирован. Объясняет разницу между «потрачено X» и «Δ на счетах Y».

```python
def calculate_cc_debt_compensator(
    self, user_id: int, year: int, month: int
) -> Decimal:
    """
    Прирост долга по credit_card и installment_card за период.
    Позитивное значение: долг вырос (кэш не ушёл).
    Используется в декомпозиции виджета Полного потока.
    """
    ...
```

### Шаг 4. Переписать Полный поток — через транзакционный Δ

Текущая реализация `_calc_full_flow_for_month` считает `income - expense` транзакционно, что неверно (не балансово и не учитывает переводы на кредитные счета как отток).

**Правильная формула — Δ ликвидной сферы за период:**

Ликвидная сфера = regular + cash + deposit счета.

```
Полный =
  + Σ(income, account_id in LIQUID)               # доходы (зарплата, бонусы, disbursement)
  - Σ(expense, account_id in LIQUID)              # все расходы с ликвидных (включая покупки на КК:
                                                  # нет, покупки на КК идут со счёта КК, не с дебета)
  - Σ(transfer, account_id in LIQUID,             # переводы ИЗ ликвидных на кредитные счета
       target_account_id in CREDIT)               # (тело платежей)
  - Σ(credit_early_repayment, account_id in LIQUID)  # досрочные из ликвидных
  # Переводы ликвидный→ликвидный (regular↔deposit) не включаем: нетто = 0
```

Почему покупки на КК не вычитаются: покупка на КК идёт со счёта credit_card (account_id = credit_card), а не с дебетового — значит, ликвидный баланс пользователя не уменьшился в момент покупки. Он уменьшится при погашении (transfer c regular на credit) — которое мы уже вычитаем.

```python
def _calc_full_flow_for_month(
    self,
    txns: list[Transaction],
    liquid_account_ids: set[int],
    credit_account_ids: set[int],
) -> Decimal:
    """
    Δ ликвидного кэша = что ПРИШЛО в ликвидную сферу - что УШЛО.
    """
    ...
```

Обнови сигнатуру метода и все места, где он вызывается. Теперь ему нужны множества account_ids по типу.

### Шаг 5. Добавить Буфер устойчивости (вместо Запаса)

Запас (calculate_reserve) считается от regular+cash. Буфер считается только от deposit.

```python
def calculate_buffer_stability(self, user_id: int) -> dict:
    """
    Буфер устойчивости = Σ(deposit account balances) / avg(monthly_expenses, 12 мес)

    Возвращает:
    {
      "months": float | None,     # на сколько месяцев хватит вкладов
      "zone": str | None,         # "critical" | "minimum" | "normal" | "excellent"
      "deposit_balance": Decimal, # суммарный баланс на вкладах
      "avg_monthly_expense": Decimal,
    }

    Зоны: < 1 → critical, 1–3 → minimum, 3–6 → normal, > 6 → excellent.
    """
    ...
```

Метод `calculate_reserve` оставь — он используется в health-совместимости. Но в `_calc_fi_score` и `calculate_metrics_summary` переключись на `calculate_buffer_stability`.

### Шаг 6. Обновить FI-score (новые веса v1.4)

Текущие веса (старые, неверные):
```python
fi_score = flow_score * 0.25 + capital_score * 0.30 + dti_score * 0.20 + reserve_score * 0.25
```

Новые веса v1.4:
```python
# Норма сбережений: avg(basic_flow) / avg(regular_income) × 100 → нормировать 0% → 0, ≥30% → 10
savings_score = min(max(lifestyle_indicator / 30 * 10, 0), 10) if lifestyle_indicator is not None else 5.0

# Капитал-траектория: trend > 0 → 10, trend ≈ 0 → 5, trend < 0 → 0
# Используем относительный тренд: trend / avg_capital * 100%
# Пока trend=null (нет снимков) → 5.0 (нейтральный, исправится в Фазе 3)

# DTI inverse: 0% DTI → 10, ≥60% DTI → 0
dti_score = max(10 - (dti_pct / 6), 0) if dti_pct is not None else 10.0

# Буфер устойчивости: 0 мес → 0, ≥6 мес → 10
buffer_score = min(buffer_months / 6 * 10, 10) if buffer_months is not None else 0.0

fi_score = (
    savings_score  * 0.20   # Норма сбережений
    + capital_score * 0.30  # Капитал-траектория
    + dti_score    * 0.25   # DTI inverse
    + buffer_score * 0.25   # Буфер устойчивости
)
```

Обнови `_calc_fi_score(self, flow, capital, dti, buffer)` — сигнатуру, добавь `buffer` вместо `reserve`.

### Шаг 7. Обновить calculate_metrics_summary

Добавь в ответ:
```python
{
  "flow": {
      "basic_flow": ...,
      "free_capital": ...,        # новое (GAP #4)
      "full_flow": ...,
      "cc_debt_compensator": ..., # новое (для виджета)
      "credit_body_payments": ...,# сколько вычтено из свободных
      "lifestyle_indicator": ...,
      "zone": ...,
      "trend": ...,
  },
  "capital": {...},
  "dti": {...},
  "buffer_stability": {...},   # новое (вместо reserve в FI-score)
  "reserve": {...},            # оставляем для обратной совместимости
  "fi_score": ...,
}
```

### Шаг 8. Обновить API endpoint

Найди роут, который отдаёт `/metrics/summary` или аналог в `app/api/v1/`. Обнови схему ответа (Pydantic) — добавь `free_capital`, `cc_debt_compensator`, `buffer_stability`. Схема должна совпадать с тем, что возвращает `calculate_metrics_summary`.

### Шаг 9. Написать тесты

Файл `tests/test_flow_metrics_phase2.py`.

Обязательные тесты:

**9.1 Свободные средства (GAP #4):**
```python
def test_free_capital_subtracts_credit_body():
    # Пользователь, базовый +58к, ипотека тело 3к (проценты 42к уже в Базовом)
    # Ожидаем: free_capital = 55к
    ...

def test_free_capital_zero_credits():
    # Нет кредитов → free_capital = basic_flow
    ...
```

**9.2 Полный поток (балансовый Δ):**
```python
def test_full_flow_kk_purchase_no_payment():
    # Покупка 40к на КК, зарплата 100к, наличные расходы 20к, погашения нет
    # Δ дебета = +80к (100 - 20), КК долг вырос на 40к
    # Ожидаем: full_flow = +80к (не +40к)
    # Ожидаем: cc_compensator = +40к
    ...

def test_full_flow_includes_deposit():
    # Перевёл 10к на вклад, остальное без изменений
    # Ожидаем: full_flow не изменился (перевод внутри ликвидной сферы)
    ...
```

**9.3 Буфер устойчивости:**
```python
def test_buffer_stability_uses_deposit_not_regular():
    # regular: 200к, deposit: 150к, avg_expenses: 50к → buffer = 3.0 мес
    ...

def test_buffer_stability_zero_deposits():
    # Нет deposit-счетов → months = None, zone = None
    ...
```

**9.4 FI-score новые веса:**
```python
def test_fi_score_weights_v14():
    # Lifestyle 30% (savings_score=10), trend=null (capital=5),
    # DTI=25% (dti_score=5.83), buffer=3мес (buffer_score=5)
    # Ожидаем fi_score = 10*0.20 + 5*0.30 + 5.83*0.25 + 5*0.25 = 6.71 ≈ 6.7
    ...

def test_fi_score_sensitivity():
    # Смена регулярности одной категории ~15к/мес
    # не должна менять fi_score более чем на 0.5–1.0 балл
    ...
```

**9.5 Окно 12 мес:**
```python
def test_dti_uses_12_month_window():
    # Пользователь с 12 мес истории: первые 6 мес доход 100к, последние 6 мес доход 200к
    # avg за 12 мес = 150к. За 3 мес = 200к (было бы меньше DTI)
    # Проверяем, что знаменатель DTI = 150к
    ...
```

## Deliverables (чеклист)

- [ ] Окно усреднения везде изменено на 12 мес (calculate_flow, calculate_dti, get_financial_independence)
- [ ] `calculate_free_capital` реализован, возвращает free_capital и credit_body_payments
- [ ] `calculate_cc_debt_compensator` реализован
- [ ] `_calc_full_flow_for_month` переписан балансово (Δ ликвидной сферы)
- [ ] `calculate_buffer_stability` реализован (deposit / avg_expenses)
- [ ] `_calc_fi_score` обновлён: веса 0.20/0.30/0.25/0.25, использует buffer_stability
- [ ] `calculate_metrics_summary` содержит free_capital, cc_debt_compensator, buffer_stability
- [ ] API endpoint обновлён, Pydantic-схема содержит новые поля
- [ ] Тест `tests/test_flow_metrics_phase2.py` — все зелёные
- [ ] Тест чувствительности FI-score — в пределах ±1 балл

## Что НЕ входит в эту фазу

- capital_snapshots и тренд капитала (Фаза 3)
- Унификация financial_health_service (Фаза 4)
- UI-виджет (Фаза 5)

## Подводные камни

**1. Переводы ликвидный↔ликвидный в Полном потоке.**

Перевод regular→deposit (пополнение вклада) должен исключаться из расчёта: это внутреннее перемещение. Идентифицируй такие переводы: `operation_type='transfer'` AND `account_id in LIQUID` AND `target_account_id in LIQUID`. Их нетто = 0, в Полный поток не включать.

**2. account_ids по типу — кешируй на вызов.**

Запросы типов счетов (liquid_ids, credit_ids) дёргай один раз в `calculate_metrics_summary`, передавай в методы. Не делай 10 одинаковых SQL-запросов.

**3. credit_account_id vs target_account_id в переводах.**

При тело-платеже (transfer с дебета на кредит) `target_account_id = credit_account_id`. Оба поля могут быть заполнены. Для фильтра «перевод на кредитный счёт» используй `target_account_id in CREDIT_IDS`.

**4. calculate_free_capital и monthly_payment=None.**

Кредитный счёт может существовать без `monthly_payment` (например, кредитная карта без фиксированного платежа). В таком случае тело = 0 для этого счёта. Не трактуй None как дефолтный платёж.

**5. Обратная совместимость reserve.**

`calculate_reserve` оставь работать, чтобы не ломать `/health` endpoint в financial_health_service. Просто в FI-score используй buffer_stability. Унификацию health-сервиса сделаем в Фазе 4.
```

---

## После выполнения

Отчитайся о статусе чеклиста, приложи вывод тестов. Если тест чувствительности FI-score показывает > 1 балл дельты — укажи, какая категория/сколько её смена двигает.
