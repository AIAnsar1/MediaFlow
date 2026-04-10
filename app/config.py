from functools import lru_cache
from typing import Literal
from pydantic import Field, PostgresDsn, RedisDsn, AnyUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "MediaFlow"
    debug: bool = False
    secret_key: str = Field(..., min_length=32)

    # Database
    database_url: AnyUrl = Field(...)
    database_echo: bool = False
    database_pool_size: int = 10

    # Redis
    redis_url: RedisDsn = Field(default="redis://localhost:6379/0")  # ty:ignore[invalid-assignment]
    use_fakeredis: bool = False  # True for Windows dev

    # Telegram
    telegram_api_server: str | None = None  # Custom Bot API Server
    storage_channel_id: int | None = Field(default=None)  # Fallback for caching media (deprecated: use CacheChannel CRUD)

    # Admin
    admin_username: str = "admin"
    admin_password: str = Field(..., min_length=8)

    # Rate Limits
    rate_limit_global_requests: int = 1000
    rate_limit_global_window: int = 60
    rate_limit_user_requests: int = 30
    rate_limit_user_window: int = 60
    rate_limit_download_requests: int = 10
    rate_limit_download_window: int = 60
    downloads_per_user_hour: int = 50
    downloads_per_minute: int = 100

    # Paths
    temp_download_path: str = "../storage/temp/"

    # Webhook
    webhook_base_url: str | None = None  # https://yourdomain.com

    # Queue
    queue_workers: int = 10
    queue_max_per_user: int = 2
    queue_max_global: int = 50

    # Worker
    worker_broadcast_batch_size: int = 25
    worker_broadcast_delay_ms: int = 50


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
