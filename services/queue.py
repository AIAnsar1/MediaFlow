import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Any
from collections import defaultdict

from app.logging import get_logger
from services.cache import cache

log = get_logger("service.queue")


@dataclass
class QueueItem:
    """Элемент очереди"""
    id: str
    user_id: int
    bot_id: int
    url: str
    handler: Callable
    kwargs: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    priority: int = 0  # Higher = more priority


class QueueService:
    """
    Сервис очереди загрузок

    - Ограничение параллельных загрузок на пользователя
    - FIFO очередь с приоритетами
    - Интеграция с Redis для персистентности
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

        self._queue: asyncio.PriorityQueue | None = None
        self._active: dict[int, int] = defaultdict(int)  # user_id -> active count
        self._total_active: int = 0
        self._workers: list[asyncio.Task] = []
        self._lock: asyncio.Lock | None = None
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        """Запустить обработку очереди"""
        current_loop = asyncio.get_running_loop()
        if self._running:
            if self._loop == current_loop:
                return
            log.warning("Loop changed, restarting queue service")
            await self.stop()

        self._loop = current_loop

        self._queue = asyncio.PriorityQueue()
        self._active.clear()
        self._total_active = 0
        self._lock = asyncio.Lock()
        self._running = True

        for i in range(self.worker_count):
            worker = asyncio.create_task(self._worker(i))
            self._workers.append(worker)

        log.info("Queue started", workers=self.worker_count)

    async def stop(self) -> None:
        """Остановить обработку"""
        self._running = False

        if self._workers:
            for worker in self._workers:
                worker.cancel()

            await asyncio.gather(*self._workers, return_exceptions=True)
            self._workers.clear()

        self._loop = None
        log.info("Queue stopped")

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
        Добавить задачу в очередь

        Returns:
            (success: bool, position_or_error: int | str)
        """
        await self.start()
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
                handler=handler,
                kwargs=kwargs,
                priority=priority,
            )

            # Добавляем в очередь (приоритет инвертирован для PriorityQueue)
            await self._queue.put((-priority, item.created_at.timestamp(), item))

            position = self._queue.qsize()
            log.debug("Added to queue", user_id=user_id, position=position)

            return True, position

    async def get_position(self, user_id: int) -> int:
        """Получить позицию в очереди"""
        await self.start()
        # Примерная позиция
        return self._queue.qsize()

    async def get_active_count(self, user_id: int) -> int:
        """Количество активных загрузок пользователя"""
        await self.start()
        return self._active[user_id]

    async def _worker(self, worker_id: int) -> None:
        """Воркер обработки очереди"""
        log.debug("Worker started", worker_id=worker_id)

        while self._running:
            try:
                # Ждём задачу с таймаутом
                try:
                    _, _, item = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue

                # Увеличиваем счётчики
                async with self._lock:
                    self._active[item.user_id] += 1
                    self._total_active += 1

                try:
                    log.debug(
                        "Processing task",
                        worker_id=worker_id,
                        user_id=item.user_id,
                        url=item.url[:50],
                    )

                    # Выполняем handler
                    await item.handler(**item.kwargs)

                except Exception as e:
                    log.exception(
                        "Task failed",
                        worker_id=worker_id,
                        error=str(e),
                    )

                finally:
                    # Уменьшаем счётчики
                    async with self._lock:
                        self._active[item.user_id] = max(0, self._active[item.user_id] - 1)
                        self._total_active = max(0, self._total_active - 1)

                    self._queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                log.exception("Worker error", worker_id=worker_id, error=str(e))
                await asyncio.sleep(1)

        log.debug("Worker stopped", worker_id=worker_id)


# === Singleton ===
queue_service = QueueService()
