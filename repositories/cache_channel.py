from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.cache_channel import CacheChannel
from repositories.base import BaseRepository



class CacheChannelRepository(BaseRepository[CacheChannel]):
    model = CacheChannel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_telegram_id(self, telegram_id: int) -> CacheChannel|None:
        stmt = select(self.model).where(self.model.telegram_id == telegram_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> CacheChannel | None:
        # Нормализуем — убираем @ если передали с ним
        clean_username = username.lstrip("@").lower()
        stmt = select(self.model).where(self.model.username == clean_username)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active(self) -> CacheChannel | None:
        stmt = (select(self.model).where(self.model.is_active == True).order_by(self.model.created_at.asc()).limit(1))  # noqa: E712
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_active(self) -> list[CacheChannel]:
        stmt = (select(self.model).where(self.model.is_active == True).order_by(self.model.created_at.asc())) # noqa: E712
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def deactivate(self, telegram_id: int) -> bool:
        channel = await self.get_by_telegram_id(telegram_id)

        if channel is None:
            return False
        channel.is_active = False
        await self.session.flush()
        self._log.info("Channel deactivated", telegram_id=telegram_id)
        return True

    async def activate(self, telegram_id: int) -> bool:
        channel = await self.get_by_telegram_id(telegram_id)

        if channel is None:
            return False
        channel.is_active = True
        await self.session.flush()
        self._log.info("Channel activated", telegram_id=telegram_id)
        return True










