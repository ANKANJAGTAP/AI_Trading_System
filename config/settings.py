"""Environment / secret configuration (the `.env` half of the config layer).

Secrets and deployment-specific values live here (DB creds, Redis, Kite API
keys, SMTP, LLM key). Tunable trading parameters live in `config/*.yaml` and are
loaded by `config.loader`. Never hardcode secrets — everything is read from the
environment / `.env`.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- runtime ---
    env: str = "dev"                      # dev | prod
    log_level: str = "INFO"
    log_json: bool = False                # JSON logs in prod, console in dev
    config_dir: str = "config"            # where the *.yaml tunables live

    # --- PostgreSQL / TimescaleDB ---
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "ats"
    postgres_user: str = "ats"
    postgres_password: str = "ats"

    # --- Redis ---
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # --- Zerodha Kite Connect ---
    kite_api_key: str = ""
    kite_api_secret: str = ""
    kite_user_id: str = ""
    kite_password: str = ""
    kite_totp_secret: str = ""            # base32 TOTP seed for automated 2FA
    kite_redirect_url: str = ""           # optional; only used to parse request_token

    # --- secure token storage ---
    token_store_path: str = ".secrets/kite_token.json"
    token_encryption_key: str = ""        # Fernet key (base64). Empty => plaintext (DEV ONLY)

    # --- SMTP alerts ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_from_name: str = ""               # display name in the From header (e.g. "OutFyld")
    smtp_use_tls: bool = True
    alert_email_to: str = ""

    # --- LLM (used from Phase 5) ---
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    # --- API control-plane auth (opt-in; empty => OPEN, dev only) ---
    # When set, every /api/* route and the /ws stream require Authorization:
    # "Bearer <token>". Leave empty ONLY for a trusted, localhost-bound dev box.
    api_auth_token: str = ""
    # Comma-separated allowed CORS origins. "*" = any (dev). In prod set to the
    # dashboard origin(s), e.g. "https://aegis.example.com".
    cors_allow_origins: str = "*"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
