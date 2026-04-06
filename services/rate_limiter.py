import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Any
from functools import wraps

from services.cache import cache
from app.logging import get_logger
from app.config import settings

log = get_logger("service.rate_limiter")


class RateLimitType(str, Enum):
    """Типы rate limit"""
    GLOBAL = "global"           # Общий лимит сервера
    USER = "user"               # Лимит на пользователя
    BOT = "bot"                 # Лимит на бота
    ENDPOINT = "endpoint"       # Лимит на endpoint
    DOWNLOAD = "download"       # Лимит на загрузки
    BROADCAST = "broadcast"     # Лимит на рассылку


@dataclass
class RateLimitResult:
    """Результат проверки rate limit"""
    allowed: bool
    remaining: int          # Оставшиеся запросы
    reset_after: int        # Секунд до сброса
    limit: int              # Максимум запросов
    retry_after: int | None = None  # Секунд до повторной попытки


@dataclass
class RateLimitConfig:
    """Конфигурация rate limit"""
    requests: int           # Количество запросов
    window: int             # Временное окно (секунды)
    burst: int | None = None  # Burst limit (пиковая нагрузка)


class RateLimiter:
    """
    Сервис Rate Limiting

    Алгоритм: Sliding Window + Token Bucket

    Уровни защиты:
    1. Global - общий лимит сервера
    2. Per-User - лимит на пользователя
    3. Per-Bot - лимит на бота
    4. Per-Action - лимит на действие (download, broadcast)
    """

    # Конфигурации по умолчанию
    DEFAULT_LIMITS: dict[RateLimitType, RateLimitConfig] = {
        RateLimitType.GLOBAL: RateLimitConfig(
            requests=1000,      # 1000 запросов
            window=60,          # в минуту
            burst=100,          # burst до 100
        ),
        RateLimitType.USER: RateLimitConfig(
            requests=30,        # 30 запросов
            window=60,          # в минуту
            burst=10,
        ),
        RateLimitType.BOT: RateLimitConfig(
            requests=500,       # 500 запросов на бота
            window=60,
            burst=50,
        ),
        RateLimitType.DOWNLOAD: RateLimitConfig(
            requests=10,        # 10 загрузок
            window=60,          # в минуту
            burst=3,
        ),
        RateLimitType.BROADCAST: RateLimitConfig(
            requests=30,        # 30 сообщений
            window=1,           # в секунду (Telegram limit)
            burst=30,
        ),
        RateLimitType.ENDPOINT: RateLimitConfig(
            requests=100,
            window=60,
            burst=20,
        ),
    }

    def __init__(self):
        self._local_cache: dict[str, tuple[int, float]] = {}  # Fallback без Redis
        self._cleanup_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Запуск cleanup task"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        log.info("Rate limiter started")

    async def stop(self) -> None:
        """Остановка"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        log.info("Rate limiter stopped")

    async def _cleanup_loop(self) -> None:
        """Периодическая очистка локального кеша"""
        while True:
            try:
                await asyncio.sleep(60)
                now = time.time()
                expired = [
                    key for key, (_, expires) in self._local_cache.items()
                    if expires < now
                ]
                for key in expired:
                    del self._local_cache[key]
                if expired:
                    log.debug("Cleaned up rate limit keys", count=len(expired))
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Cleanup error", error=str(e))

    def _get_key(
        self,
        limit_type: RateLimitType,
        identifier: str | int | None = None,
    ) -> str:
        """Генерация ключа для rate limit"""
        if identifier:
            return f"ratelimit:{limit_type.value}:{identifier}"
        return f"ratelimit:{limit_type.value}"

    async def check(
        self,
        limit_type: RateLimitType,
        identifier: str | int | None = None,
        config: RateLimitConfig | None = None,
    ) -> RateLimitResult:
        """
        Проверить rate limit

        Args:
            limit_type: Тип лимита
            identifier: ID (user_id, bot_id, etc.)
            config: Кастомная конфигурация

        Returns:
            RateLimitResult
        """
        config = config or self.DEFAULT_LIMITS.get(limit_type)
        if not config:
            return RateLimitResult(allowed=True, remaining=999, reset_after=0, limit=999)

        key = self._get_key(limit_type, identifier)

        try:
            return await self._check_redis(key, config)
        except Exception as e:
            log.warning("Redis rate limit failed, using local", error=str(e))
            return self._check_local(key, config)

    async def _check_redis(self, key: str, config: RateLimitConfig) -> RateLimitResult:
        """Проверка через Redis (Sliding Window)"""
        await cache.connect()
        now = time.time()
        window_start = now - config.window

        # Lua script для атомарной операции
        # Используем sorted set: score = timestamp, member = unique id
        pipe = cache.redis.pipeline()

        # Удаляем старые записи
        pipe.zremrangebyscore(key, 0, window_start)
        # Считаем текущие
        pipe.zcard(key)
        # Добавляем новый запрос
        pipe.zadd(key, {f"{now}:{id(now)}": now})
        # Устанавливаем TTL
        pipe.expire(key, config.window + 1)

        results = await pipe.execute()
        current_count = results[1]

        # Проверяем лимит
        if current_count >= config.requests:
            # Получаем время самого старого запроса в окне
            oldest = await cache.redis.zrange(key, 0, 0, withscores=True)
            if oldest:
                reset_after = int(oldest[0][1] + config.window - now)
            else:
                reset_after = config.window

            # Удаляем только что добавленный запрос
            await cache.redis.zremrangebyscore(key, now, now + 1)

            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_after=reset_after,
                limit=config.requests,
                retry_after=reset_after,
            )

        remaining = config.requests - current_count - 1

        return RateLimitResult(
            allowed=True,
            remaining=max(0, remaining),
            reset_after=config.window,
            limit=config.requests,
        )

    def _check_local(self, key: str, config: RateLimitConfig) -> RateLimitResult:
        """Fallback: локальная проверка (Token Bucket)"""
        now = time.time()

        if key in self._local_cache:
            count, window_start = self._local_cache[key]

            # Проверяем, не истекло ли окно
            if now - window_start >= config.window:
                # Новое окно
                self._local_cache[key] = (1, now)
                return RateLimitResult(
                    allowed=True,
                    remaining=config.requests - 1,
                    reset_after=config.window,
                    limit=config.requests,
                )

            if count >= config.requests:
                reset_after = int(window_start + config.window - now)
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    reset_after=reset_after,
                    limit=config.requests,
                    retry_after=reset_after,
                )

            self._local_cache[key] = (count + 1, window_start)
            return RateLimitResult(
                allowed=True,
                remaining=config.requests - count - 1,
                reset_after=int(window_start + config.window - now),
                limit=config.requests,
            )

        # Первый запрос
        self._local_cache[key] = (1, now)
        return RateLimitResult(
            allowed=True,
            remaining=config.requests - 1,
            reset_after=config.window,
            limit=config.requests,
        )

    async def check_user(self, user_id: int) -> RateLimitResult:
        """Проверить лимит пользователя"""
        return await self.check(RateLimitType.USER, user_id)

    async def check_download(self, user_id: int) -> RateLimitResult:
        """Проверить лимит загрузок пользователя"""
        return await self.check(RateLimitType.DOWNLOAD, user_id)

    async def check_global(self) -> RateLimitResult:
        """Проверить глобальный лимит"""
        return await self.check(RateLimitType.GLOBAL)

    async def check_bot(self, bot_id: int) -> RateLimitResult:
        """Проверить лимит бота"""
        return await self.check(RateLimitType.BOT, bot_id)

    async def check_broadcast(self, bot_id: int) -> RateLimitResult:
        """Проверить лимит рассылки (30 msg/sec для Telegram)"""
        return await self.check(RateLimitType.BROADCAST, bot_id)

    async def check_all(
        self,
        user_id: int | None = None,
        bot_id: int | None = None,
        action: RateLimitType | None = None,
    ) -> RateLimitResult:
        """
        Проверить все применимые лимиты

        Возвращает первый неуспешный или общий результат
        """
        checks = [
            (RateLimitType.GLOBAL, None),
        ]

        if bot_id:
            checks.append((RateLimitType.BOT, bot_id))
        if user_id:
            checks.append((RateLimitType.USER, user_id))
        if action and user_id:
            checks.append((action, user_id))

        for limit_type, identifier in checks:
            result = await self.check(limit_type, identifier)
            if not result.allowed:
                log.warning(
                    "Rate limit exceeded",
                    type=limit_type.value,
                    identifier=identifier,
                    retry_after=result.retry_after,
                )
                return result

        return RateLimitResult(allowed=True, remaining=999, reset_after=60, limit=999)

    async def reset(
        self,
        limit_type: RateLimitType,
        identifier: str | int | None = None,
    ) -> None:
        """Сбросить rate limit"""
        await cache.connect()
        key = self._get_key(limit_type, identifier)
        try:
            await cache.redis.delete(key)
        except:
            if key in self._local_cache:
                del self._local_cache[key]


# === Singleton ===
rate_limiter = RateLimiter()


# === Decorators ===

def rate_limit(
    limit_type: RateLimitType = RateLimitType.USER,
    get_identifier: Callable[..., int | str | None] | None = None,
):
    """
    Декоратор для rate limiting

    Использование:
        @rate_limit(RateLimitType.DOWNLOAD, lambda user_id, **_: user_id)
        async def download_handler(user_id: int, ...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            identifier = None
            if get_identifier:
                identifier = get_identifier(*args, **kwargs)

            result = await rate_limiter.check(limit_type, identifier)

            if not result.allowed:
                raise RateLimitExceeded(
                    f"Rate limit exceeded. Retry after {result.retry_after} seconds.",
                    retry_after=result.retry_after,
                )

            return await func(*args, **kwargs)

        return wrapper
    return decorator


class RateLimitExceeded(Exception):
    """Исключение при превышении rate limit"""
    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after
