from litestar import Request, Response
from litestar.middleware import AbstractMiddleware
from litestar.types import ASGIApp, Receive, Scope, Send
from litestar.status_codes import HTTP_429_TOO_MANY_REQUESTS
from litestar.datastructures import MutableScopeHeaders

from src.services.rate_limiter import rate_limiter, RateLimitType, RateLimitConfig
from src.logging import get_logger

log = get_logger("middleware.rate_limit")


class RateLimitMiddleware(AbstractMiddleware):
    """
    Rate Limit Middleware для Litestar

    Добавляет заголовки:
    - X-RateLimit-Limit
    - X-RateLimit-Remaining
    - X-RateLimit-Reset
    - Retry-After (при 429)
    """

    # Endpoints с особыми лимитами
    ENDPOINT_LIMITS: dict[str, RateLimitConfig] = {
        "/webhook": RateLimitConfig(requests=1000, window=60),  # Webhook'и
        "/admin": RateLimitConfig(requests=100, window=60),     # Админка
        "/api": RateLimitConfig(requests=60, window=60),        # API
    }

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Получаем IP
        client_ip = self._get_client_ip(scope)
        path = scope.get("path", "/")

        # Определяем лимит для endpoint
        config = None
        for prefix, limit_config in self.ENDPOINT_LIMITS.items():
            if path.startswith(prefix):
                config = limit_config
                break

        # Проверяем rate limit
        result = await rate_limiter.check(
            RateLimitType.ENDPOINT,
            identifier=f"{client_ip}:{path.split('/')[1] if '/' in path else 'root'}",
            config=config,
        )

        if not result.allowed:
            # 429 Too Many Requests
            response = Response(
                content={
                    "error": "Too Many Requests",
                    "retry_after": result.retry_after,
                },
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                headers={
                    "Retry-After": str(result.retry_after),
                    "X-RateLimit-Limit": str(result.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(result.reset_after),
                },
            )

            log.warning(
                "Rate limit exceeded",
                ip=client_ip,
                path=path,
                retry_after=result.retry_after,
            )

            await response(scope, receive, send)
            return

        # Добавляем заголовки к ответу
        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableScopeHeaders(message)
                headers["X-RateLimit-Limit"] = str(result.limit)
                headers["X-RateLimit-Remaining"] = str(result.remaining)
                headers["X-RateLimit-Reset"] = str(result.reset_after)

            await send(message)

        await self.app(scope, receive, send_with_headers)

    def _get_client_ip(self, scope: Scope) -> str:
        """Получить IP клиента"""
        # Проверяем заголовки прокси
        headers = dict(scope.get("headers", []))

        # X-Forwarded-For
        forwarded = headers.get(b"x-forwarded-for", b"").decode()
        if forwarded:
            return forwarded.split(",")[0].strip()

        # X-Real-IP
        real_ip = headers.get(b"x-real-ip", b"").decode()
        if real_ip:
            return real_ip

        # Fallback to client
        client = scope.get("client")
        if client:
            return client[0]

        return "unknown"
