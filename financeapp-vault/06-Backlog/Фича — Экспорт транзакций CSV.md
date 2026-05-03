# Фича — Экспорт транзакций CSV
#бэклог #высокий-приоритет
> Эндпоинт + кнопка экспорта всех транзакций в CSV. GDPR-минимум + страховка пользователя от vendor lock-in.
---
## Проблема (2026-05-03)
Нет способа выгрузить свои данные. Это:
- Юридически: GDPR/152-ФЗ требуют права на портативность данных.
- Психологически: юзер боится вкладывать месяцы работы в систему, из которой нельзя «забрать» данные.
- Практически: для бухучёта/налогов/анализа в Excel.

В Voice Inbox упомянуто как «next release feature», но в Backlog не было.

## Планируемое
### Backend
- `GET /transactions/export.csv?date_from=&date_to=&account_id=` — streaming response.
- Поля: `date, account, type, operation_type, category, counterparty, debt_partner, amount, currency, description, transfer_pair_id, is_regular, needs_review`.
- Локаль RU: разделитель `;`, decimal `,`, BOM в начале файла (для Excel).
- Имя файла: `transactions_YYYY-MM-DD_to_YYYY-MM-DD.csv`.

### Frontend
- Кнопка «Экспортировать» в шапке `/transactions`.
- Модалка с выбором периода (по умолчанию: текущий + 11 предыдущих месяцев) и опциональным фильтром по счёту.
- Скачивание через `<a download>` или fetch + blob.

### Опционально (v2)
- Экспорт XLSX с форматированием
- Экспорт счетов / категорий / правил отдельно
- Полный backup-export в JSON

## Критичность
**Высокий приоритет** — обязательно до публичного запуска.

## Ссылки
- [[Подготовка к запуску MVP]] — Этап 3.1-3.2
- Voice Inbox.md (note 2026-05-01)
