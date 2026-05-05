# Фича — Memory-efficient upload pipeline
#бэклог #пост-mvp #импорт #infra
> Перевод upload-пайплайна с BytesIO в RAM на tempfile-streaming для снижения пикового использования памяти при concurrent uploads.
---
## Контекст (2026-05-03)
Этап 0.2 закрыл security и size-каpы (10/10/25 MB на CSV/XLSX/PDF), но сохранил RAM-based аккумуляцию: `read_upload_with_limits` накапливает чанки в `BytesIO()` и передаёт `bytes` в extractor. Зафиксировано как осознанный trade-off:

> NOTE: Files are accumulated in BytesIO (RAM). For 100 concurrent uploads of 25 MB PDFs that's ~2.5 GB peak — acceptable for the current single-box deployment.

## Проблема
Worst-case память на 100 одновременных загрузок 25 MB PDF = ~2.5 GB. На текущем dev/MVP deployment с 4+ GB RAM терпимо, но:
- При росте concurrent uploads (например, маркетинговая рассылка → пик утренних загрузок) лимит легко пробивается.
- Каждый upload удваивает память во время `service.upload_source` (extractor парсит → ImportRow в RAM → JSON в БД).

## Планируемое
### Backend
- `read_upload_with_limits` пишет чанки в `tempfile.SpooledTemporaryFile(max_size=2*1024*1024)`:
  - До 2 MB — в RAM,
  - выше — на диск (Linux: `/tmp`, Docker: tmpfs если доступен).
- API helper возвращает `(file_path, kind)` или объект-обёртку со streaming-доступом, не `bytes`.
- **Рефакторинг `ImportExtractorRegistry`**: extractor'ы (`csv_extractor`, `xlsx_extractor`, `pdf_extractor`) сейчас принимают `raw_bytes: bytes`. Перевести на `path: Path` или `BinaryIO`. openpyxl/pypdf оба поддерживают file-like input.
- В service `import_service.upload_source` — заменить `raw_bytes` на streaming-handle.
- `file_content` колонка `import_sessions` — сейчас хранит base64 контент для re-парсинга при изменении mapping. Решить: либо хранить путь (с cleanup'ом по cron), либо продолжать читать в base64 на этапе persist.

### Cleanup
- Tempfile удаляется после успешного `service.upload_source` (или через `try/finally`).
- Beat-task раз в сутки чистит зависшие temp-файлы старше 24h.

## Оценка
~2-3 дня. Рефакторинг extractor'ов — самая трудная часть, требует обновления golden-тестов в `tests/`.

## Критичность
**Низкий-средний приоритет** — не блокер MVP. Откладывается до момента, когда мониторинг покажет реальный peak RAM > 60% от worker capacity.

## Ссылки
- Этап 0.2: `app/services/upload_validator.py:read_upload_with_limits` (NOTE-комментарий про RAM-инвариант).
- Архитектурное решение: `architecture_decisions.md` блок «Upload validation».
