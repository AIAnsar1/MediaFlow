from typing import Any
from litestar import Request, Response
from litestar.connection import ASGIConnection
from litestar.handlers import BaseRouteHandler
from litestar.middleware import AbstractMiddleware
from litestar.types import ASGIApp, Receive, Scope, Send
from litestar.status_codes import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN
from litestar.exceptions import NotAuthorizedException
from litestar.datastructures import State

from src.services.auth import auth_service, AuthUser
from src.logging import get_logger

log = get_logger("middleware.auth")


class AuthMiddleware(AbstractMiddleware):
    """
    Authentication Middleware

    Проверяет:
    1. Session cookie для веб-интерфейса
    2. JWT Bearer token для API
    3. CSRF token для POST/PUT/DELETE
    """

    # Пути, не требующие авторизации
    PUBLIC_PATHS = {
        "/",
        "/admin/login",
        "/webhook",
        "/static",
        "/health",
        "/favicon.ico",
    }

    # Пути, требующие только API ключ (webhooks)
    WEBHOOK_PATHS = {
        "/webhook",
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

        path = scope.get("path", "/")
        method = scope.get("method", "GET")

        # Проверяем публичные пути
        if self._is_public_path(path):
            await self.app(scope, receive, send)
            return

        # Webhook пути - проверяем токен бота
        if self._is_webhook_path(path):
            await self.app(scope, receive, send)
            return

        # Получаем headers и cookies
        headers = dict(scope.get("headers", []))
        cookies = self._parse_cookies(headers.get(b"cookie", b"").decode())

        # Пробуем авторизацию
        user = await self._authenticate(headers, cookies)

        if not user:
            # Редирект на логин для веб или 401 для API
            if path.startswith("/api"):
                await send({
                    "type": "http.response.start",
                    "status": HTTP_401_UNAUTHORIZED,
                    "headers": [(b"content-type", b"application/json")],
                })
                await send({
                    "type": "http.response.body",
                    "body": b'{"error": "Unauthorized"}',
                })
            else:
                await send({
                    "type": "http.response.start",
                    "status": 302,
                    "headers": [(b"location", b"/admin/login")],
                })
                await send({
                    "type": "http.response.body",
                    "body": b"",
                })

            return

        # Проверяем CSRF для модифицирующих методов
        if method in ("POST", "PUT", "DELETE", "PATCH"):
            if not self._verify_csrf(headers, cookies):
                log.warning("CSRF validation failed", path=path)
                await send({
                    "type": "http.response.start",
                    "status": HTTP_403_FORBIDDEN,
                    "headers": [(b"content-type", b"application/json")],
                })
                await send({
                    "type": "http.response.body",
                    "body": b'{"error": "CSRF validation failed"}',
                })
                return

        # Добавляем user в scope
        scope["state"] = scope.get("state", {})
        scope["state"]["user"] = user

        await self.app(scope, receive, send)

    def _is_public_path(self, path: str) -> bool:
        """Проверить публичный путь"""
        for public in self.PUBLIC_PATHS:
            if path == public or (public != "/" and path.startswith(f"{public}/")):
                return True
        return False

    def _is_webhook_path(self, path: str) -> bool:
        """Проверить webhook путь"""
        return path.startswith("/webhook/")

    def _parse_cookies(self, cookie_header: str) -> dict[str, str]:
        """Парсинг cookies"""
        cookies = {}
        if cookie_header:
            for item in cookie_header.split(";"):
                item = item.strip()
                if "=" in item:
                    key, value = item.split("=", 1)
                    cookies[key.strip()] = value.strip()
        return cookies

    async def _authenticate(
        self,
        headers: dict,
        cookies: dict,
    ) -> AuthUser | None:
        """Попытка аутентификации"""

        # 1. Проверяем Bearer token
        auth_header = headers.get(b"authorization", b"").decode()
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            user = auth_service.verify_access_token(token)
            if user:
                return user

        # 2. Проверяем session cookie
        session_id = cookies.get("session_id")
        if session_id:
            session = await auth_service.get_session(session_id)
            if session:
                # Продлеваем сессию
                await auth_service.extend_session(session_id)
                return AuthUser(username=session["username"])

        return None

    def _verify_csrf(self, headers: dict, cookies: dict) -> bool:
        """Проверка CSRF"""
        session_id = cookies.get("session_id")
        if not session_id:
            return False

        # CSRF токен из заголовка или формы
        csrf_token = headers.get(b"x-csrf-token", b"").decode()

        if not csrf_token:
            # Пробуем из cookies
            csrf_token = cookies.get("csrf_token", "")

        if not csrf_token:
            return False

        return auth_service.verify_csrf_token(session_id, csrf_token)


# === Guard для защиты routes ===

async def admin_guard(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    """Guard для админских роутов"""
    user = connection.scope.get("state", {}).get("user")

    if not user:
        raise NotAuthorizedException("Authentication required")

    if not user.is_admin:
        raise NotAuthorizedException("Admin access required")
