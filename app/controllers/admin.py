from litestar import Controller, get
from litestar.response import Template
from litestar.di import Provide
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from repositories import BotRepository, UserRepository, MediaRepository


class AdminController(Controller):
    path = "/admin"
    dependencies = {"session": Provide(get_session)}

    @get("/", name="admin:dashboard")
    async def dashboard(self, session: AsyncSession) -> Template:
        bot_repo = BotRepository(session)
        user_repo = UserRepository(session)
        media_repo = MediaRepository(session)

        bots = await bot_repo.get_all()
        total_users = await user_repo.count()
        total_media = await media_repo.count()
        source_stats = await media_repo.get_stats_by_source()
        language_stats = await user_repo.get_language_stats()

        return Template(
            template_name="admin/dashboard.html",
            context={
                "stats": {
                    "total_downloads": total_media,
                    "total_users": total_users,
                    "total_bots": len(bots),
                },
                "recent_downloads": [],
                "bots": bots,
                "total_media": total_media,
                "source_stats": source_stats,
                "language_stats": language_stats,
            }
        )
