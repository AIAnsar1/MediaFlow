import asyncio
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.logging import setup_logging, get_logger
from database.connection import db
from services import cache, bot_manager
from services.rate_limiter import rate_limiter
from workers.config import get_redis_settings
from workers.tasks import (
    broadcast_ad,
    delete_ad_messages,
    cleanup_temp_files,
    cleanup_old_downloads,
    update_bot_stats,
    aggregate_daily_stats,
    health_check,
)

log = get_logger("workers")


async def startup(ctx: dict) -> None:
    """Инициализация воркера"""
    setup_logging()
    log.info("Worker starting up...")

    await db.connect()
    await cache.connect()
    await bot_manager.setup()
    await rate_limiter.start()

    ctx["db"] = db
    ctx["cache"] = cache
    ctx["bot_manager"] = bot_manager

    log.info("Worker ready")


async def shutdown(ctx: dict) -> None:
    """Завершение воркера"""
    log.info("Worker shutting down...")

    await rate_limiter.stop()
    await bot_manager.shutdown()
    await cache.disconnect()
    await db.disconnect()

    log.info("Worker stopped")


class WorkerSettings:
    """ARQ Worker Settings"""

    redis_settings: RedisSettings = get_redis_settings()

    # Регистрация задач
    functions = [
        broadcast_ad,
        delete_ad_messages,
        cleanup_temp_files,
        cleanup_old_downloads,
        update_bot_stats,
        aggregate_daily_stats,
        health_check,
    ]

    # Cron задачи
    cron_jobs = [
        # Очистка temp файлов каждый час
        cron(cleanup_temp_files, hour={0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}, minute=0),

        # Обновление статистики каждые 15 минут
        cron(update_bot_stats, minute={0, 15, 30, 45}),

        # Агрегация ежедневной статистики в 00:05
        cron(aggregate_daily_stats, hour=0, minute=5),

        # Очистка старых загрузок раз в день в 03:00
        cron(cleanup_old_downloads, hour=3, minute=0),

        # Health check каждые 5 минут
        cron(health_check, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
    ]

    on_startup = startup
    on_shutdown = shutdown

    # Настройки
    max_jobs = 50
    job_timeout = 3600  # 1 час
    health_check_interval = 30
    queue_name = "mediadownloader"
