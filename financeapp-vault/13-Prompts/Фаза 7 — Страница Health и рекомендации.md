# Фаза 7 — Страница Health: рекомендации и доработка UI (2026-04-19)

> Промпт для Claude Code. Выполняется ПОСЛЕ Фазы 6.
>
> **Предусловие:** Фаза 4 обновила FI-score на 4 компонента v1.4, страница Health отображает `capital_trend` и `buffer_stability` вместо `discipline` и `financial_independence` в кольце. Фазы 1-6 завершены.

**Результат фазы:** страница Health (`/health`) полностью использует данные из `/metrics/health` endpoint для рекомендаций и зон. Блок «Приоритетные шаги» подключён к `recommendations` из MetricsService. Раздел DTI на странице Health использует правильные значения после Фаз 1-4. Тест-прогон страницы в браузере проходит без ошибок.

---

```
Ты выполняешь Фазу 7. Целевая страница: `frontend/app/(app)/health/page.tsx`.

## Что сейчас

Страница Health получает данные через `useFinancialHealth()` (endpoint `/financial-health`).
Также существует endpoint `/metrics/health` (GET), который возвращает:

```json
{
  "metrics": { "flow": {...}, "capital": {...}, "dti": {...}, "buffer_stability": {...}, "fi_score": ... },
  "fi_score": 7.2,
  "fi_zone": "path",
  "weakest_metric": "dti",
  "recommendations": [
    { "metric": "dti", "zone": "danger", "priority": 1, "title": "Высокая кредитная нагрузка", "message": "..." }
  ]
}
```

Это данные из `MetricsService.calculate_health_summary()` — единственный источник истины для рекомендаций.

## Задача

### Шаг 1. Добавить хук useHealthSummary

Файл: `frontend/hooks/use-health-summary.ts`

```typescript
import { useQuery } from '@tanstack/react-query';
import { getHealthSummary, type HealthSummary } from '@/lib/api/metrics';

export function useHealthSummary() {
  return useQuery({
    queryKey: ['metrics', 'health-summary'],
    queryFn: getHealthSummary,
    staleTime: 5 * 60 * 1000,
  });
}
```

### Шаг 2. Подключить блок «Приоритетные шаги»

Сейчас «Приоритетные шаги» в `health/page.tsx` либо захардкожены, либо берутся из `currentHealth` (FinancialHealth). Переключи их на `HealthSummary.recommendations`:

```typescript
import { useHealthSummary } from '@/hooks/use-health-summary';

// В компоненте:
const healthSummaryQuery = useHealthSummary();
const healthSummary = healthSummaryQuery.data;

// Рендер приоритетных шагов:
{healthSummary?.recommendations.map((rec) => (
  <div key={rec.message_key} className="rounded-2xl border border-slate-200 bg-white p-4">
    <div className="font-semibold text-slate-900 text-sm">{rec.title}</div>
    <div className="text-sm text-slate-500 mt-1">{rec.message}</div>
  </div>
))}
{(!healthSummary || healthSummary.recommendations.length === 0) && (
  <div className="text-sm text-slate-400">Нет критичных показателей — всё в норме.</div>
)}
```

### Шаг 3. Проверить блок DTI на странице Health

Сейчас: страница отображает `currentHealth.dti` из `/financial-health`.
После Фазы 3 DTI включает тело кредитных платежей — значит `/financial-health` тоже должен показывать правильный DTI (т.к. `FinancialHealthService` вызывает `MetricsService` — GAP #1 закрыт в Фазе 4).

Проверить: числа DTI на странице Health == числам из `/metrics/summary` (проверить через DevTools → Network).

Если расходятся — добавить `healthSummary?.metrics.dti.dti_percent` как приоритетный источник для отображения DTI на странице Health, оставив `/financial-health` как fallback.

### Шаг 4. Убедиться что FI-score история работает

В `health/page.tsx` ищи компонент с историей FI-score (скорее всего это график по месяцам или блок `fi_score_components.history`). После Фазы 4 история переписана под v1.4 формулу. Проверь:

- Открыть /health в браузере
- История FI-score (если показывается) — не пустая, числа в разумных пределах (0-10)
- Если история пустая (не накоплено снимков после Фазы 3 backfill-скрипта) — убедись что запустился `scripts/backfill_capital_snapshots.py`

### Шаг 5. Мелкие UX-доработки

Найди в `health/page.tsx` все места где упоминаются:
- `financial_independence` или `fi_percent` как **компонент FI-score** (не как отдельная метрика) — убрать из кольца, если вдруг остались
- `discipline` как **компонент FI-score** — то же самое (Фаза 4 должна была убрать, проверь)
- `safety_buffer` как **компонент FI-score** — заменено `buffer_stability`, проверь что правильное поле читается

Если всё уже сделано в Фазе 4 — пропустить.

### Шаг 6. Добавить обработку состояния загрузки

Если `healthSummaryQuery.isLoading` — показывать скелетон в блоке «Приоритетные шаги» вместо пустого места.

## Deliverables (чеклист)

- [ ] `use-health-summary.ts` создан
- [ ] Блок «Приоритетные шаги» на странице Health берёт данные из `HealthSummary.recommendations`
- [ ] FI-score кольцо содержит ровно 4 компонента (savings_rate, capital_trend, dti_inverse, buffer_stability)
- [ ] DTI на странице Health совпадает с `/metrics/summary` (проверено в DevTools)
- [ ] История FI-score — не пустая (либо данные есть, либо отображается заглушка «Накапливаем историю...»)
- [ ] `npm run build` — 0 ошибок
- [ ] Ручная проверка в браузере: страница /health открывается, все блоки загружены, нет NaN или undefined в числах

## Что НЕ входит

- Переработка дизайна страницы Health (только подключение правильных данных)
- Редирект /dashboard → /dashboard-new (Фаза 8)
```
