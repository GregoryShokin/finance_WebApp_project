from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.models.budget import Budget  # noqa: F401 — registers mapper
from app.models.budget_alert import BudgetAlert  # noqa: F401 — registers mapper
from app.models.goal import Goal  # noqa: F401 — registers mapper
from app.models.real_asset import RealAsset  # noqa: F401 — registers mapper

from app.api.v1.accounts import router as accounts_router
from app.api.v1.auth import router as auth_router
from app.api.v1.categories import router as categories_router
from app.api.v1.budget import router as budget_router
from app.api.v1.category_rules import router as category_rules_router
from app.api.v1.financial_health import router as financial_health_router
from app.api.v1.goals import router as goals_router
from app.api.v1.metrics import router as metrics_router
from app.api.v1.counterparties import router as counterparties_router
from app.api.v1.health import router as health_router
from app.api.v1.imports import router as imports_router
from app.api.v1.telegram import router as telegram_router
from app.api.v1.transactions import router as transactions_router
from app.core.config import settings
from app.core.middleware import SecurityHeadersMiddleware

app = FastAPI(title=settings.APP_NAME, version="0.3.0", debug=settings.DEBUG)

if settings.ENABLE_HTTPS_REDIRECT:
    app.add_middleware(HTTPSRedirectMiddleware)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.TRUSTED_HOSTS or ["localhost", "127.0.0.1"],
)

app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin"],
)

app.include_router(health_router, prefix=settings.API_V1_PREFIX)
app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
app.include_router(accounts_router, prefix=settings.API_V1_PREFIX)
app.include_router(categories_router, prefix=settings.API_V1_PREFIX)
app.include_router(counterparties_router, prefix=settings.API_V1_PREFIX)
app.include_router(transactions_router, prefix=settings.API_V1_PREFIX)
app.include_router(imports_router, prefix=settings.API_V1_PREFIX)
app.include_router(telegram_router, prefix=settings.API_V1_PREFIX)
app.include_router(budget_router, prefix=settings.API_V1_PREFIX)
app.include_router(financial_health_router, prefix=settings.API_V1_PREFIX)
app.include_router(goals_router, prefix=settings.API_V1_PREFIX)
app.include_router(metrics_router, prefix=settings.API_V1_PREFIX)
app.include_router(category_rules_router, prefix=settings.API_V1_PREFIX)


@app.get("/")
def root():
    return {
        "service": settings.APP_NAME,
        "docs": "/docs",
        "api_prefix": settings.API_V1_PREFIX,
        "environment": settings.APP_ENV,
    }
