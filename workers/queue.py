import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Any
from collections import defaultdict

from arq import create_pool
from arq.connections import ArqRedis

from app.logging import get_logger
from workers.config import get_redis_settings
from services.rate_limiter import rate_limiter, RateLimitType

log = get_logger("service.queue")


@dataclass
class QueueItem:
    """Элемент очереди"""
    id: str
    user_id: int
    bot_id: int
    url: str
    created_at: datetime = field(default_factory=datetime.now)
    priority: int = 0


class QueueService:
    """
    Сервис очереди загрузок

    - In-memory очередь для быстрых операций
    - ARQ для тяжёлых фоновых задач
    - Rate limiting интеграция
    """

    def __init__(
        self,
        max_per_user: int = 2,
        max_global: int = 50,
        worker_count: int = 10,
    ):
        self.max_per_user = max_per_user
        self.max_global = max_global
        self.worker_count = worker_count

        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._active: dict[int, int] = defaultdict(int)  # user_id -> count
        self._total_active: int = 0
        self._workers: list[asyncio.Task] = []
        self._lock = asyncio.Lock()
        self._running = False

        # ARQ pool
        self._arq_pool: ArqRedis | None = None

    async def start(self) -> None:
        """Запуск сервиса"""
        if self._running:
            return

        self._running = True

        # Создаём ARQ pool
        try:
            self._arq_pool = await create_pool(get_redis_settings())
            log.info("ARQ pool created")
        except Exception as e:
            log.warning("ARQ pool failed, using local queue only", error=str(e))

        # Запускаем воркеры
        for i in range(self.worker_count):
            worker = asyncio.create_task(self._worker(i))
            self._workers.append(worker)

        log.info("Queue service started", workers=self.worker_count)

    async def stop(self) -> None:
        """Остановка"""
        self._running = False

        for worker in self._workers:
            worker.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

        if self._arq_pool:
            await self._arq_pool.close()

        log.info("Queue service stopped")

    async def add(
        self,
        user_id: int,
        bot_id: int,
        url: str,
        handler: Callable,
        priority: int = 0,
        **kwargs,
    ) -> tuple[bool, int | str]:
        """
        Добавить в очередь

        Returns:
            (success, position_or_error)
        """
        # Проверяем rate limit
        rate_result = await rate_limiter.check_download(user_id)
        if not rate_result.allowed:
            return False, f"Rate limit: retry in {rate_result.retry_after}s"

        async with self._lock:
            # Проверяем лимит пользователя
            if self._active[user_id] >= self.max_per_user:
                return False, "Too many active downloads"

            # Проверяем глобальный лимит
            if self._total_active >= self.max_global:
                return False, "Server is busy"

            # Создаём задачу
            item = QueueItem(
                id=f"{user_id}:{bot_id}:{datetime.now().timestamp()}",
                user_id=user_id,
                bot_id=bot_id,
                url=url,
                priority=priority,
            )

            # Сохраняем handler и kwargs
            item_data = {
                "item": item,
                "handler": handler,
                "kwargs": kwargs,
            }

            await self._queue.put((-priority, item.created_at.timestamp(), item_data))

            position = self._queue.qsize()
            log.debug("Added to queue", user_id=user_id, position=position)

            return True, position

    async def get_position(self, user_id: int) -> int:
        """Позиция в очереди"""
        return self._queue.qsize()

    async def get_active_count(self, user_id: int) -> int:
        """Количество активных загрузок"""
        return self._active[user_id]

    async def _worker(self, worker_id: int) -> None:
        """Воркер обработки очереди"""
        log.debug("Worker started", worker_id=worker_id)

        while self._running:
            try:
                try:
                    _, _, item_data = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue

                item = item_data["item"]
                handler = item_data["handler"]
                kwargs = item_data["kwargs"]

                # Увеличиваем счётчики
                async with self._lock:
                    self._active[item.user_id] += 1
                    self._total_active += 1

                try:
                    log.debug(
                        "Processing",
                        worker_id=worker_id,
                        user_id=item.user_id,
                        url=item.url[:50],
                    )

                    await handler(**kwargs)

                except Exception as e:
                    log.exception("Task failed", error=str(e))

                finally:
                    async with self._lock:
                        self._active[item.user_id] = max(0, self._active[item.user_id] - 1)
                        self._total_active = max(0, self._total_active - 1)

                    self._queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.exception("Worker error", error=str(e))
                await asyncio.sleep(1)

        log.debug("Worker stopped", worker_id=worker_id)

    # === ARQ Integration ===

    async def enqueue_broadcast(self, ad_id: int, **kwargs) -> str | None:
        """Добавить задачу рассылки в ARQ"""
        if not self._arq_pool:
            log.error("ARQ pool not available")
            return None

        try:
            job = await self._arq_pool.enqueue_job(
                "broadcast_ad",
                ad_id,
                **kwargs,
            )
            log.info("Broadcast job enqueued", job_id=job.job_id, ad_id=ad_id)
            return job.job_id
        except Exception as e:
            log.error("Failed to enqueue broadcast", error=str(e))
            return None

    async def enqueue_delete_ad(self, ad_id: int) -> str | None:
        """Добавить задачу удаления рекламы"""
        if not self._arq_pool:
            return None

        try:
            job = await self._arq_pool.enqueue_job("delete_ad_messages", ad_id)
            return job.job_id
        except Exception as e:
            log.error("Failed to enqueue delete", error=str(e))
            return None

    async def get_job_status(self, job_id: str) -> dict | None:
        """Получить статус задачи"""
        if not self._arq_pool:
            return None

        try:
            job = await self._arq_pool.job(job_id)
            if job:
                status = await job.status()
                return {
                    "id": job_id,
                    "status": status.value,
                    "result": await job.result() if status.value == "complete" else None,
                }
        except:
            pass
        return None


# === Singleton ===
queue_service = QueueService()
