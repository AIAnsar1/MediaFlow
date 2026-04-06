from arq.connections import RedisSettings
from app.config import settings


def get_redis_settings() -> RedisSettings:
    """Настройки Redis для ARQ"""
    # Парсим URL
    url = str(settings.redis_url)

    # redis://localhost:6379/0
    if settings.use_fakeredis:
        # Для разработки на Windows
        return RedisSettings(
            host="localhost",
            port=6379,
            database=0,
        )

    # Парсим реальный URL
    from urllib.parse import urlparse
    parsed = urlparse(url)

    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
        password=parsed.password,
    )


# ARQ настройки
ARQ_SETTINGS = {
    "redis_settings": get_redis_settings(),
    "job_timeout": 3600,  # 1 час максимум на задачу
    "max_jobs": 100,
    "job_retry": 3,
    "health_check_interval": 30,
    "queue_name": "mediadownloader",
}
