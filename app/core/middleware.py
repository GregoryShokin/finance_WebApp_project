from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


DOCS_PATH_PREFIXES = ("/docs", "/redoc", "/openapi.json")


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