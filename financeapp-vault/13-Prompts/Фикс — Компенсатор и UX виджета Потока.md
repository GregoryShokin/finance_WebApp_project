# Фикс — Компенсатор КК и UX виджета Потока (2026-04-19)

> Промпт для Claude Code. Единый фикс, закрывает:
> 1. Концептуальный баг в формуле компенсатора (даёт двойной учёт при частичном погашении)
> 2. Шесть UX-багов в `flow-widget.tsx`, найденных при ревью
>
> **Предусловие:** Фазы 1-5 завершены. Виджет Потока работает на `/dashboard-new` на тестовых данных.

---

## Зачем этот фикс

### Баг A (критичный): компенсатор ломает математику декомпозиции

Сейчас `_calc_cc_debt_compensator_from_txns` возвращает **Δ долга по КК** (покупки − погашения − досрочные). Это концептуально неверно. Компенсатор в декомпозиции виджета должен объяснять **один источник расхождения** — когда расход записан, но кэш не ушёл с ликвидных счетов (покупка на КК). Погашение долга КК — **другой, независимый** источник расхождения, и он уже отражён строкой `credit_body_payments` (transfer к кредитному счёту).

Текущая формула `Δ долга = покупки − погашения` вычитает погашения **дважды** — один раз в `credit_body`, второй раз внутри компенсатора.

**Пример (частичное погашение):**

Пользователь в апреле:
- Зарплата 100к на дебет
- Обычные расходы 20к с дебета
- Покупка мебели 40к на КК
- Погашение 30к с дебета на КК (transfer)
- Инвестиция 10к

**Реально:** Δ дебета = +100 − 20 − 30 − 10 = **+40к**.

Декомпозиция:

| Строка | Сумма |
|---|---:|
| Доходы | +100 |
| Расходы (включая 40 КК) | −60 |
| Тело кредитных платежей | −30 |
| Покупки инвестиций | −10 |
| Компенсатор (по текущей формуле: 40 − 30 = 10) | +10 |
| **Сумма** | **+10** ❌ |

Сумма (+10) не совпадает с Δ кэша (+40). Разрыв 30к = погашение, учтённое дважды.

**Правильная формула:**
```
compensator = Σ(expense, account_id ∈ {credit_card, installment_card})
```

Только покупки на КК. **Всегда ≥ 0.** Погашения остаются в `credit_body_payments`.

С правильной формулой: `compensator = 40`. Сумма декомпозиции: 100 − 60 − 30 − 10 + 40 = **+40к** = Δ кэша ✓

### Багы B–G (UX в `flow-widget.tsx`): см. ниже в шагах

---

## Задача

### Шаг 1. Починить формулу компенсатора на бэкенде

**Файл:** `app/services/metrics_service.py`

Найти `_calc_cc_debt_compensator_from_txns` (примерно строка 579).

Было:
```python
def _calc_cc_debt_compensator_from_txns(
    self,
    txns: list[Transaction],
    cc_account_ids: set[int],
) -> Decimal:
    """
    Прирост долга по КК за период = компенсатор для декомпозиции Полного потока.

    = + Σ(expense, account_id in CC)
      − Σ(transfer, target_account_id in CC)
      − Σ(credit_early_repayment, credit_account_id in CC)
    """
    if not cc_account_ids:
        return Decimal("0")

    total = Decimal("0")
    for tx in txns:
        amount = Decimal(str(tx.amount))
        op = tx.operation_type
        if op == "regular" and tx.type == "expense" and tx.account_id in cc_account_ids:
            total += amount
        elif op == "transfer" and tx.target_account_id in cc_account_ids:
            total -= amount
        elif op == "credit_early_repayment" and (
            tx.credit_account_id in cc_account_ids or tx.target_account_id in cc_account_ids
        ):
            total -= amount
    return _round2(total)
```

Стало:
```python
def _calc_cc_debt_compensator_from_txns(
    self,
    txns: list[Transaction],
    cc_account_ids: set[int],
) -> Decimal:
    """
    Компенсатор для декомпозиции Полного потока = сумма покупок с КК за период.

    Назначение: объясняет расхождение между "записано как расход" и "ушло с ликвидных счетов".
    Покупка на КК (account_id = credit_card) записана как expense, но ликвидный баланс
    пользователя не уменьшился — изменился только долг на кредитке.

    Погашение КК (transfer к кредитному счёту) НЕ входит в компенсатор — оно уже отражено
    в строке "Тело кредитных платежей" (credit_body_payments) декомпозиции.

    Формула: compensator = Σ(amount  где  account_id ∈ {credit_card, installment_card}  и  type='expense')

    Свойства:
      - Всегда ≥ 0 (покупки не могут быть отрицательными)
      - Ноль, если пользователь не делал покупок на КК в периоде
      - Максимально равен сумме всех покупок на КК

    Ref: financeapp-vault/01-Metrics/Поток.md, решение 2026-04-19.
    """
    if not cc_account_ids:
        return Decimal("0")

    total = Decimal("0")
    for tx in txns:
        if tx.type == "expense" and tx.account_id in cc_account_ids:
            total += Decimal(str(tx.amount))
    return _round2(total)
```

**Важно:** `cc_account_ids` уже включает и `credit_card`, и `installment_card` — см. `CREDIT_CARD_TYPES = {"credit_card", "installment_card"}` (строка 57 файла) и `accounts["credit_card"]` содержит оба (строка 266). Ничего дополнительно фильтровать не нужно.

### Шаг 2. Обновить тесты на бэкенде

**Файл:** `tests/test_flow_metrics_phase2.py` (или `test_capital_snapshots.py` — где лежат тесты Полного потока; проверь `grep -l "cc_debt_compensator\|test_full_flow" tests/`).

Найти `test_full_flow_kk_purchase_no_payment`. Это текущий сценарий — покупка на КК без погашения. Он должен продолжать работать после правки (40к покупок → компенсатор 40к).

Добавить **новый тест** — сценарий с частичным погашением, ловящий баг:

```python
def test_compensator_partial_repayment_no_double_counting():
    """
    Баг 2026-04-19: компенсатор НЕ ДОЛЖЕН вычитать погашения.
    Погашения уже отражены через credit_body_payments (transfer к credit счёту).
    Если компенсатор тоже их вычтет — двойной учёт и разрыв декомпозиции.
    """
    # Setup: user with regular debit + credit_card
    user = ...
    debit = _create_account(user, "regular", balance=0)
    cc = _create_account(user, "credit_card", balance=0, credit_limit=100000)

    month_date = date(2026, 4, 1)

    # Transactions in April:
    _create_tx(user, type="income", amount=100000, account_id=debit.id,
               operation_type="regular", date=month_date)
    _create_tx(user, type="expense", amount=20000, account_id=debit.id,
               operation_type="regular", date=month_date)
    # Purchase on CC: 40k
    _create_tx(user, type="expense", amount=40000, account_id=cc.id,
               operation_type="regular", date=month_date)
    # Partial repayment: 30k transfer debit → cc
    _create_tx(user, type="expense", amount=30000, account_id=debit.id,
               target_account_id=cc.id, operation_type="transfer", date=month_date)

    service = MetricsService(db)

    # Compensator — только покупки на КК = 40k, НЕ 10k (Δ долга)
    compensator = service.calculate_cc_debt_compensator(user.id, 2026, 4)
    assert compensator == Decimal("40000"), (
        f"Компенсатор должен быть 40k (только покупки), а не {compensator} "
        f"(это бы значило, что погашения вычтены — двойной учёт)."
    )

    # Δ ликвидного кэша = +100 - 20 - 30 = +50k (investment 10k не учтён в этом минимальном кейсе)
    summary = service.calculate_metrics_summary(user.id)
    # Проверить, что full_flow совпадает с Δ кэша
    assert summary["flow"]["full_flow"] == Decimal("50000")
    # И что компенсатор = 40k
    assert summary["flow"]["cc_debt_compensator"] == Decimal("40000")

    # Проверить замкнутость декомпозиции:
    # all_income - all_expenses - credit_body - investments + compensator = full_flow
    # all_income = 100
    # all_expenses = 60 (20 dbt + 40 cc)
    # credit_body = 30
    # compensator = 40
    # 100 - 60 - 30 + 40 = 50 ✓
```

Убедись, что существующие тесты всё ещё зелёные. Если какой-то тест ожидал `compensator = Δ долга` — исправь его под новое поведение или добавь отдельный `test_legacy_*` (не рекомендую, лучше обновить).

### Шаг 3. Обновить методологический раздел в Поток.md

**Файл:** `financeapp-vault/01-Metrics/Поток.md`

Найти блок «Декомпозиция в виджете (путь Б, решение 2026-04-19)» (строки ~125-145).

Было:
```
**Строка «Прирост долга по кредиткам»** считается балансово:

```
compensator = Σ(долг_КК_конец − долг_КК_начало) по всем credit_card/installment_card счетам
```
```

Стало:
```
**Строка «Прирост долга по кредиткам»** считается как сумма покупок на КК за период:

```
compensator = Σ(amount  где  account_id ∈ {credit_card, installment_card}  и  type='expense')
```

Свойства:
- **Всегда ≥ 0** — покупки не могут быть отрицательными
- Ноль, если пользователь не использовал КК в периоде
- Погашения КК **НЕ** входят в компенсатор — они уже учтены в строке «Тело кредитных платежей» (`credit_body_payments`)

**Почему не Δ долга по балансам.** Кажется интуитивным использовать «Δ долга = покупки − погашения», но это даёт двойной учёт: погашения уже отражены через `transfer к credit_account_id` (попадают в `credit_body_payments`). Вычитание их ещё и из компенсатора ломает замкнутость: `сумма_строк ≠ Δ кэша` при частичном погашении.

**Пример** (частичное погашение): зарплата 100к, расходы 20к с дебета, покупка 40к на КК, погашение 30к. Δ дебета = +50к.

| Метод | Компенсатор | Сумма декомпозиции | Совпадает с Δ кэша? |
|---|:---:|:---:|:---:|
| Δ долга (неверный) | +10 (40−30) | 100 − 60 − 30 + 10 = **+20** | ❌ разрыв 30к |
| Σ покупок на КК (верный) | +40 | 100 − 60 − 30 + 40 = **+50** | ✓ сходится |
```

И в разделе «История решений» (в конце файла) добавить:
```
- **2026-04-19** — уточнена формула компенсатора: Σ покупок на КК, не Δ долга. Старая формула давала двойной учёт погашений.
```

### Шаг 4. Фронтенд — убрать ветки отрицательного компенсатора

**Файл:** `frontend/components/dashboard-new/flow-widget.tsx`

После правки формулы на бэкенде `cc_debt_compensator` никогда не будет отрицательным. Убрать обработку отрицательного случая.

**Строки 266-268** (внутри логики Полного таба):
```typescript
// Было:
if (compensator < 0) {
  innerSegs.push({ color: COLORS.amber, value: Math.abs(compensator), label: 'Погашение долга КК' });
}

// Стало: удалить этот блок целиком.
```

**Строки 417-424** (в декомпозиции Полного):
```typescript
// Было:
{data.ccCompensator > 0 ? (
  <RowItem color={COLORS.amber} label="Прирост долга по кредиткам" ... />
) : data.ccCompensator < 0 ? (
  <RowItem color={COLORS.amber} label="Погашение долга по кредиткам" ... />
) : null}

// Стало:
{data.ccCompensator > 0 ? (
  <RowItem
    color={COLORS.amber}
    label="Покупки в кредит"
    sub="записано как расход, но кэш не ушёл"
    amount={data.ccCompensator}
  />
) : null}
```

Обрати внимание: поменялся и **лейбл** строки. «Прирост долга по кредиткам» — неточный заголовок (это не Δ долга). Правильнее «Покупки в кредит» или «Расходы через кредитку».

### Шаг 5. Фронтенд — остальные UX-фиксы

Всё в том же файле `frontend/components/dashboard-new/flow-widget.tsx`.

#### 5.1 Баг B: Полный в дефиците показывает «нейтральную» подсказку

Строки 302-308:
```typescript
// Было:
} else {
  hintTone = 'neutral';
  if (data.ccCompensator > 0) {
    ...
  } else {
    hintText = `На счетах ${formatRub(data.fullFlow)} за месяц.`;
  }
}

// Стало:
} else {
  if (data.fullFlow < 0) {
    hintTone = 'deficit';
    hintText = `На счетах ${formatRub(data.fullFlow)} за месяц. Крупная покупка, досрочное погашение или превышение обязательств.`;
  } else if (data.ccCompensator > 0) {
    hintTone = 'neutral';
    const realGrowth = data.fullFlow - data.ccCompensator;
    hintText = `На счетах ${formatRub(data.fullFlow)}. Из них ${formatRub(data.ccCompensator)} — покупки в кредит (погасятся в следующем месяце). Реальный прирост своих: ${formatRub(realGrowth)}.`;
  } else {
    hintTone = 'neutral';
    hintText = `На счетах ${formatRub(data.fullFlow)} за месяц.`;
  }
}
```

#### 5.2 Баг C: смешанные `strokeLinecap`

Строки 344-347 (фоновые треки): заменить `strokeLinecap="round"` на `strokeLinecap="butt"`:

```typescript
// Было:
<circle ... strokeDasharray={`${OUTER_MAX} ${OUTER_CIRC}`} strokeLinecap="round" />
<circle ... strokeDasharray={`${INNER_MAX} ${INNER_CIRC}`} strokeLinecap="round" />

// Стало:
<circle ... strokeDasharray={`${OUTER_MAX} ${OUTER_CIRC}`} strokeLinecap="butt" />
<circle ... strokeDasharray={`${INNER_MAX} ${INNER_CIRC}`} strokeLinecap="butt" />
```

Теперь все края (и треков, и сегментов) будут прямыми — однородный «спидометр».

#### 5.3 Баг D: `lifestyle === null` в Базовом

Строки 282-292:
```typescript
// Было:
if (tab === 'basic') {
  if (data.lifestyle !== null && data.basicFlow >= 0 && data.zone === 'healthy') {
    hintTone = 'healthy';
    hintText = `${data.lifestyle}% дохода остаётся после регулярных трат. Образ жизни устойчив.`;
  } else if (data.zone === 'tight' || (data.lifestyle !== null && data.basicFlow >= 0)) {
    hintTone = 'tight';
    hintText = `После трат остаётся ${data.lifestyle ?? 0}% дохода. Одна непредвиденная трата выведет в минус.`;
  } else {
    hintTone = 'deficit';
    hintText = `Регулярные расходы превышают доход на ${formatRub(Math.abs(data.basicFlow))}/мес. Сократи второстепенные.`;
  }
}

// Стало — упрощённая и корректная логика:
if (tab === 'basic') {
  if (data.basicFlow < 0) {
    hintTone = 'deficit';
    hintText = `Регулярные расходы превышают доход на ${formatRub(Math.abs(data.basicFlow))}/мес. Сократи второстепенные.`;
  } else if (data.lifestyle === null) {
    hintTone = 'neutral';
    hintText = 'Показатель уровня жизни уточнится, когда накопится 12 месяцев истории.';
  } else if (data.lifestyle < 20) {
    hintTone = 'tight';
    hintText = `После трат остаётся ${data.lifestyle}% дохода. Одна непредвиденная трата выведет в минус.`;
  } else {
    hintTone = 'healthy';
    hintText = `${data.lifestyle}% дохода остаётся после регулярных трат. Образ жизни устойчив.`;
  }
}
```

Порядок проверок: сначала дефицит (главное), потом null (специальный случай), потом значения.

#### 5.4 Баг E: центрирование текста в SVG

Строки 351-368:
```typescript
// Было:
<text
  x={120}
  y={118}
  textAnchor="middle"
  className="fill-slate-900"
  style={{ fontSize: 22, fontWeight: 700 }}
>
  {formatCenter(centerAmount)}
</text>
<text
  x={120}
  y={138}
  textAnchor="middle"
  className="fill-slate-400"
  style={{ fontSize: 10, letterSpacing: 2 }}
>
  {centerLabel}
</text>

// Стало — используем dominantBaseline для точного центрирования:
<text
  x={120}
  y={117}
  textAnchor="middle"
  dominantBaseline="middle"
  className="fill-slate-900"
  style={{ fontSize: 22, fontWeight: 700 }}
>
  {formatCenter(centerAmount)}
</text>
<text
  x={120}
  y={140}
  textAnchor="middle"
  dominantBaseline="middle"
  className="fill-slate-400"
  style={{ fontSize: 10, letterSpacing: 2 }}
>
  {centerLabel}
</text>
```

Точный y-coord подбирается визуально — протестируй в браузере. Главное — `dominantBaseline="middle"`.

#### 5.5 Баг F: Полоска инвестиций в Полном всегда 100% — выглядит странно

Строки 426-434:
```typescript
// Было:
{breakdown.investmentBuy > 0 ? (
  <InvestmentBar
    value={breakdown.investmentBuy}
    total={breakdown.investmentBuy}
    label="Реальные инвестиции за период"
    hint="Без вкладов"
    forceFull
  />
) : null}

// Стало: удалить этот блок. В Полном табе инвестиции уже видны строкой
// "Покупки инвестиций" в декомпозиции — полоска дублирует и вводит в
// заблуждение (100% выглядит как "цель достигнута").
```

Полоска инвестиций остаётся только в Свободном табе, где есть знаменатель `free_capital` и процент осмыслен.

### Шаг 6. Визуальная проверка в браузере

После всех правок:

```bash
cd frontend && npm run dev
# Открыть http://localhost:3000/dashboard-new
```

Проверки:
- [ ] Переключение трёх табов работает без мерцаний
- [ ] Треки и сегменты колец теперь одного стиля (butt caps)
- [ ] Текст в центре доната — визуально по центру круга
- [ ] Если у тебя есть покупки на КК — видна amber-полоска в Полном, декомпозиция строкой «Покупки в кредит» ({сумма покупок})
- [ ] Если `full_flow < 0` — подсказка Полного КРАСНАЯ (deficit), не серая
- [ ] Если `lifestyle_indicator === null` — подсказка Базового НЕЙТРАЛЬНАЯ с текстом «уточнится когда накопится 12 мес»
- [ ] В Полном табе НЕТ полоски инвестиций (только строка в декомпозиции)
- [ ] Математика сходится: сумма строк декомпозиции Полного = центральное число

Для ручной проверки математики: если у тебя есть пользователь с покупками КК **и** погашениями в одном месяце — проверь, что `центр ≈ сумма строк` (может быть лёгкое расхождение на копейки из-за округления).

## Deliverables (чеклист)

### Бэкенд
- [ ] `_calc_cc_debt_compensator_from_txns` — формула упрощена до Σ(expense на CC)
- [ ] Docstring обновлён с объяснением почему не Δ долга
- [ ] Тест `test_compensator_partial_repayment_no_double_counting` — зелёный
- [ ] Существующие тесты Фазы 2 — зелёные (ничего не сломали)

### Документация
- [ ] `financeapp-vault/01-Metrics/Поток.md` — раздел «Декомпозиция в виджете» обновлён с новой формулой и примером
- [ ] В «История решений» добавлена запись 2026-04-19 про уточнение

### Фронтенд — `flow-widget.tsx`
- [ ] Убрана ветка `compensator < 0` в кольцах (строка ~266)
- [ ] Убрана ветка `ccCompensator < 0` в декомпозиции (строки ~417-424)
- [ ] Переименована строка «Прирост долга по кредиткам» → «Покупки в кредит»
- [ ] Полный в дефиците — подсказка теперь `deficit` (rose), не `neutral`
- [ ] `strokeLinecap="butt"` везде (и треки, и сегменты)
- [ ] `lifestyle === null` обрабатывается отдельной веткой (neutral с текстом про 12 мес)
- [ ] Логика Базового упрощена (сначала deficit, потом null, потом значения)
- [ ] `dominantBaseline="middle"` в SVG text
- [ ] Полоска инвестиций удалена из Полного таба (остаётся только в Свободном)
- [ ] `npm run build` — 0 TypeScript ошибок
- [ ] Ручная проверка в браузере: все переключения работают, математика сходится

## Что НЕ входит

- CTA-ссылки на модули школы в красных зонах (школа пока не реализована — оставим на этап 8+)
- Упрощение UX-вопроса про разные источники данных (центр из API, кольца из транзакций) — это отдельный техдолг
- Tooltip при наведении на сегменты доната

## После выполнения

Отчитайся:
- Численный вывод теста `test_compensator_partial_repayment_no_double_counting`
- Скриншот / описание виджета в трёх табах для тестового пользователя с частичным погашением
- Подтверждение: сумма строк декомпозиции = центральное число во всех трёх табах
