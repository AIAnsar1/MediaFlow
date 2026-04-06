import asyncio
import json
import hashlib
from typing import Any
from datetime import timedelta

from app.config import settings
from app.logging import get_logger

log = get_logger("service.cache")

# Shared FakeServer for persistence across reconnections in tests
_fake_server = None


class CacheService:
    """

    Использование:
        cache = CacheService()
        await cache.connect()

        await cache.set("key", {"data": 123}, ttl=3600)
        data = await cache.get("key")
    """

    def __init__(self):
        self._redis = None
        self._loop = None

    async def connect(self) -> None:
        """Подключение к Redis"""
        current_loop = asyncio.get_running_loop()
        if self._redis is not None:
            if self._loop == current_loop:
                return
            log.warning("Loop changed, reconnecting cache")
            await self.disconnect()

        self._loop = current_loop
        if settings.use_fakeredis:
            import fakeredis
            import fakeredis.aioredis
            global _fake_server
            if _fake_server is None:
                _fake_server = fakeredis.FakeServer()
            self._redis = fakeredis.aioredis.FakeRedis(server=_fake_server, decode_responses=True)
            log.info("Connected to FakeRedis (dev mode)")
        else:
            import redis.asyncio as redis
            self._redis = redis.from_url(
                str(settings.redis_url),
                encoding="utf-8",
                decode_responses=True,
            )
            # Проверка подключения
            await self._redis.ping()
            log.info("Connected to Redis", url=str(settings.redis_url).split("@")[-1])

    async def disconnect(self) -> None:
        """Отключение"""
        if self._redis:
            try:
                await self._redis.close()
            except Exception:
                pass
            self._redis = None
            self._loop = None
            log.info("Disconnected from Redis")

    @property
    def redis(self):
        """Getter for internal redis client"""
        if self._redis is None:
            raise RuntimeError("Cache not connected. Call connect() first.")
        return self._redis

    # === Basic Operations ===

    async def get(self, key: str) -> Any | None:
        """Получить значение"""
        await self.connect()
        data = await self.redis.get(key)
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return data
        return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        """Установить значение"""
        await self.connect()
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        await self.redis.set(key, value, ex=ttl)

    async def delete(self, key: str) -> bool:
        """Удалить ключ"""
        await self.connect()
        return await self.redis.delete(key) > 0

    async def exists(self, key: str) -> bool:
        """Проверить существование"""
        await self.connect()
        return await self.redis.exists(key) > 0

    async def incr(self, key: str, amount: int = 1) -> int:
        """Инкремент"""
        await self.connect()
        return await self.redis.incrby(key, amount)

    async def expire(self, key: str, ttl: int) -> None:
        """Установить TTL"""
        await self.connect()
        await self.redis.expire(key, ttl)

    # === Media Cache ===

    def _media_key(self, url: str, quality: str | None = None) -> str:
        """Генерация ключа для медиа"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        if quality:
            return f"media:{url_hash}:{quality}"
        return f"media:{url_hash}"

    async def get_cached_media(
        self,
        url: str,
        quality: str | None = None,
    ) -> dict | None:
        """Получить закешированное медиа"""
        key = self._media_key(url, quality)
        data = await self.get(key)
        if data:
            log.debug("Cache HIT", url=url[:50], quality=quality)
        return data

    async def cache_media(
        self,
        url: str,
        file_id: str,
        message_id: int,
        chat_id: int,
        quality: str | None = None,
        ttl: int = 86400 * 30,  # 30 days
        **extra,
    ) -> None:
        """Закешировать медиа"""
        key = self._media_key(url, quality)
        data = {
            "file_id": file_id,
            "message_id": message_id,
            "chat_id": chat_id,
            "quality": quality,
            **extra,
        }
        await self.set(key, data, ttl=ttl)
        log.debug("Cached media", url=url[:50], quality=quality)

    # === Rate Limiting ===

    async def check_rate_limit(
        self,
        key: str,
        limit: int,
        window: int = 60,
    ) -> tuple[bool, int]:
        """
        Проверить rate limit

        Returns:
            (allowed: bool, remaining: int)
        """
        await self.connect()
        current = await self.redis.get(key)

        if current is None:
            await self.redis.setex(key, window, 1)
            return True, limit - 1

        current = int(current)
        if current >= limit:
            ttl = await self.redis.ttl(key)
            return False, ttl  # False + seconds until reset

        await self.redis.incr(key)
        return True, limit - current - 1

    async def get_user_rate_limit(
        self,
        user_id: int,
        action: str = "download",
    ) -> tuple[bool, int]:
        """Rate limit для пользователя"""
        key = f"simple_ratelimit:{action}:{user_id}"

        if action == "download":
            return await self.check_rate_limit(
                key,
                limit=settings.downloads_per_user_hour,
                window=3600,
            )

        return True, 999

    async def get_global_rate_limit(self) -> tuple[bool, int]:
        """Глобальный rate limit"""
        return await self.check_rate_limit(
            "simple_ratelimit:global",
            limit=settings.downloads_per_minute,
            window=60,
        )

    # === User State (для FSM без aiogram) ===

    async def get_user_state(self, user_id: int, bot_id: int) -> dict | None:
        """Получить состояние пользователя"""
        key = f"state:{bot_id}:{user_id}"
        return await self.get(key)

    async def set_user_state(
        self,
        user_id: int,
        bot_id: int,
        state: str,
        data: dict | None = None,
        ttl: int = 3600,
    ) -> None:
        """Установить состояние пользователя"""
        key = f"state:{bot_id}:{user_id}"
        await self.set(key, {"state": state, "data": data or {}}, ttl=ttl)

    async def clear_user_state(self, user_id: int, bot_id: int) -> None:
        """Очистить состояние"""
        key = f"state:{bot_id}:{user_id}"
        await self.delete(key)

    async def update_state_data(
        self,
        user_id: int,
        bot_id: int,
        **data,
    ) -> None:
        """Обновить данные состояния"""
        current = await self.get_user_state(user_id, bot_id) or {"state": None, "data": {}}
        current["data"].update(data)
        await self.set_user_state(
            user_id, bot_id,
            current["state"],
            current["data"],
        )

    # === Queue ===

    async def add_to_queue(
        self,
        queue_name: str,
        item: dict,
    ) -> int:
        """Добавить в очередь"""
        await self.connect()
        return await self.redis.rpush(
            f"queue:{queue_name}",
            json.dumps(item, default=str),
        )

    async def pop_from_queue(self, queue_name: str) -> dict | None:
        """Забрать из очереди"""
        await self.connect()
        data = await self.redis.lpop(f"queue:{queue_name}")
        if data:
            return json.loads(data)
        return None

    async def queue_length(self, queue_name: str) -> int:
        """Длина очереди"""
        await self.connect()
        return await self.redis.llen(f"queue:{queue_name}")


# === Singleton ===
cache = CacheService()
