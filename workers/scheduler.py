import asyncio
from datetime import datetime, timedelta
from typing import Callable, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.memory import MemoryJobStore

from app.logging import get_logger
from database.connection import db
from repositories.uow import UnitOfWork
from services import cache

log = get_logger("scheduler")


class SchedulerService:
    """
    Сервис планировщика задач

    Использует APScheduler для периодических задач внутри процесса
    (дополнение к ARQ для задач, не требующих отдельного воркера)
    """

    def __init__(self):
        self.scheduler = AsyncIOScheduler(
            jobstores={
                "default": MemoryJobStore(),
            },
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 60,
            },
        )
        self._running = False

    async def start(self) -> None:
        """Запуск планировщика"""
        if self._running:
            return

        self._register_jobs()
        self.scheduler.start()
        self._running = True
        log.info("Scheduler started")

    async def stop(self) -> None:
        """Остановка планировщика"""
        if not self._running:
            return

        self.scheduler.shutdown(wait=True)
        self._running = False
        log.info("Scheduler stopped")

    def _register_jobs(self) -> None:
        """Регистрация периодических задач"""

        # Обновление статистики кеша каждые 5 минут
        self.scheduler.add_job(
            self._update_cache_stats,
            trigger=IntervalTrigger(minutes=5),
            id="update_cache_stats",
            name="Update Cache Stats",
        )

        # Очистка истекших rate limits каждые 10 минут
        self.scheduler.add_job(
            self._cleanup_rate_limits,
            trigger=IntervalTrigger(minutes=10),
            id="cleanup_rate_limits",
            name="Cleanup Rate Limits",
        )

        # Проверка здоровья ботов каждые 5 минут
        self.scheduler.add_job(
            self._check_bots_health,
            trigger=IntervalTrigger(minutes=5),
            id="check_bots_health",
            name="Check Bots Health",
        )

        # Очистка старых state данных каждый час
        self.scheduler.add_job(
            self._cleanup_old_states,
            trigger=IntervalTrigger(hours=1),
            id="cleanup_old_states",
            name="Cleanup Old States",
        )

        # Обновление webhook'ов при необходимости (каждые 6 часов)
        self.scheduler.add_job(
            self._refresh_webhooks,
            trigger=IntervalTrigger(hours=6),
            id="refresh_webhooks",
            name="Refresh Webhooks",
        )

    async def _update_cache_stats(self) -> None:
        """Обновить статистику кеша"""
        try:
            info = await cache.redis.info("stats")
            log.debug(
                "Cache stats",
                hits=info.get("keyspace_hits", 0),
                misses=info.get("keyspace_misses", 0),
            )
        except Exception as e:
            log.warning("Failed to get cache stats", error=str(e))

    async def _cleanup_rate_limits(self) -> None:
        """Очистка истекших rate limit ключей"""
        try:
            # Redis автоматически удаляет по TTL,
            # но можно дополнительно почистить
            pattern = "ratelimit:*"
            cursor = 0
            cleaned = 0

            while True:
                cursor, keys = await cache.redis.scan(
                    cursor=cursor,
                    match=pattern,
                    count=100,
                )

                for key in keys:
                    ttl = await cache.redis.ttl(key)
                    if ttl == -1:  # Нет TTL
                        await cache.redis.expire(key, 3600)
                        cleaned += 1

                if cursor == 0:
                    break

            if cleaned:
                log.debug("Rate limit keys cleaned", count=cleaned)

        except Exception as e:
            log.warning("Rate limit cleanup failed", error=str(e))

    async def _check_bots_health(self) -> None:
        """Проверить здоровье ботов"""
        from services import bot_manager
        from models import BotStatus

        try:
            async with UnitOfWork() as uow:
                bots = await uow.bots.get_all()

                for bot_model in bots:
                    if bot_model.status != BotStatus.ACTIVE:
                        continue

                    try:
                        bot = await bot_manager.get_bot(bot_model.token)
                        if bot:
                            me = await bot.get_me()
                            # Бот работает
                    except Exception as e:
                        log.warning(
                            "Bot health check failed",
                            username=bot_model.username,
                            error=str(e),
                        )
                        # Можно обновить статус или отправить алерт

        except Exception as e:
            log.error("Bots health check failed", error=str(e))

    async def _cleanup_old_states(self) -> None:
        """Очистка старых FSM состояний"""
        try:
            # Состояния старше 24 часов
            pattern = "state:*"
            cursor = 0
            cleaned = 0

            while True:
                cursor, keys = await cache.redis.scan(
                    cursor=cursor,
                    match=pattern,
                    count=100,
                )

                for key in keys:
                    ttl = await cache.redis.ttl(key)
                    # Если TTL не установлен или очень большой
                    if ttl == -1 or ttl > 86400:
                        await cache.redis.expire(key, 3600)  # 1 час
                        cleaned += 1

                if cursor == 0:
                    break

            if cleaned:
                log.debug("Old states cleaned", count=cleaned)

        except Exception as e:
            log.warning("State cleanup failed", error=str(e))

    async def _refresh_webhooks(self) -> None:
        """Обновить webhook'и"""
        from services import bot_manager
        from config import settings

        if not settings.webhook_base_url:
            return

        try:
            results = await bot_manager.setup_all_webhooks(settings.webhook_base_url)
            log.info("Webhooks refreshed", results=results)
        except Exception as e:
            log.error("Webhook refresh failed", error=str(e))

    # === Public API ===

    def add_job(
        self,
        func: Callable,
        trigger: str = "interval",
        **trigger_args,
    ) -> str:
        """Добавить задачу"""
        if trigger == "interval":
            trigger_obj = IntervalTrigger(**trigger_args)
        elif trigger == "cron":
            trigger_obj = CronTrigger(**trigger_args)
        else:
            raise ValueError(f"Unknown trigger: {trigger}")

        job = self.scheduler.add_job(func, trigger=trigger_obj)
        return job.id

    def remove_job(self, job_id: str) -> None:
        """Удалить задачу"""
        self.scheduler.remove_job(job_id)

    def get_jobs(self) -> list[dict]:
        """Получить список задач"""
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in self.scheduler.get_jobs()
        ]


# === Singleton ===
scheduler = SchedulerService()
