from __future__ import annotations

import json
from functools import cached_property
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "finance-backend"
    APP_ENV: str = "dev"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    POSTGRES_DB: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str

    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_URL: str = "redis://redis:6379/0"

    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    ALGORITHM: str = "HS256"
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_BOT_NAME: str = "financeapp_import_bot"

    BACKEND_CORS_ORIGINS: list[str] | str = ["http://localhost:3000"]
    TRUSTED_HOSTS: list[str] | str = ["localhost", "127.0.0.1"]
    ENABLE_HTTPS_REDIRECT: bool = False
    # Reverse proxies whose `X-Forwarded-For` we trust for client-IP resolution.
    # Empty list → never trust XFF (use direct peer address). Entries are IPs
    # or CIDR ranges (e.g. "10.0.0.0/8") parsed by `app/core/client_ip.py`.
    TRUSTED_PROXIES: list[str] | str = []

    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-haiku-4-5"
    LLM_CLASSIFICATION_ENABLED: bool = False
    LLM_MIN_CONFIDENCE: float = 0.6

    # Rule-strength thresholds (И-08 Phase 2.3).
    RULE_ACTIVATE_CONFIRMS: int = 2
    RULE_GENERALIZE_CONFIRMS: int = 3
    RULE_DEACTIVATE_REJECTIONS: int = 3
    RULE_ERROR_RATIO_CAP: float = 0.3

    # Upload limits (Этап 0.2). Per-type caps applied in /imports/upload and
    # /telegram/bot/upload after magic-byte detection. GLOBAL_BODY_SIZE_CAP_MB
    # is enforced by middleware as a defense-in-depth header check before the
    # multipart parser runs. MAX_XLSX_DECOMPRESSED_MB protects against zip-bomb
    # XLSX uploads (validated in app/services/upload_validator.py).
    MAX_UPLOAD_SIZE_CSV_MB: int = 10
    MAX_UPLOAD_SIZE_XLSX_MB: int = 10
    MAX_UPLOAD_SIZE_PDF_MB: int = 25
    MAX_XLSX_DECOMPRESSED_MB: int = 100
    GLOBAL_BODY_SIZE_CAP_MB: int = 30

    # Rate limits (Этап 0.3). Strings are slowapi/limits format ("N/period").
    # /auth/* are per-IP (no user yet); /imports/upload is per-user (CGNAT
    # collapses millions of mobile users behind one IP); /telegram/bot/upload
    # is per-IP because extracting telegram_id would require parsing the
    # multipart body twice — see backlog "Bot rate-limit per-telegram_id".
    # Generous defaults — these are abuse caps, not throttling.
    RATE_LIMIT_LOGIN: str = "5/15 minutes"
    RATE_LIMIT_REGISTER: str = "3/hour"
    RATE_LIMIT_REFRESH: str = "30/5 minutes"
    RATE_LIMIT_UPLOAD: str = "30/hour"
    RATE_LIMIT_BOT_UPLOAD: str = "30/hour"
    # Toggle for tests — set RATE_LIMIT_ENABLED=false in pytest env to silence
    # the limiter without ripping decorators off routes.
    RATE_LIMIT_ENABLED: bool = True

    @field_validator("BACKEND_CORS_ORIGINS", "TRUSTED_HOSTS", "TRUSTED_PROXIES", mode="before")
    @classmethod
    def _parse_str_list(cls, value: Any) -> list[str] | Any:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            if raw.startswith("["):
                parsed = json.loads(raw)
                if not isinstance(parsed, list):
                    raise ValueError("Expected JSON array")
                return [str(item).strip() for item in parsed if str(item).strip()]
            return [item.strip() for item in raw.split(",") if item.strip()]
        return value

    @field_validator("SECRET_KEY")
    @classmethod
    def _validate_secret_key(cls, value: str) -> str:
        if len(value.strip()) < 32:
            raise ValueError("SECRET_KEY must contain at least 32 characters")
        forbidden = {
            "super-secret-key-change-me",
            "change-me",
            "secret",
            "dev-secret",
            "test-secret",
        }
        if value.strip().lower() in forbidden:
            raise ValueError("SECRET_KEY is insecure and must be replaced")
        return value

    @cached_property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() in {"prod", "production"}


settings = Settings()
