import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.client_ip import get_client_ip


DOCS_PATH_PREFIXES = ("/docs", "/redoc", "/openapi.json")

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        path = request.url.path

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        # Для Swagger/ReDoc нельзя ставить слишком строгий CSP,
        # иначе интерфейс документации ломается.
        if path.startswith(DOCS_PATH_PREFIXES):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self' https: data: blob: 'unsafe-inline' 'unsafe-eval'; "
                "img-src 'self' https: data: blob:; "
                "style-src 'self' https: 'unsafe-inline'; "
                "script-src 'self' https: 'unsafe-inline' 'unsafe-eval'; "
                "font-src 'self' https: data:;"
            )
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "img-src 'self' data:; "
                "style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; "
                "font-src 'self' data:; "
                "object-src 'none'; "
                "base-uri 'self'; "
                "frame-ancestors 'none'; "
                "form-action 'self';"
            )

        return response


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """Defense-in-depth cap on request body size.

    Header-only check: if `Content-Length` is present and exceeds the cap,
    we reject with 413 BEFORE the multipart parser allocates anything. If
    the header is missing (chunked transfer encoding, HTTP/2) we fall through
    to the route — `app/services/upload_validator.py` enforces the per-type
    limit on the streaming read, so a hostile client lying about the size
    still gets caught on the second 64 KB chunk.

    Registered LAST in `main.py` so FastAPI's reverse-order middleware
    application runs it FIRST on every request (before CORS preflight, before
    SecurityHeadersMiddleware), making rejections cheap.
    """

    def __init__(self, app, *, max_size_mb: int):
        super().__init__(app)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.max_size_mb = max_size_mb

    async def dispatch(self, request: Request, call_next):
        raw = request.headers.get("content-length")
        if raw is not None:
            try:
                declared = int(raw)
            except ValueError:
                # Malformed header — let Starlette / the route handle it.
                # Either it'll be rejected at parse time, or treated as missing.
                declared = None
            # Negative Content-Length is nonsense; treat as missing rather than
            # signing off on it (Starlette/uvicorn usually rejects upstream, but
            # belt-and-braces).
            if declared is not None and declared >= 0 and declared > self.max_size_bytes:
                # `get_client_ip` honors `TRUSTED_PROXIES` so behind nginx/ALB
                # we log the real client, not the proxy. Same resolver is used
                # by the rate-limit key functions — keeps logs and rate-limit
                # buckets aligned on the same identity.
                client_ip = get_client_ip(request)
                logger.warning(
                    "MaxBodySizeMiddleware blocked request: "
                    "client_ip=%s path=%s content_length=%s cap=%s",
                    client_ip, request.url.path, declared, self.max_size_bytes,
                )
                payload = {
                    "detail": "Размер запроса превышает глобальный лимит.",
                    "code": "global_body_size_exceeded",
                    "max_size_mb": self.max_size_mb,
                    "actual_size_mb": round(declared / 1024 / 1024, 2),
                }
                return JSONResponse(status_code=413, content=payload)
        return await call_next(request)