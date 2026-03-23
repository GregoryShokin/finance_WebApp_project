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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ALGORITHM: str = "HS256"

    BACKEND_CORS_ORIGINS: list[str] | str = ["http://localhost:3000"]
    TRUSTED_HOSTS: list[str] | str = ["localhost", "127.0.0.1"]
    ENABLE_HTTPS_REDIRECT: bool = False

    @field_validator("BACKEND_CORS_ORIGINS", "TRUSTED_HOSTS", mode="before")
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
