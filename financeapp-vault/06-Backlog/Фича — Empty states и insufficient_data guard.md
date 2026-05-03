# Фича — Empty states и insufficient_data guard
#бэклог #высокий-приоритет #ux
> Когда у юзера <30 транзакций или <3 завершённых месяцев, метрики не должны показывать посчитанные-на-пустой-выборке значения.
---
## Проблема (2026-05-03)
Сейчас при пустом аккаунте:
- Dashboard / Health / Planning / Goals покажут метрики посчитанные на 0-1 месяце данных → числа странные, тренды бессмысленные, FI-score 0/10.
- Юзер видит «у меня всё плохо» с первой минуты, теряет доверие к метрикам.

`MetricsService` использует константу `AVG_WINDOW_MONTHS=12` без guard'а на минимум данных.

## Планируемое
### Backend
- В `MetricsService.calculate_metrics_summary()` / `calculate_health_summary()` добавить:
  - Для `flow.lifestyle_indicator`, `capital.trend_*`, `dti.dti_percent`, `buffer.months` — если completed_months < MIN_MONTHS (3 для большинства, 1 для DTI и Buffer как точечных) → возвращать `null` + поле `insufficient_data: true`, `months_available: N`.
- Аналогично для FI-score: если хотя бы один компонент `insufficient_data` → весь FI-score возвращает `null` + breakdown с пометками.
- НЕ возвращать «0» — это даёт ложный сигнал «всё плохо».

### Frontend
- Компонент `<MetricCard insufficientData monthsAvailable={N} requiresMonths={3} />`:
  - Прогресс-бар «N из 3 месяцев данных»
  - Подсказка: «загрузите выписки за последние 3 месяца чтобы метрика стала показательной»
  - Серый цвет вместо зон зелёный/красный
- `<EmptyAccountState />` на dashboard при 0 транзакций — большой CTA «Загрузить первую выписку» / «Посмотреть на примере».

## Критичность
**Высокий приоритет** — критично для первого впечатления.

## Ссылки
- [[Подготовка к запуску MVP]] — Этап 4.2-4.4
- См. также: [[Фича — Демо-режим]]
