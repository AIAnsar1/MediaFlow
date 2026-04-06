import time
from datetime import datetime, date, timedelta
from typing import Any
from dataclasses import dataclass
from enum import Enum

from services.cache import cache
from app.logging import get_logger

log = get_logger("service.metrics")


class MetricType(str, Enum):
    """Типы метрик"""
    COUNTER = "counter"      # Счётчик (только увеличивается)
    GAUGE = "gauge"          # Значение (может меняться)
    HISTOGRAM = "histogram"  # Распределение значений


@dataclass
class MetricPoint:
    """Точка метрики"""
    name: str
    value: float
    timestamp: datetime
    labels: dict[str, str] | None = None


class MetricsService:
    """
    Сервис сбора и хранения метрик

    Redis keys:
    - metrics:counter:{name}:{labels_hash} → value
    - metrics:gauge:{name}:{labels_hash} → value
    - metrics:timeseries:{name}:{hour} → list of values
    - metrics:daily:{name}:{date} → aggregated value
    """

    # Retention periods
    HOURLY_RETENTION = 24  # часов
    DAILY_RETENTION = 90   # дней

    def __init__(self):
        self._local_buffer: list[MetricPoint] = []

    # === Counters ===

    async def increment(
        self,
        name: str,
        value: int = 1,
        labels: dict[str, str] | None = None,
    ) -> int:
        """Увеличить счётчик"""
        key = self._build_key("counter", name, labels)
        new_value = await cache.incr(key, value)

        # Также записываем в timeseries для графиков
        await self._record_timeseries(name, value, labels)

        return new_value

    async def get_counter(
        self,
        name: str,
        labels: dict[str, str] | None = None,
    ) -> int:
        """Получить значение счётчика"""
        key = self._build_key("counter", name, labels)
        value = await cache.get(key)
        return int(value) if value else 0

    # === Gauges ===

    async def set_gauge(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Установить значение gauge"""
        key = self._build_key("gauge", name, labels)
        await cache.set(key, value, ttl=3600)

    async def get_gauge(
        self,
        name: str,
        labels: dict[str, str] | None = None,
    ) -> float:
        """Получить значение gauge"""
        key = self._build_key("gauge", name, labels)
        value = await cache.get(key)
        return float(value) if value else 0.0

    # === Timing ===

    async def record_timing(
        self,
        name: str,
        duration_ms: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Записать время выполнения"""
        # Записываем в timeseries
        await self._record_timeseries(f"{name}_duration", duration_ms, labels)

        # Обновляем среднее
        avg_key = self._build_key("gauge", f"{name}_avg", labels)
        count_key = self._build_key("counter", f"{name}_count", labels)

        count = await cache.incr(count_key)
        current_avg = await cache.get(avg_key) or 0

        # Скользящее среднее
        new_avg = ((float(current_avg) * (count - 1)) + duration_ms) / count
        await cache.set(avg_key, new_avg, ttl=3600)

    def timer(self, name: str, labels: dict[str, str] | None = None):
        """Context manager для измерения времени"""
        return MetricsTimer(self, name, labels)

    # === Timeseries ===

    async def _record_timeseries(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Записать значение в timeseries"""
        now = datetime.now()
        hour_key = now.strftime("%Y%m%d%H")

        key = f"metrics:ts:{name}:{hour_key}"

        # Добавляем в список
        data = {
            "value": value,
            "timestamp": now.isoformat(),
            "labels": labels,
        }
        await cache.redis.rpush(key, str(data))
        await cache.redis.expire(key, self.HOURLY_RETENTION * 3600)

    async def get_timeseries(
        self,
        name: str,
        hours: int = 24,
    ) -> list[dict]:
        """Получить timeseries данные"""
        now = datetime.now()
        result = []

        for i in range(hours):
            hour = now - timedelta(hours=i)
            hour_key = hour.strftime("%Y%m%d%H")
            key = f"metrics:ts:{name}:{hour_key}"

            values = await cache.redis.lrange(key, 0, -1)

            # Агрегируем по часу
            if values:
                total = sum(float(eval(v).get("value", 0)) for v in values)
                result.append({
                    "hour": hour.strftime("%Y-%m-%d %H:00"),
                    "value": total,
                    "count": len(values),
                })

        return list(reversed(result))

    # === High-level metrics ===

    async def record_download(
        self,
        platform: str,
        bot_id: int,
        duration_ms: float,
        success: bool,
        from_cache: bool = False,
    ) -> None:
        """Записать метрики загрузки"""
        labels = {"platform": platform, "bot_id": str(bot_id)}

        # Счётчики
        await self.increment("downloads_total", labels=labels)

        if success:
            await self.increment("downloads_success", labels=labels)
        else:
            await self.increment("downloads_failed", labels=labels)

        if from_cache:
            await self.increment("downloads_cached", labels=labels)

        # Время
        await self.record_timing("download", duration_ms, labels={"platform": platform})

        # По платформе (для графика)
        await self.increment(f"downloads_{platform}")

    async def record_user_activity(self, bot_id: int) -> None:
        """Записать активность пользователя"""
        await self.increment("active_users", labels={"bot_id": str(bot_id)})

        # Уникальные за день
        today = date.today().isoformat()
        await cache.redis.pfadd(f"metrics:unique_users:{today}", str(bot_id))

    async def record_error(
        self,
        error_type: str,
        bot_id: int | None = None,
    ) -> None:
        """Записать ошибку"""
        labels = {"type": error_type}
        if bot_id:
            labels["bot_id"] = str(bot_id)

        await self.increment("errors_total", labels=labels)

    async def record_broadcast_progress(
        self,
        ad_id: int,
        sent: int,
        failed: int,
        total: int,
    ) -> None:
        """Записать прогресс рассылки"""
        key = f"broadcast:progress:{ad_id}"
        await cache.set(key, {
            "sent": sent,
            "failed": failed,
            "total": total,
            "progress": round(sent / total * 100, 1) if total > 0 else 0,
            "updated_at": datetime.now().isoformat(),
        }, ttl=3600)

    async def get_broadcast_progress(self, ad_id: int) -> dict | None:
        """Получить прогресс рассылки"""
        return await cache.get(f"broadcast:progress:{ad_id}")

    # === Stats aggregation ===

    async def get_dashboard_stats(self) -> dict:
        """Получить статистику для dashboard"""
        today = date.today().isoformat()

        # Downloads today
        downloads_today = 0
        for platform in ["youtube", "instagram", "tiktok", "pinterest", "vk"]:
            count = await self.get_counter(f"downloads_{platform}")
            downloads_today += count

        # Errors today
        errors_today = await self.get_counter("errors_total")

        # Unique users today
        unique_users = await cache.redis.pfcount(f"metrics:unique_users:{today}")

        # Average download time
        avg_time = await self.get_gauge("download_avg")

        # Downloads by platform
        by_platform = {}
        for platform in ["youtube", "instagram", "tiktok", "pinterest", "vk"]:
            by_platform[platform] = await self.get_counter(f"downloads_{platform}")

        # Success rate
        total = await self.get_counter("downloads_total")
        success = await self.get_counter("downloads_success")
        success_rate = round(success / total * 100, 2) if total > 0 else 100

        return {
            "downloads_today": downloads_today,
            "errors_today": errors_today,
            "unique_users_today": unique_users,
            "avg_download_time_ms": round(avg_time, 2),
            "by_platform": by_platform,
            "success_rate": success_rate,
            "cache_hit_rate": await self._get_cache_hit_rate(),
        }

    async def get_hourly_stats(self, hours: int = 24) -> list[dict]:
        """Получить почасовую статистику"""
        downloads = await self.get_timeseries("downloads_total", hours)
        errors = await self.get_timeseries("errors_total", hours)

        # Объединяем
        result = []
        for i, dl in enumerate(downloads):
            err = errors[i] if i < len(errors) else {"value": 0}
            result.append({
                "hour": dl["hour"],
                "downloads": dl["value"],
                "errors": err.get("value", 0),
            })

        return result

    async def _get_cache_hit_rate(self) -> float:
        """Получить процент попаданий в кеш"""
        total = await self.get_counter("downloads_total")
        cached = await self.get_counter("downloads_cached")

        if total == 0:
            return 0.0

        return round(cached / total * 100, 2)

    # === Helpers ===

    def _build_key(
        self,
        metric_type: str,
        name: str,
        labels: dict[str, str] | None = None,
    ) -> str:
        """Построить ключ метрики"""
        key = f"metrics:{metric_type}:{name}"

        if labels:
            # Сортируем для консистентности
            labels_str = ":".join(f"{k}={v}" for k, v in sorted(labels.items()))
            key = f"{key}:{labels_str}"

        return key


class MetricsTimer:
    """Context manager для измерения времени"""

    def __init__(
        self,
        metrics: MetricsService,
        name: str,
        labels: dict[str, str] | None = None,
    ):
        self.metrics = metrics
        self.name = name
        self.labels = labels
        self.start_time: float = 0

    async def __aenter__(self):
        self.start_time = time.time()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.time() - self.start_time) * 1000
        await self.metrics.record_timing(self.name, duration_ms, self.labels)


# === Singleton ===
metrics = MetricsService()
