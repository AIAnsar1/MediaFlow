import json
from datetime import datetime
from typing import Any
from dataclasses import dataclass
from enum import Enum

from arq.jobs import Job, JobStatus
from arq.connections import ArqRedis

from services.cache import cache
from app.logging import get_logger
from workers.config import get_redis_settings

log = get_logger("service.queue_monitor")


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    DEFERRED = "deferred"
    NOT_FOUND = "not_found"


@dataclass
class JobInfo:
    """Информация о задаче"""
    job_id: str
    function: str
    args: tuple
    kwargs: dict
    status: JobState
    enqueue_time: datetime | None
    start_time: datetime | None
    finish_time: datetime | None
    result: Any | None
    error: str | None
    retry_count: int


@dataclass
class QueueStats:
    """Статистика очереди"""
    pending: int
    running: int
    complete: int
    failed: int
    total_processed: int
    success_rate: float


class QueueMonitorService:
    """
    Сервис мониторинга очередей ARQ

    Функции:
    - Статистика очередей
    - Список jobs
    - Retry failed jobs
    - Delete jobs
    - Worker status
    """

    def __init__(self):
        self._pool: ArqRedis | None = None
        self._loop: Any | None = None

    async def get_pool(self) -> ArqRedis:
        """Получить ARQ pool"""
        import asyncio
        from app.config import settings
        
        current_loop = asyncio.get_running_loop()
        
        if self._pool is None or self._loop != current_loop:
            if self._pool:
                await self.close()
            
            self._loop = current_loop
            
            if settings.use_fakeredis:
                # В режиме тестов используем уже подключенный cache.redis
                await cache.connect()
                # cache.redis в тестах это FakeRedis, нам нужно привести его к ArqRedis
                # для совместимости типов в Job(job_id, pool)
                self._pool = cache.redis
            else:
                from arq import create_pool
                from workers.config import get_redis_settings
                self._pool = await create_pool(get_redis_settings())
                
        return self._pool

    async def close(self) -> None:
        """Закрыть pool"""
        if self._pool:
            await self._pool.close()
            self._pool = None

    # === Queue Stats ===

    async def get_queue_stats(self) -> QueueStats:
        """Получить статистику очереди"""
        pool = await self.get_pool()

        # Pending jobs
        pending = await cache.redis.zcard("arq:queue:mediadownloader")

        # Running jobs (in progress)
        running = await cache.redis.scard("arq:in-progress:mediadownloader")

        # Results (completed + failed)
        result_keys = await cache.redis.keys("arq:result:*")
        complete = 0
        failed = 0

        for key in result_keys[:1000]:  # Limit
            result = await cache.redis.get(key)
            if result:
                try:
                    data = json.loads(result)
                    if data.get("success"):
                        complete += 1
                    else:
                        failed += 1
                except:
                    pass

        total = complete + failed
        success_rate = round(complete / total * 100, 2) if total > 0 else 100.0

        return QueueStats(
            pending=pending,
            running=running,
            complete=complete,
            failed=failed,
            total_processed=total,
            success_rate=success_rate,
        )

    async def get_pending_jobs(self, limit: int = 50) -> list[JobInfo]:
        """Получить pending jobs"""
        jobs = []

        # Получаем из sorted set
        pending_data = await cache.redis.zrange(
            "arq:queue:mediadownloader",
            0,
            limit - 1,
            withscores=True,
        )

        for job_data, score in pending_data:
            try:
                data = json.loads(job_data)
                jobs.append(JobInfo(
                    job_id=data.get("job_id", ""),
                    function=data.get("function", "unknown"),
                    args=tuple(data.get("args", [])),
                    kwargs=data.get("kwargs", {}),
                    status=JobState.PENDING,
                    enqueue_time=datetime.fromtimestamp(score / 1000) if score else None,
                    start_time=None,
                    finish_time=None,
                    result=None,
                    error=None,
                    retry_count=data.get("retry", 0),
                ))
            except Exception as e:
                log.warning("Failed to parse job", error=str(e))

        return jobs

    async def get_running_jobs(self) -> list[JobInfo]:
        """Получить running jobs"""
        jobs = []

        running_ids = await cache.redis.smembers("arq:in-progress:mediadownloader")

        for job_id in running_ids:
            job_info = await self.get_job_info(job_id.decode() if isinstance(job_id, bytes) else job_id)
            if job_info:
                job_info.status = JobState.RUNNING
                jobs.append(job_info)

        return jobs

    async def get_failed_jobs(self, limit: int = 50) -> list[JobInfo]:
        """Получить failed jobs"""
        jobs = []

        # Сканируем results
        cursor = 0
        count = 0

        while count < limit:
            cursor, keys = await cache.redis.scan(
                cursor=cursor,
                match="arq:result:*",
                count=100,
            )

            for key in keys:
                if count >= limit:
                    break

                result = await cache.redis.get(key)
                if result:
                    try:
                        data = json.loads(result)
                        if not data.get("success"):
                            job_id = key.decode().split(":")[-1] if isinstance(key, bytes) else key.split(":")[-1]
                            jobs.append(JobInfo(
                                job_id=job_id,
                                function=data.get("function", "unknown"),
                                args=tuple(data.get("args", [])),
                                kwargs=data.get("kwargs", {}),
                                status=JobState.FAILED,
                                enqueue_time=None,
                                start_time=datetime.fromisoformat(data["start_time"]) if data.get("start_time") else None,
                                finish_time=datetime.fromisoformat(data["finish_time"]) if data.get("finish_time") else None,
                                result=None,
                                error=data.get("error"),
                                retry_count=data.get("retry", 0),
                            ))
                            count += 1
                    except Exception as e:
                        log.warning("Failed to parse result", error=str(e))

            if cursor == 0:
                break

        return jobs

    async def get_recent_jobs(self, limit: int = 50) -> list[JobInfo]:
        """Получить последние jobs (все статусы)"""
        pending = await self.get_pending_jobs(limit // 3)
        running = await self.get_running_jobs()
        failed = await self.get_failed_jobs(limit // 3)

        # Объединяем и сортируем
        all_jobs = pending + running + failed
        all_jobs.sort(key=lambda x: x.enqueue_time or datetime.min, reverse=True)

        return all_jobs[:limit]

    async def get_job_info(self, job_id: str) -> JobInfo | None:
        """Получить информацию о job"""
        pool = await self.get_pool()

        try:
            job = Job(job_id, pool)
            status = await job.status()
            info = await job.info()

            if not info:
                return None

            # Маппинг статуса
            status_map = {
                JobStatus.deferred: JobState.DEFERRED,
                JobStatus.queued: JobState.PENDING,
                JobStatus.in_progress: JobState.RUNNING,
                JobStatus.complete: JobState.COMPLETE,
                JobStatus.not_found: JobState.NOT_FOUND,
            }

            return JobInfo(
                job_id=job_id,
                function=info.function,
                args=info.args,
                kwargs=info.kwargs,
                status=status_map.get(status, JobState.NOT_FOUND),
                enqueue_time=info.enqueue_time,
                start_time=info.start_time,
                finish_time=info.finish_time,
                result=info.result if status == JobStatus.complete else None,
                error=str(info.result) if status == JobStatus.complete and not info.success else None,
                retry_count=0,
            )
        except Exception as e:
            log.error("Failed to get job info", job_id=job_id, error=str(e))
            return None

    # === Job Actions ===

    async def retry_job(self, job_id: str) -> bool:
        """Retry failed job"""
        pool = await self.get_pool()

        try:
            job = Job(job_id, pool)
            info = await job.info()

            if not info:
                return False

            # Удаляем старый результат
            await cache.redis.delete(f"arq:result:{job_id}")

            # Создаём новую задачу
            await pool.enqueue_job(
                info.function,
                *info.args,
                **info.kwargs,
            )

            log.info("Job retried", job_id=job_id, function=info.function)
            return True

        except Exception as e:
            log.error("Failed to retry job", job_id=job_id, error=str(e))
            return False

    async def delete_job(self, job_id: str) -> bool:
        """Удалить job"""
        try:
            # Удаляем результат
            await cache.redis.delete(f"arq:result:{job_id}")

            # Удаляем из очереди (если pending)
            await cache.redis.zrem("arq:queue:mediadownloader", job_id)

            log.info("Job deleted", job_id=job_id)
            return True

        except Exception as e:
            log.error("Failed to delete job", job_id=job_id, error=str(e))
            return False

    async def retry_all_failed(self) -> int:
        """Retry all failed jobs"""
        failed = await self.get_failed_jobs(limit=100)
        retried = 0

        for job in failed:
            if await self.retry_job(job.job_id):
                retried += 1

        log.info("Retried failed jobs", count=retried)
        return retried

    async def clear_failed(self) -> int:
        """Очистить все failed jobs"""
        failed = await self.get_failed_jobs(limit=1000)
        deleted = 0

        for job in failed:
            if await self.delete_job(job.job_id):
                deleted += 1

        log.info("Cleared failed jobs", count=deleted)
        return deleted

    # === Workers Status ===

    async def get_workers_status(self) -> list[dict]:
        """Получить статус воркеров"""
        workers = []

        # Ищем heartbeat ключи
        cursor = 0
        while True:
            cursor, keys = await cache.redis.scan(
                cursor=cursor,
                match="arq:health:*",
                count=100,
            )

            for key in keys:
                data = await cache.redis.get(key)
                if data:
                    try:
                        worker_info = json.loads(data)
                        worker_id = key.decode().split(":")[-1] if isinstance(key, bytes) else key.split(":")[-1]

                        # Проверяем свежесть
                        last_seen = datetime.fromisoformat(worker_info.get("time", ""))
                        is_active = (datetime.now() - last_seen).seconds < 60

                        workers.append({
                            "id": worker_id,
                            "status": "active" if is_active else "idle",
                            "jobs_processed": worker_info.get("jobs", 0),
                            "last_seen": last_seen.isoformat(),
                            "current_job": worker_info.get("current_job"),
                        })
                    except:
                        pass

            if cursor == 0:
                break

        return workers

    # === Broadcasts ===

    async def get_active_broadcasts(self) -> list[dict]:
        """Получить активные рассылки"""
        from services.metrics import metrics

        broadcasts = []

        # Сканируем broadcast progress keys
        cursor = 0
        while True:
            cursor, keys = await cache.redis.scan(
                cursor=cursor,
                match="broadcast:progress:*",
                count=100,
            )

            for key in keys:
                data = await cache.get(key.decode() if isinstance(key, bytes) else key)
                if data:
                    ad_id = key.decode().split(":")[-1] if isinstance(key, bytes) else key.split(":")[-1]
                    broadcasts.append({
                        "ad_id": int(ad_id),
                        **data,
                    })

            if cursor == 0:
                break

        return broadcasts


# === Singleton ===
queue_monitor = QueueMonitorService()
