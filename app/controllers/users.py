from litestar import Controller, get, post
from litestar.response import Template, Redirect
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

        users = await repo.get_all(
            offset=(page - 1) * limit,
            limit=limit,
        )

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

    @post("/{user_id:int}/toggle-ban", name="users:toggle_ban")
    async def toggle_ban(self, session: AsyncSession, user_id: int) -> Redirect:
        """Toggle user ban status"""
        repo = UserRepository(session)
        user = await repo.get_by_id(user_id)
        if user:
            new_state = not user.is_banned
            await repo.update(user_id, is_banned=new_state)
            await session.commit()
            return Redirect(path=f"/admin/users?message=User {'banned' if new_state else 'unbanned'}")
        return Redirect(path="/admin/users")

    @post("/{user_id:int}/delete", name="users:delete")
    async def delete_user(self, session: AsyncSession, user_id: int) -> Redirect:
        """Delete a user"""
        repo = UserRepository(session)
        await repo.delete(user_id)
        await session.commit()
        return Redirect(path="/admin/users?message=User deleted")
