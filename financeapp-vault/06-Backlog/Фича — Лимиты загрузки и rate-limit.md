# Фича — Лимиты загрузки и rate-limit
#бэклог #критический-приоритет #безопасность
> Защита публичных эндпоинтов от перегрузки и атак: лимит размера файла, content-type whitelist, rate-limit на upload и auth.
---
## Проблема (2026-05-03)
Перед публичным запуском в коде нет:
- Лимита размера загружаемого файла на `/imports/upload` и `/telegram/bot/upload` — атакующий может положить `pdf_extractor` 500 MB PDF.
- Жёсткого content-type whitelist — экстракторы пытаются парсить любой загруженный мусор.
- Rate-limit на `/auth/login`, `/auth/register`, `/imports/upload`, `/telegram/bot/upload` — возможен brute-force паролей и DDoS экстракторов.

В продакшене это блокер по безопасности и стабильности.

## Планируемое
### Лимиты файлов
- CSV/XLSX: 10 MB
- PDF: 25 MB
- Ранний reject в API-роуте до передачи экстракторам
- Content-type whitelist: `text/csv`, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, `application/vnd.ms-excel`, `application/pdf` (магические байты, не trust headers)

### Rate-limit
- `slowapi` или Redis-based лимитер
- `/auth/login`: 5 попыток / 15 мин на IP
- `/auth/register`: 3 регистрации / час на IP
- `/imports/upload`: 30 загрузок / час на user
- `/telegram/bot/upload`: 30 загрузок / час на telegram_id
- 429 ответ с `Retry-After` заголовком

### Frontend
- Валидация размера на клиенте (мгновенный фидбек до отправки)
- Понятная ошибка при 429 («слишком много попыток, повторите через X минут»)

## Критичность
**Критический приоритет** — обязательно до публичного домена. Без этого первый bot-сканер положит сервис.

## Ссылки
- [[Подготовка к запуску MVP]] — Этап 0.2, 0.3
