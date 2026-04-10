"""Tests for CacheChannelService"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from models.cache_channel import CacheChannel
from services.cache_channel import (
    CacheChannelService,
    CacheChannelError,
    CacheChannelNotFoundError,
    CacheChannelAlreadyExistsError,
    NoCacheChannelAvailableError,
    CreateCacheChannelDTO,
    UpdateCacheChannelDTO,
)


class TestCacheChannelDTO:
    """Test DTOs"""

    def test_create_dto_defaults(self):
        dto = CreateCacheChannelDTO(
            name="Test Channel",
            telegram_id=-1001234567890,
        )
        assert dto.is_active is True
        assert dto.username is None
        assert dto.description is None

    def test_update_dto_all_none(self):
        dto = UpdateCacheChannelDTO()
        assert dto.name is None
        assert dto.description is None
        assert dto.is_active is None


class TestCacheChannelService:
    """Tests for CacheChannelService"""

    @pytest.mark.asyncio
    async def test_create(self, test_db):
        service = CacheChannelService(test_db)

        dto = CreateCacheChannelDTO(
            name="Test Channel",
            telegram_id=-1001234567890,
            username="test_channel",
        )

        channel = await service.create(dto)

        assert channel is not None
        assert channel.name == "Test Channel"
        assert channel.telegram_id == -1001234567890

    @pytest.mark.asyncio
    async def test_create_duplicate_telegram_id(self, test_db):
        service = CacheChannelService(test_db)

        dto = CreateCacheChannelDTO(
            name="Channel 1",
            telegram_id=-1001234567890,
        )
        await service.create(dto)

        dto2 = CreateCacheChannelDTO(
            name="Channel 2",
            telegram_id=-1001234567890,  # Same ID
        )

        with pytest.raises(CacheChannelAlreadyExistsError):
            await service.create(dto2)

    @pytest.mark.asyncio
    async def test_create_duplicate_username(self, test_db):
        service = CacheChannelService(test_db)

        dto = CreateCacheChannelDTO(
            name="Channel 1",
            telegram_id=-1001111111111,
            username="my_channel",
        )
        await service.create(dto)

        dto2 = CreateCacheChannelDTO(
            name="Channel 2",
            telegram_id=-1002222222222,
            username="MY_CHANNEL",  # Case-insensitive
        )

        with pytest.raises(CacheChannelAlreadyExistsError):
            await service.create(dto2)

    @pytest.mark.asyncio
    async def test_get_by_id(self, test_db):
        service = CacheChannelService(test_db)

        dto = CreateCacheChannelDTO(
            name="Test Channel",
            telegram_id=-1001234567890,
        )
        channel = await service.create(dto)

        found = await service.get_by_id(channel.id)
        assert found.id == channel.id

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, test_db):
        service = CacheChannelService(test_db)

        from uuid import uuid4
        with pytest.raises(CacheChannelNotFoundError):
            await service.get_by_id(uuid4())

    @pytest.mark.asyncio
    async def test_get_by_telegram_id(self, test_db):
        service = CacheChannelService(test_db)

        dto = CreateCacheChannelDTO(
            name="Test Channel",
            telegram_id=-1001234567890,
        )
        await service.create(dto)

        found = await service.get_by_telegram_id(-1001234567890)
        assert found.telegram_id == -1001234567890

    @pytest.mark.asyncio
    async def test_get_by_telegram_id_not_found(self, test_db):
        service = CacheChannelService(test_db)

        with pytest.raises(CacheChannelNotFoundError):
            await service.get_by_telegram_id(-9999999999999)

    @pytest.mark.asyncio
    async def test_get_active_channel(self, test_db):
        service = CacheChannelService(test_db)

        dto = CreateCacheChannelDTO(
            name="Active Channel",
            telegram_id=-1001234567890,
            is_active=True,
        )
        await service.create(dto)

        channel = await service.get_active_channel()
        assert channel is not None
        assert channel.is_active is True

    @pytest.mark.asyncio
    async def test_get_active_channel_none(self, test_db):
        """No active channels — should raise"""
        service = CacheChannelService(test_db)

        with pytest.raises(NoCacheChannelAvailableError):
            await service.get_active_channel()

    @pytest.mark.asyncio
    async def test_list_all(self, test_db):
        service = CacheChannelService(test_db)

        await service.create(CreateCacheChannelDTO(name="Ch1", telegram_id=-1001111111111))
        await service.create(CreateCacheChannelDTO(name="Ch2", telegram_id=-1002222222222))
        await test_db.commit()

        channels = await service.list_all()
        assert len(channels) >= 2

    @pytest.mark.asyncio
    async def test_list_all_active_only(self, test_db):
        service = CacheChannelService(test_db)

        await service.create(CreateCacheChannelDTO(name="Active", telegram_id=-1001111111111))

        dto = CreateCacheChannelDTO(name="Inactive", telegram_id=-1002222222222)
        inactive = await service.create(dto)
        await service.update(inactive.id, UpdateCacheChannelDTO(is_active=False))
        await test_db.commit()

        active = await service.list_all(only_active=True)
        assert len(active) == 1
        assert active[0].name == "Active"

    @pytest.mark.asyncio
    async def test_update(self, test_db):
        service = CacheChannelService(test_db)

        channel = await service.create(
            CreateCacheChannelDTO(name="Old Name", telegram_id=-1001234567890)
        )

        updated = await service.update(channel.id, UpdateCacheChannelDTO(name="New Name"))
        assert updated.name == "New Name"

    @pytest.mark.asyncio
    async def test_update_no_changes(self, test_db):
        service = CacheChannelService(test_db)

        channel = await service.create(
            CreateCacheChannelDTO(name="Test", telegram_id=-1001234567890)
        )

        updated = await service.update(channel.id, UpdateCacheChannelDTO())
        assert updated.name == "Test"  # Unchanged

    @pytest.mark.asyncio
    async def test_toggle_active(self, test_db):
        service = CacheChannelService(test_db)

        channel = await service.create(
            CreateCacheChannelDTO(name="Test", telegram_id=-1001234567890, is_active=True)
        )

        assert channel.is_active is True

        toggled = await service.toggle_active(channel.id)
        assert toggled.is_active is False

        toggled = await service.toggle_active(channel.id)
        assert toggled.is_active is True

    @pytest.mark.asyncio
    async def test_delete(self, test_db):
        service = CacheChannelService(test_db)

        channel = await service.create(
            CreateCacheChannelDTO(name="Test", telegram_id=-1001234567890)
        )

        await service.delete(channel.id)

        with pytest.raises(CacheChannelNotFoundError):
            await service.get_by_id(channel.id)

    @pytest.mark.asyncio
    async def test_delete_by_telegram_id(self, test_db):
        service = CacheChannelService(test_db)

        await service.create(
            CreateCacheChannelDTO(name="Test", telegram_id=-1001234567890)
        )

        await service.delete_by_telegram_id(-1001234567890)

        with pytest.raises(CacheChannelNotFoundError):
            await service.get_by_telegram_id(-1001234567890)

    @pytest.mark.asyncio
    async def test_delete_by_telegram_id_not_found(self, test_db):
        service = CacheChannelService(test_db)

        with pytest.raises(CacheChannelNotFoundError):
            await service.delete_by_telegram_id(-9999999999999)

    def test_normalize_username(self):
        """Test username normalization"""
        svc = CacheChannelService  # access static method via class
        assert svc._normalize_username("@MyChannel") == "mychannel"
        assert svc._normalize_username("MyChannel") == "mychannel"
        assert svc._normalize_username("  @MyChannel  ") == "@mychannel"  # strips @ but not leading spaces
        assert svc._normalize_username(None) is None
        assert svc._normalize_username("") is None
