# Фича — Pre-auth IP rate-limit на upload
#бэклог #пост-mvp #security #rate-limit
> Дополнительный per-IP лимит на `/imports/upload` ДО проверки токена, чтобы атакующий с garbage Bearer не тратил ресурсы на JWT decode + DB lookup.
---
## Контекст (2026-05-04)
В Этапе 0.3 принято и зафиксировано в `architecture_decisions.md` поведение «**401 побеждает 429**»:

> Невалидный токен → `Depends(get_current_user)` бросает 401 ДО декоратора rate-limit. Counter не инкрементится. Pre-auth IP-rate-limit на upload не реализован — защита через `/auth/login` лимит.

Pinned тестом `tests/test_rate_limit_uploads.py:test_invalid_token_returns_401_not_429` — 35 запросов с garbage Bearer все возвращают 401, ни одного 429.

## Проблема
Атакующий с миллионом garbage-токенов (например, leaked JWT secrets из других проектов) может бомбить `/imports/upload` без срабатывания rate-limit. Каждый запрос:
- Парсится middleware chain (5 layers).
- Резолвит `Depends(get_db)` — connection из pool (~0.1ms).
- Резолвит `Depends(get_current_user)` — JWT decode (~10-50μs) + `UserRepository.get_by_id` (1 round-trip в БД ~0.5ms).
- Возвращает 401.

При 1k req/s: ~500ms/sec on DB, рост connection pool churn, latency для легитимных юзеров.

**Косвенная защита есть:** `/auth/login` лимит 5/15min. Атакующий с украденным `secrets/jwks` не нуждается в login (он сам подписывает токены), но если у него **нет** правильного `SECRET_KEY` — токен failed JWT signature → 401 в JWT decode (5μs), не доходит до DB lookup. То есть DB-impact = 0 для большинства атак.

**Реальный сценарий, где это важно:** утечка `SECRET_KEY` (catastrophic event). Атакующий генерит валидные токены для несуществующих user_id. JWT decode проходит, `UserRepository.get_by_id` возвращает None, 401. В этом сценарии каждый запрос = 1 DB query — атакующий может насыщать DB.

## Планируемое
### Вариант A: pre-auth декоратор отдельным lim
```python
# Сначала per-IP лимит (300/hour, щедрый), потом per-user (30/hour)
@router.post("/imports/upload", ...)
@limiter.limit("300/hour", key_func=ip_key)  # outer guard
@limiter.limit(settings.RATE_LIMIT_UPLOAD, key_func=user_or_ip_key)  # inner per-user
async def upload_file(request: Request, ...):
    ...
```
Slowapi поддерживает множественные декораторы — оба check'а должны пройти. Pre-auth лимит ловит атаки до достижения `Depends(get_current_user)` (если slowapi enforcement happens before Depends — что **не так** в текущей версии, см. mini-step 1.5).

### Вариант B: middleware-уровень per-IP cap
- `IpThrottleMiddleware` после `MaxBodySize`, считает запросы per-IP в Redis.
- Глобальный cap (например, 1000 запросов/минуту/IP) для ВСЕХ роутов, не только upload.
- Срабатывает раньше FastAPI dependency cycle — закрывает «401 побеждает 429».

### Вариант C: nginx rate-limit
- Внешний layer ловит DoS-уровень атаки до достижения uvicorn.
- Описан в [[Фича — nginx rate-limit как outer layer]] — этой карточки достаточно для большинства сценариев.

**Рекомендация:** **Вариант C** для MVP+1, **Вариант B** для эскалации, **Вариант A** только если slowapi эволюционирует middleware-mode (текущая архитектура декоратор-after-Depends делает A бесполезным для pre-auth защиты).

## Оценка
- Вариант C — см. отдельную карточку.
- Вариант B — ~1 день (middleware + Redis counter + тесты).
- Вариант A — нет смысла без middleware-mode upgrade slowapi.

## Критичность
**Низкий приоритет** — реальная угроза только при утечке `SECRET_KEY`. В этом сценарии rotation секрета (revoke all tokens) — primary mitigation, не rate-limit.

## Ссылки
- Этап 0.3 architecture_decisions: «401 побеждает 429».
- Test pinning current behavior: `tests/test_rate_limit_uploads.py:test_invalid_token_returns_401_not_429`.
- Связано: [[Фича — nginx rate-limit как outer layer]] (предпочтительная mitigation).
