from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.cache_channel import CacheChannel
from repositories.cache_channel import CacheChannelRepository
from services.cache import cache as redis_cache
from app.logging import get_logger

log = get_logger("service.cache_channel")


@dataclass(frozen=True, slots=True)
class CreateCacheChannelDTO:
    """Данные для создания кэш-канала."""
    name: str
    telegram_id: int
    username: str | None = None
    description: str | None = None
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class UpdateCacheChannelDTO:
    """Данные для обновления кэш-канала (все поля опциональны)."""
    name: str | None = None
    username: str | None = None
    description: str | None = None
    is_active: bool | None = None


class CacheChannelError(Exception):
    """Базовая ошибка сервиса кэш-каналов."""


class CacheChannelAlreadyExistsError(CacheChannelError):
    """Канал с таким telegram_id или username уже существует."""


class CacheChannelNotFoundError(CacheChannelError):
    """Канал не найден."""


class NoCacheChannelAvailableError(CacheChannelError):
    """Нет ни одного активного кэш-канала."""


class CacheChannelService:

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = CacheChannelRepository(session)


    async def create(self, dto: CreateCacheChannelDTO) -> CacheChannel:
        # Нормализация username
        username = self._normalize_username(dto.username)
        # Проверка уникальности по telegram_id
        existing_by_id = await self._repo.get_by_telegram_id(dto.telegram_id)

        if existing_by_id is not None:
            raise CacheChannelAlreadyExistsError(f"Канал с telegram_id={dto.telegram_id} уже зарегистрирован")

        # Проверка уникальности по username
        if username:
            existing_by_username = await self._repo.get_by_username(username)
            if existing_by_username is not None:
                raise CacheChannelAlreadyExistsError(f"Канал с username=@{username} уже зарегистрирован")
        channel = await self._repo.create(name=dto.name,telegram_id=dto.telegram_id,username=username,description=dto.description,is_active=dto.is_active)
        log.info("Cache channel created",channel_id=str(channel.id),telegram_id=dto.telegram_id,name=dto.name)
        return channel


    async def get_by_id(self, channel_id: UUID) -> CacheChannel:
        channel = await self._repo.get_by_id(channel_id)

        if channel is None:
            raise CacheChannelNotFoundError(f"Канал с id={channel_id} не найден")
        return channel

    async def get_by_telegram_id(self, telegram_id: int) -> CacheChannel:
        channel = await self._repo.get_by_telegram_id(telegram_id)

        if channel is None:
            raise CacheChannelNotFoundError(f"Канал с telegram_id={telegram_id} не найден")
        return channel

    async def get_active_channel(self) -> CacheChannel:
        channel = await self._repo.get_active()

        if channel is None:
            raise NoCacheChannelAvailableError("Нет активных кэш-каналов. Добавьте канал через /admin cache_channel add")
        return channel

    async def get_next_active_channel(self) -> CacheChannel:
        """
        Get the next available cache channel using Least Recently Used (LRU) strategy.
        """
        # We order by last_used_at (NULLs first) and then by created_at
        stmt = (
            select(CacheChannel)
            .where(CacheChannel.is_active == True)
            .order_by(CacheChannel.last_used_at.asc().nullsfirst(), CacheChannel.created_at.asc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        channel = result.scalar_one_or_none()

        if not channel:
            # Fallback to default from settings if no active channels in DB
            raise NoCacheChannelAvailableError("No active cache channels found in database.")

        # Update last_used_at
        channel.last_used_at = datetime.now()
        await self._session.flush()

        return channel

    async def list_all(self,only_active: bool = False,offset: int = 0,limit: int = 50) -> list[CacheChannel]:
        if only_active:
            return await self._repo.get_all_active()
        channels = await self._repo.get_all(offset=offset,limit=limit,order_by="created_at",desc=False)
        return list(channels)


    async def update(self,channel_id: UUID,dto: UpdateCacheChannelDTO) -> CacheChannel:
        # Убедимся что канал существует
        channel = await self.get_by_id(channel_id)
        # Подготовка данных для обновления
        updates: dict = {}

        if dto.name is not None:
            updates["name"] = dto.name

        if dto.description is not None:
            updates["description"] = dto.description

        if dto.is_active is not None:
            updates["is_active"] = dto.is_active

        if dto.username is not None:
            new_username = self._normalize_username(dto.username)
            # Проверяем что новый username не занят другим каналом
            if new_username != channel.username:
                existing = await self._repo.get_by_username(new_username or "")
                if existing is not None and existing.id != channel.id:
                    raise CacheChannelAlreadyExistsError(f"Username @{new_username} уже используется другим каналом")
            updates["username"] = new_username

        if not updates:
            log.debug("Nothing to update", channel_id=str(channel_id))
            return channel

        updated = await self._repo.update(channel_id, **updates)
        log.info("Cache channel updated", channel_id=str(channel_id), fields=list(updates.keys()))
        return updated  # type: ignore[return-value]

    async def toggle_active(self, channel_id: UUID) -> CacheChannel:
        channel = await self.get_by_id(channel_id)
        new_state = not channel.is_active
        return await self.update(channel_id,UpdateCacheChannelDTO(is_active=new_state))


    async def delete(self, channel_id: UUID) -> None:
        await self.get_by_id(channel_id)
        await self._repo.delete(channel_id)
        log.info("Cache channel deleted", channel_id=str(channel_id))

    async def delete_by_telegram_id(self, telegram_id: int) -> None:
        channel = await self._repo.get_by_telegram_id(telegram_id)

        if channel is None:
            raise CacheChannelNotFoundError(f"Канал с telegram_id={telegram_id} не найден")
        await self._repo.delete(channel.id)
        log.info("Cache channel deleted by telegram_id", telegram_id=telegram_id)


    @staticmethod
    def _normalize_username(username: str | None) -> str | None:
        """Убрать @ и привести к нижнему регистру."""
        if not username:
            return None
        return username.lstrip("@").lower().strip()