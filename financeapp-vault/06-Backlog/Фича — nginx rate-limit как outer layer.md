# Фича — nginx rate-limit как outer layer
#бэклог #пост-mvp #infra #security
> Outer-layer rate-limit на nginx/Cloudflare ПЕРЕД достижением FastAPI.
---
## Контекст (2026-05-04)
Этап 0.3 закрыл app-уровневый rate-limit через slowapi. Architecture trade-off (зафиксирован в `architecture_decisions.md` блок «Rate limits»):
- Атакующий с миллионом запросов в секунду на `/auth/login` доходит до FastAPI и тратит worker-cycles на JWT decode + slowapi storage check (Redis round-trip).
- Slowapi rate-limit отбрасывает 6-й запрос за 15 минут, но первые 5 проходят весь stack.
- Уровень нагрузки на 1k+ req/s — заметная нагрузка на uvicorn workers даже при 100% reject rate.

App-уровневый rate-limit оптимален для **бизнес-логики** (per-user квоты, per-endpoint лимиты), не для **DoS-защиты** на network-уровне.

## Проблема
- DoS-атака 10k+ req/s: app rejects 99.99%, но каждый rejected запрос всё ещё проходит:
  - TLS handshake,
  - HTTP parsing (uvicorn),
  - middleware chain (MaxBodySize → SlowAPI → CORS → SecurityHeaders),
  - Depends resolution,
  - decorator check,
  - ответ 429.
- На 10k req/s × 4 workers = ~2.5k req/s/worker — заметное CPU.
- При 100k req/s app просто ляжет до достижения rate-limit decorator.

## Планируемое
### nginx config (или Cloudflare equivalent)
```nginx
# /etc/nginx/conf.d/finance-api.conf

# Per-IP request rate, burst-tolerant.
limit_req_zone $binary_remote_addr zone=api_general:10m rate=20r/s;

# Stricter on auth endpoints.
limit_req_zone $binary_remote_addr zone=api_auth:10m rate=2r/s;

# Connection limit per IP.
limit_conn_zone $binary_remote_addr zone=api_conn:10m;

server {
    listen 443 ssl http2;
    server_name api.financeapp.example;

    # General request rate limit.
    location / {
        limit_req zone=api_general burst=50 nodelay;
        limit_conn api_conn 20;
        proxy_pass http://api:8000;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Stricter limit on auth (5 r/s burst, then app-level kicks in).
    location ~* /api/v1/auth/(login|register|refresh) {
        limit_req zone=api_auth burst=5 nodelay;
        proxy_pass http://api:8000;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Block known bot user-agents (опционально).
    if ($http_user_agent ~* (bot|crawler|spider|scraper)) {
        return 429;
    }
}
```

### Cloudflare alternative
- Cloudflare Rate Limiting Rules — UI-driven, без nginx config.
- WAF Custom Rules — block known attack patterns.
- DDoS Protection (Pro plan+) — auto-mitigation на L3/L4/L7.

### Sync с app-уровнем
- nginx — outer layer, режет на 20 r/s per IP (защита от DoS).
- App — inner layer, режет на 5/15min per IP (защита от brute-force).
- Если nginx пропускает — app поймает.
- Если nginx режет — app не получает запрос → CPU экономится.

### Конфигурация TRUSTED_PROXIES
- При деплое за nginx — `TRUSTED_PROXIES='["10.0.0.0/8"]'` (или конкретный nginx IP).
- Без этого app будет видеть все запросы как от nginx → per-IP лимиты бесполезны.
- Закрыто в Этапе 0.3 (helper `app/core/client_ip.py`), но env требует ручной настройки.

### Документация
- Обновить README раздел «Rate limits» — добавить блок «Production deployment behind nginx».
- Пример nginx config в `docs/nginx-example.conf` (опц., если решим версионировать).

## Оценка
~0.5-1 день setup'а nginx + тестирование. Не code-изменения в app, только infra.

## Критичность
**Средний приоритет** для production deployment, **низкий** для MVP с малым трафиком (<100 req/s). Когда:
- Появится реальный трафик (>100 юзеров) → nginx становится обязательным.
- Появятся атаки в логах → срочно.

Pre-deployment hardening: добавить в чек-лист «nginx rate-limit configured before public launch».

## Ссылки
- Этап 0.3 architecture_decisions: «Decorator-only mode + 401 побеждает 429» — компенсируется outer-layer.
- nginx limit_req docs: https://nginx.org/en/docs/http/ngx_http_limit_req_module.html
- Cloudflare Rate Limiting: https://developers.cloudflare.com/waf/rate-limiting-rules/
