from datetime import datetime, timedelta
from litestar import Controller, get, post
from litestar.response import Template, Redirect, Response
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.datastructures import Cookie

from src.services.auth import auth_service
from src.logging import get_logger

log = get_logger("controller.auth")


class AuthController(Controller):
    path = "/admin"

    @get("/login", name="auth:login_page")
    async def login_page(self, error: str | None = None) -> Template:
        """Страница логина"""
        return Template(
            template_name="admin/login.html",
            context={"error": error},
        )

    @post("/login", name="auth:login")
    async def login(
        self,
        data: dict = Body(media_type=RequestEncodingType.URL_ENCODED),
    ) -> Response:
        """Обработка логина"""
        username = data.get("username", "").strip()
        password = data.get("password", "")

        if not auth_service.authenticate_admin(username, password):
            log.warning("Failed login attempt", username=username)
            return Redirect(path="/admin/login?error=Invalid credentials")

        # Создаём сессию
        session_id = await auth_service.create_session(username)
        csrf_token = auth_service.generate_csrf_token(session_id)

        log.info("Admin logged in", username=username)

        # Устанавливаем cookies
        response = Redirect(path="/admin")
        response.cookies.append(
            Cookie(
                key="session_id",
                value=session_id,
                httponly=True,
                secure=True,  # В продакшене
                samesite="lax",
                max_age=86400,  # 24 часа
            )
        )
        response.cookies.append(
            Cookie(
                key="csrf_token",
                value=csrf_token,
                httponly=False,  # Доступен для JS
                secure=True,
                samesite="lax",
                max_age=86400,
            )
        )

        return response

    @post("/logout", name="auth:logout")
    async def logout(
        self,
        session_id: str | None = None,
    ) -> Response:
        """Выход"""
        if session_id:
            await auth_service.delete_session(session_id)

        response = Redirect(path="/admin/login")

        # Удаляем cookies
        response.cookies.append(
            Cookie(key="session_id", value="", max_age=0)
        )
        response.cookies.append(
            Cookie(key="csrf_token", value="", max_age=0)
        )

        return response

    @post("/refresh-token", name="auth:refresh")
    async def refresh_token(
        self,
        data: dict = Body(media_type=RequestEncodingType.JSON),
    ) -> Response:
        """Обновление JWT токена (для API)"""
        refresh_token = data.get("refresh_token")

        if not refresh_token:
            return Response(
                content={"error": "Refresh token required"},
                status_code=400,
            )

        new_access_token = await auth_service.refresh_access_token(refresh_token)

        if not new_access_token:
            return Response(
                content={"error": "Invalid refresh token"},
                status_code=401,
            )

        return Response(
            content={"access_token": new_access_token},
            status_code=200,
        )
