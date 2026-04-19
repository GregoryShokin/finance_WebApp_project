# Фаза 4 — Унификация FI-score (2026-04-19)

> Промпт для Claude Code. Выполняется ПОСЛЕ Фазы 3.
>
> **Предусловие:** Фаза 3 завершена. В `metrics_service._calc_fi_score` реализованы веса v1.4 (0.20/0.30/0.25/0.25), работает тренд капитала на снимках, DTI включает тело, Буфер устойчивости на вкладах.

**Результат фазы:** ровно один источник истины для FI-score — `MetricsService`. Два публичных endpoint (`/metrics/summary` и `/financial-health`) возвращают **одинаковый** FI-score и одинаковые компоненты для одного пользователя. Удалены дублирующиеся реализации в `financial_health_service.py`. Страница Health на фронте корректно отображает 4 компонента.

---

```
Ты выполняешь Фазу 4 внедрения мультиметрики v1.4 в FinanceApp.

## Контекст

Закрываем GAP #1 из `financeapp-vault/14-Specifications/Спецификация — Целевое состояние системы.md` § 11: сейчас существуют две параллельные реализации FI-score.

### Что есть сейчас (проверено 2026-04-19)

**Реализация 1 — `app/services/metrics_service.py::_calc_fi_score`** (верная, v1.4):
- 4 компонента: `savings_score`, `capital_score`, `dti_score`, `buffer_score`
- Веса: `0.20 + 0.30 + 0.25 + 0.25 = 1.00`
- Источники: `calculate_flow`, `calculate_capital` (с трендом из снимков), `calculate_dti`, `calculate_buffer_stability`
- Endpoint: `GET /metrics/summary`, `GET /metrics/health`

**Реализация 2 — `app/services/financial_health_service.py::get_financial_health`** (устарела):
- 5 компонентов: `savings_rate`, `discipline`, `financial_independence`, `safety_buffer`, `dti_inverse`
- Веса: `0.25 + 0.20 + 0.30 + 0.15 + 0.10 = 1.00` (НЕ v1.4)
- Endpoint: `GET /financial-health`, `GET /financial-health/{user_id}`

Два endpoint возвращают РАЗНЫЕ FI-score для одного пользователя. Это ломает когерентность продукта: число на дашборде не совпадает с числом на странице Health.

### Что оставляем в financial_health_service

НЕ всё в `financial_health_service.py` — дубликат. Часть функциональности специфична для страницы Health и не должна уходить в metrics_service:

- `discipline` и `discipline_violations` (метрика соблюдения бюджета) — остаётся
- `chronic_underperformers`, `unplanned_categories` — аналитика, остаётся
- `monthly_history` (помесячная картина для графиков Health) — остаётся
- `leverage` (долги / собственный капитал) — остаётся как отдельная метрика
- `daily_limit`, `carry_over_days` — остаётся
- `savings_rate` текущего месяца — остаётся (это `balance/income` месяца, не FI-score компонент)
- `fi_percent` (прогресс к финансовой независимости через пассивный доход) — остаётся как ОТДЕЛЬНАЯ метрика, но НЕ входит в FI-score

### Что уходит в metrics_service (остаётся истиной там)

- Формула FI-score целиком
- Нормализация компонентов (0–10)
- Зоны FI-score (freedom / path / growth / risk)

## Задача

### Шаг 1. Обновить схему `FIScoreComponents`

Файл: `app/schemas/financial_health.py`

Было:
```python
class FIScoreComponents(BaseModel):
    savings_rate: float
    discipline: float
    financial_independence: float
    safety_buffer: float
    dti_inverse: float
    months_calculated: int | None = None
    history: FIScoreHistory | None = None
```

Стало (v1.4):
```python
class FIScoreComponents(BaseModel):
    # v1.4 weights (2026-04-19): 0.20 + 0.30 + 0.25 + 0.25 = 1.00
    savings_rate: float        # вес 0.20 — нормализованный базовый поток / регулярный доход
    capital_trend: float       # вес 0.30 — траектория капитала за 3 мес.
    dti_inverse: float         # вес 0.25 — 10 - DTI/6
    buffer_stability: float    # вес 0.25 — месяцы на вкладах / 6 * 10
    months_calculated: int | None = None
    history: FIScoreHistory | None = None
```

**Важно для обратной совместимости фронта**: если какой-то компонент фронта читает `discipline` или `financial_independence` из `fi_score_components`, эти поля теперь отсутствуют. Эти метрики доступны отдельно в корне `FinancialHealthResponse` (как и раньше — см. поля `discipline`, `fi_percent`). Это осознанное изменение: они не компоненты FI-score, но остаются видимыми метриками Health.

### Шаг 2. Перевести `FinancialHealthService` на MetricsService как источник истины

Файл: `app/services/financial_health_service.py`

В методе `get_financial_health(user_id)`:

**Удалить**:
- Локальный расчёт `fi_score` (строки ~180-187 с весами `0.25/0.20/0.30/0.15/0.10`)
- Локальный расчёт `fi_score_components` (строки ~173-179)
- Метод `_fi_score_zone` — заменить на вызов `MetricsService._get_fi_zone`
- Метод `_safety_buffer_component` — заменить данными из `MetricsService.calculate_buffer_stability`

**Добавить**:

```python
from app.services.metrics_service import MetricsService

def get_financial_health(self, user_id: int) -> FinancialHealthResponse:
    # ... существующая логика для discipline, chronic, unplanned, history ...

    # НОВОЕ: FI-score и его компоненты — единый источник
    metrics_service = MetricsService(self.db)
    metrics_summary = metrics_service.calculate_metrics_summary(user_id)

    fi_score = metrics_summary["fi_score"]
    fi_score_zone = metrics_service._get_fi_zone(fi_score)

    # Пересобираем FIScoreComponents из metrics_summary
    # (числа уже нормализованы внутри _calc_fi_score, но нам нужны сами нормализованные значения)
    # Для этого вытащи в MetricsService публичный метод или рассчитай здесь
    fi_score_components = self._build_fi_score_components_v14(
        metrics_summary=metrics_summary,
        months_calculated=lookback_months,
        history=fi_score_history,
    )

    return FinancialHealthResponse(
        # ... все остальные поля (savings_rate, dti, leverage, discipline, fi_percent и т.д.) — как были ...
        fi_score=fi_score,
        fi_score_zone=fi_score_zone,
        fi_score_components=fi_score_components,
    )
```

### Шаг 3. Вытащить нормализацию компонентов в публичный метод MetricsService

Сейчас `_calc_fi_score` возвращает только итоговое число, но не промежуточные нормализованные компоненты. Нужно их отдать наружу.

В `app/services/metrics_service.py`:

```python
@dataclass
class FIScoreBreakdown:
    """Нормализованные компоненты FI-score (0..10) + итоговый балл."""
    savings_score: float      # норма сбережений (0..10)
    capital_score: float      # траектория капитала (0..10)
    dti_score: float          # DTI inverse (0..10)
    buffer_score: float       # буфер устойчивости (0..10)
    total: float              # итог по весам v1.4

def calculate_fi_score_breakdown(self, user_id: int) -> FIScoreBreakdown:
    """
    Публичный метод: возвращает нормализованные компоненты FI-score + итог.
    Используется financial_health_service для FIScoreComponents.
    """
    summary = self.calculate_metrics_summary(user_id)
    return self._build_fi_breakdown(
        flow=summary["flow"],
        capital=summary["capital"],
        dti=summary["dti"],
        buffer=summary["buffer_stability"],
    )

def _build_fi_breakdown(self, flow, capital, dti, buffer) -> FIScoreBreakdown:
    # То, что сейчас в _calc_fi_score, но возвращает все промежуточные значения
    ...
```

`_calc_fi_score` оставь как внутренний метод (он возвращает только total).

В `FinancialHealthService._build_fi_score_components_v14`:

```python
def _build_fi_score_components_v14(
    self, metrics_summary, months_calculated, history
) -> FIScoreComponents:
    metrics_service = MetricsService(self.db)
    breakdown = metrics_service.calculate_fi_score_breakdown(metrics_summary["user_id"])
    return FIScoreComponents(
        savings_rate=breakdown.savings_score,
        capital_trend=breakdown.capital_score,
        dti_inverse=breakdown.dti_score,
        buffer_stability=breakdown.buffer_score,
        months_calculated=months_calculated,
        history=history,
    )
```

Убедись, что `calculate_metrics_summary` возвращает user_id в результате (или меняй сигнатуру `calculate_fi_score_breakdown`, чтобы принимала готовый metrics_summary).

### Шаг 4. Удалить устаревшие методы

В `financial_health_service.py` удалить:
- `_savings_rate_component` (если он только про FI-score v1.0)
- `_discipline_component` (если он только про FI-score v1.0, а не про саму метрику дисциплины)
- `_financial_independence_component` (аналогично)
- `_safety_buffer_component`
- `_dti_inverse_component`
- `_fi_score_zone` — заменён на `MetricsService._get_fi_zone`

**Не трогать**:
- `_discipline_metrics` (сама метрика дисциплины) — остаётся
- `_current_month_passive_income` — для fi_percent
- `_calc_dti_payments` — уже исправлен в Фазе 3 (body + interest)
- `_current_capital_snapshot` — для leverage (не путать с capital_snapshots таблицей из Фазы 3!)

### Шаг 5. Обновить `FIScoreHistory`

В `_build_fi_score_history` — убрать параметры `discipline`, `fi_percent`, `safety_buffer_score` (они больше не компоненты). Использовать те же 4 компонента, что и в v1.4:

```python
def _build_fi_score_history(
    self,
    *,
    savings_score: float,
    capital_score: float,
    dti_score: float,
    buffer_score: float,
) -> dict:
    current = round(savings_score * 0.20 + capital_score * 0.30 + dti_score * 0.25 + buffer_score * 0.25, 1)
    # previous, baseline — подтягивать из снимков (Фаза 3 уже даёт историю)
    ...
```

Если `previous` и `baseline` исторически считались по старым формулам — пересчитай или оставь `current` как единственное значение, пока не накопится 3 мес. истории по новой формуле.

### Шаг 6. Обновить MonthlyHealthSnapshot

Файл: `app/schemas/financial_health.py` — `MonthlyHealthSnapshot`.

Поле `fi_score: float` внутри снимка помесячной истории — тоже должно считаться по v1.4. В `_build_monthly_history` в `financial_health_service.py` для каждого снимка прошлого месяца вызывай тот же алгоритм (через `MetricsService._build_fi_breakdown` с параметрами прошлого месяца).

**Осторожно:** для прошлых месяцев `capital_score` требует исторических снимков капитала. После Фазы 3 они есть (backfill-скрипт их восполняет). Если снимков за месяц нет — `capital_score = 5.0` (нейтральный), фиксируй это в поле флагом.

### Шаг 7. Обновить фронт страницы Health

Файлы: `frontend/app/(app)/health/`, `frontend/components/...` — найди компонент, отображающий кольцо FI-score и его компоненты.

Текущие компоненты в UI (5 штук):
- Норма сбережений
- Дисциплина
- Финансовая независимость
- Подушка безопасности
- DTI

Новые компоненты (4 штуки):
- Норма сбережений (savings_rate)
- Траектория капитала (capital_trend) — новое
- DTI inverse (dti_inverse)
- Буфер устойчивости (buffer_stability)

Убери `Дисциплина` и `Финансовая независимость` из кольца/разбивки FI-score. Они остаются отдельными виджетами на странице Health (читаются из `discipline` и `fi_percent` корня ответа — они не в `fi_score_components`).

Обнови тексты-подсказки для каждого компонента.

### Шаг 8. Тесты

`tests/test_fi_score_unification.py`:

```python
def test_fi_score_consistent_across_endpoints(client, test_user):
    """
    /metrics/summary и /financial-health возвращают одинаковый fi_score
    для одного пользователя в одной сессии.
    """
    r1 = client.get("/api/v1/metrics/summary", headers=auth_headers(test_user))
    r2 = client.get("/api/v1/financial-health", headers=auth_headers(test_user))
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["fi_score"] == r2.json()["fi_score"]


def test_fi_score_components_v14(test_user, db):
    """Компоненты FI-score — 4 штуки с весами v1.4."""
    service = FinancialHealthService(db)
    result = service.get_financial_health(test_user.id)
    assert hasattr(result.fi_score_components, 'savings_rate')
    assert hasattr(result.fi_score_components, 'capital_trend')
    assert hasattr(result.fi_score_components, 'dti_inverse')
    assert hasattr(result.fi_score_components, 'buffer_stability')
    assert not hasattr(result.fi_score_components, 'discipline')
    assert not hasattr(result.fi_score_components, 'financial_independence')


def test_fi_score_weights_sum_to_one():
    """Веса v1.4 в сумме = 1.00."""
    # 0.20 + 0.30 + 0.25 + 0.25 = 1.00
    total = 0.20 + 0.30 + 0.25 + 0.25
    assert abs(total - 1.0) < 1e-9


def test_fi_score_manual_calculation():
    """Проверяем расчёт FI-score на конкретных числах."""
    # Пользователь: savings 30% → 10, capital trend растёт → 8, DTI 24% → 6, buffer 4 мес → 6.67
    # fi_score = 10*0.20 + 8*0.30 + 6*0.25 + 6.67*0.25 = 2 + 2.4 + 1.5 + 1.67 = 7.57 ≈ 7.6
    ...


def test_discipline_and_fi_percent_still_in_response():
    """discipline и fi_percent остаются в ответе, но не в fi_score_components."""
    # ...
```

## Deliverables (чеклист)

### Бэкенд
- [ ] `FIScoreComponents` схема обновлена: 4 компонента v1.4
- [ ] `FinancialHealthService.get_financial_health` вызывает `MetricsService.calculate_fi_score_breakdown` для FI-score
- [ ] Метод `calculate_fi_score_breakdown` вынесен в публичный API `MetricsService`
- [ ] Удалены устаревшие `_savings_rate_component`, `_financial_independence_component`, `_safety_buffer_component`, `_dti_inverse_component`, `_fi_score_zone` в `financial_health_service`
- [ ] `_build_fi_score_history` использует 4 компонента v1.4
- [ ] `MonthlyHealthSnapshot.fi_score` для прошлых месяцев считается через `MetricsService` с историческими снимками капитала

### Фронт
- [ ] Кольцо FI-score на странице Health показывает 4 компонента (savings / capital_trend / dti / buffer)
- [ ] `discipline` и `fi_percent` остались как отдельные виджеты на странице Health, но не в кольце FI-score
- [ ] Тексты подсказок обновлены под новые компоненты

### Тесты
- [ ] `test_fi_score_consistent_across_endpoints` — зелёный
- [ ] `test_fi_score_components_v14` — зелёный
- [ ] `test_fi_score_weights_sum_to_one` — зелёный
- [ ] `test_fi_score_manual_calculation` — зелёный (совпадает с ручным расчётом на бумаге)
- [ ] `test_discipline_and_fi_percent_still_in_response` — зелёный

### Миграция/совместимость
- [ ] Не ломает существующие поля `FinancialHealthResponse` (кроме `fi_score_components` — это осознанное изменение схемы)
- [ ] В changelog / CLAUDE.md: отмечено, что `fi_score_components.discipline` и `.financial_independence` удалены

## Что НЕ входит

- UI-виджет Потока с тремя табами (Фаза 5)
- Переработка дашборда — убрать СМО-виджет, добавить буфер (Фаза 6)
- Удаление `financial_health_service` целиком (откладывается; слияние в один сервис — техдолг, можно сделать после Фазы 6)

## Подводные камни

**1. `FinancialHealthService` большой (1124 строки)** — там много специфичных для Health вещей: discipline, monthly_history, chronic_underperformers. Не пытайся их перенести в `metrics_service`, оставь как есть. Задача Фазы 4 — только FI-score. Остальное — в будущих рефакторингах.

**2. Кольцо FI-score на фронте может быть глубоко завязано на 5 компонентов.** Если в компоненте жёстко прописано `.discipline`, `.financial_independence` — TypeScript сразу покажет ошибку после обновления типа. Это нормально, пройди по всем точкам и обнови.

**3. `fi_percent` ≠ `financial_independence` компонент FI-score.** `fi_percent` — это прогресс к полной финансовой независимости (пассивный доход / расходы × 100%), отдельная метрика. В старой формуле FI-score она была компонентом с весом 0.30. В v1.4 её в FI-score нет — она живёт отдельно на странице Health как самостоятельный виджет (обычно прогресс-бар). Не путай эти две сущности при удалении.

**4. `MonthlyHealthSnapshot` для старых месяцев.** Если пользователь открывает Health и смотрит на историю 6 мес., каждый снимок показывает свой `fi_score`. После Фазы 4 эти старые значения не пересчитываются — они такие, какими были на момент первого расчёта. Решение: либо перечитывай через `MetricsService` с передачей `as_of=month_date` (требует поддержки исторического расчёта в metrics_service — это сложно), либо помечай старые снимки флагом `is_legacy_formula` и при необходимости пересчитай через one-off скрипт после Фазы 4. Рекомендую: скрипт `scripts/recompute_fi_score_history.py`, запустить один раз после деплоя.

**5. `discipline` и `_discipline_metrics`.** Логику подсчёта дисциплины НЕ трогай — это самостоятельная метрика. Удаляй только её участие в расчёте FI-score.

**6. MetricsService сейчас не умеет считать FI-score для прошлого месяца.** Его публичный `calculate_metrics_summary(user_id)` всегда возвращает ТЕКУЩЕЕ состояние. Для исторического FI-score (в `monthly_history`) нужно либо:
- расширить `calculate_metrics_summary(user_id, as_of: date | None)` — чтобы принимал точку во времени и считал на неё метрики
- оставить в `financial_health_service` локальный расчёт для истории, но по ТЕМ ЖЕ формулам v1.4 (скопировать вспомогательный метод из MetricsService)

Первый путь чище, но требует инвазивных изменений в MetricsService. Второй — прагматичный, сохраняет разделение слоёв. Рекомендую ВТОРОЙ: в `financial_health_service._build_monthly_history` добавь вызов `MetricsService._build_fi_breakdown` с данными за соответствующий месяц (придётся сделать этот метод чистой функцией без зависимости от текущей даты).

## После выполнения

Отчитайся:
- Количество удалённых методов в `financial_health_service.py` (ожидаю 4-6)
- Количество изменённых файлов фронта
- Вывод `test_fi_score_consistent_across_endpoints` — должен показать, что оба endpoint возвращают один и тот же float
- Ручная проверка: открыть `/dashboard` и `/health` — FI-score одинаковый?
```

---

## После выполнения Фазы 4

Следующие этапы:
- **Фаза 5** — виджет Потока на фронте (порт `trilayer-flow-widget.html` в компонент)
- **Фаза 6** — остальные виджеты дашборда (убрать MonthlyAvgBalanceCard, обновить Буфер)
- **Фаза 7** — финальная чистка `/dashboard` vs `/dashboard-new` техдолга
