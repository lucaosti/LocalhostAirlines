"""Application configuration, read once from the environment.

Every value here corresponds to a variable in .env.example. Nothing here has a
production-usable default for a secret — SECRET_KEY and POSTGRES_PASSWORD must be
supplied, and the application refuses to start without them (see validators below).
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")
    secret_key: str = Field(alias="SECRET_KEY")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    base_currency: str = Field(default="EUR", alias="BASE_CURRENCY")

    travelpayouts_token: str | None = Field(default=None, alias="TRAVELPAYOUTS_TOKEN")
    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")

    # The session cookie's Secure attribute defaults False to match the
    # documented deployment: plain HTTP on a trusted LAN (spec §8, §157). A
    # browser never sends a Secure cookie back over plain HTTP, so setting
    # this unconditionally would break login on the default deployment.
    # Flip it on for anyone terminating TLS in front of Caddy.
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")

    session_ttl_hours: int = Field(default=24 * 14, alias="SESSION_TTL_HOURS")

    # Login rate limiting lives in Redis (spec §82: cache-shaped, not a
    # source of truth) and fails open if Redis is unreachable — losing
    # brute-force protection briefly is preferable to locking every user
    # out of an otherwise-working login because a cache is down.
    login_rate_limit_per_account: int = Field(default=5, alias="LOGIN_RATE_LIMIT_PER_ACCOUNT")
    login_rate_limit_per_ip: int = Field(default=20, alias="LOGIN_RATE_LIMIT_PER_IP")
    login_rate_limit_window_seconds: int = Field(
        default=300, alias="LOGIN_RATE_LIMIT_WINDOW_SECONDS"
    )

    @field_validator("secret_key")
    @classmethod
    def secret_key_must_be_set(cls, v: str) -> str:
        # A blank secret key would silently make sessions forgeable. Fail loudly at
        # startup instead of failing quietly at the first login (spec §78).
        if not v or len(v) < 32:
            raise ValueError("SECRET_KEY must be set and at least 32 characters")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
