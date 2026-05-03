# Фича — Обучаемый operation_type
#бэклог #высокий-приоритет #импорт
> `transaction_category_rules` учат категорию, но не учат `operation_type`. Юзер каждый раз вручную ставит «debt» / «transfer» / «refund» для одних и тех же контрагентов.
---
## Проблема (2026-05-03)
Архитектурный пробел в спеке пайплайна импорта (см. memory/project_operation_type_learning_gap.md):
- `transaction_category_rules` хранит маппинг `(user, normalized_description) → category_id` с confirms/rejections.
- `operation_type` определяется только из keyword-нормализатора (`is_transfer_like`, `is_refund_like`) и истории через `account_context` / `bank_mechanics` / orphan-transfer hint.
- Если описание не содержит keyword'ов («Перевод от Иван И.»), система каждый раз ставит дефолт `regular` и заставляет юзера переключать на `debt`.

## Планируемое
### Backend
- Добавить колонку `operation_type` (nullable string) в `transaction_category_rules`.
- Расширить `bulk_upsert` / `upsert` / `get_best_rule`: при подтверждении строки с не-default operation_type писать его в правило вместе с категорией.
- В `import_normalizer_v2` / `enrichment`: если правило найдено и `operation_type IS NOT NULL` и `confirms >= RULE_ACTIVATE_CONFIRMS` → применить.
- Учёт в `bulk_apply_cluster`: массовое подтверждение учит operation_type аналогично категории.
- Миграция 0059.

### Тесты
- Сценарий «Иван получает зарплату → переключаю на debt → следующий импорт классифицирован как debt без вмешательства»
- Сценарий «правило отвергнуто — confirms убывают, при достижении порога правило деактивируется»

### Документация
- Запись в `14-Specifications/Спецификация — Пайплайн импорта.md` §7.x как закрытие known risk.

## Критичность
**Высокий приоритет** — без этого ощущение «система тупит» убивает retention модератора.

## Ссылки
- [[Подготовка к запуску MVP]] — Этап 2.1-2.5
- Memory: `project_operation_type_learning_gap.md`
