from types import TracebackType
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import db
from repositories import (
    BotRepository,
    UserRepository,
    MediaRepository,
    AdRepository,
    AdDeliveryRepository,
    CacheChannelRepository,
)
from app.logging import get_logger

log = get_logger("uow")


class UnitOfWork:
    """
    Unit of Work - единая точка работы с репозиториями

    Использование:
        async with UnitOfWork() as uow:
            user = await uow.users.get_by_telegram_id(123, 1)
            bot = await uow.bots.get_by_id(1)
            await uow.commit()
    """

    def __init__(self):
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> "UnitOfWork":
        self._session = db.session_factory()

        # Инициализируем репозитории
        self.bots = BotRepository(self._session)
        self.users = UserRepository(self._session)
        self.media = MediaRepository(self._session)
        self.ads = AdRepository(self._session)
        self.ad_deliveries = AdDeliveryRepository(self._session)
        self.cache_channels = CacheChannelRepository(self._session)

        return self

    @property
    def session(self) -> AsyncSession:
        """Public access to the underlying session."""
        if self._session is None:
            raise RuntimeError("UnitOfWork is not initialized. Use 'async with UnitOfWork() as uow:'")
        return self._session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()
            log.error("UoW rollback", error=str(exc_val))
        await self._session.close()

    async def commit(self) -> None:
        """Зафиксировать транзакцию"""
        await self._session.commit()

    async def rollback(self) -> None:
        """Откатить транзакцию"""
        await self._session.rollback()

    async def flush(self) -> None:
        """Flush без commit"""
        await self._session.flush()
