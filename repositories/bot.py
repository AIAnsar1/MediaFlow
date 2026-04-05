from sqlalchemy import select, func
from src.repositories.base import BaseRepository
from src.models import Bot, BotStatus, User, Download


class BotRepository(BaseRepository[Bot]):
    model = Bot

    async def get_by_token(self, token: str) -> Bot | None:
        return await self.get_one(token=token)

    async def get_by_bot_id(self, bot_id: int) -> Bot | None:
        return await self.get_one(bot_id=bot_id)

    async def get_by_username(self, username: str) -> Bot | None:
        return await self.get_one(username=username)

    async def get_active_bots(self) -> list[Bot]:
        return list(await self.filter(status=BotStatus.ACTIVE))

    async def update_stats(self, bot_id: int) -> Bot | None:
        """Пересчитать статистику бота"""
        # Считаем пользователей
        user_count = await self.session.execute(
            select(func.count()).select_from(User).where(User.bot_id == bot_id)
        )
        total_users = user_count.scalar() or 0

        # Считаем загрузки
        download_count = await self.session.execute(
            select(func.count()).select_from(Download).where(Download.bot_id == bot_id)
        )
        total_downloads = download_count.scalar() or 0

        return await self.update(
            bot_id,
            total_users=total_users,
            total_downloads=total_downloads,
        )

    async def token_exists(self, token: str) -> bool:
        return await self.exists(token=token)
