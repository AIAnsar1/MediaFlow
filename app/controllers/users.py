from litestar import Controller, get
from litestar.response import Template
from litestar.di import Provide
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from repositories import UserRepository
from app.middleware.auth import admin_guard


class UserController(Controller):
    path = "/admin/users"
    guards = [admin_guard]
    dependencies = {"session": Provide(get_session)}

    @get("/", name="users:list")
    async def list_users(
        self,
        session: AsyncSession,
        page: int = 1,
        limit: int = 20,
        search: str | None = None,
    ) -> Template:
        """User list with pagination and search"""
        repo = UserRepository(session)
        
        # Получаем пользователей
        users = await repo.get_all(
            offset=(page - 1) * limit,
            limit=limit,
        )
        
        # Общее количество
        total = await repo.count()
        
        return Template(
            template_name="admin/users/list.html",
            context={
                "users": users,
                "page": page,
                "limit": limit,
                "total": total,
                "search": search,
            }
        )

    @get("/{user_id:int}", name="users:detail")
    async def user_detail(
        self,
        session: AsyncSession,
        user_id: int,
    ) -> Template:
        """User details"""
        repo = UserRepository(session)
        user = await repo.get_by_id(user_id)
        
        return Template(
            template_name="admin/users/detail.html",
            context={"user": user}
        )
