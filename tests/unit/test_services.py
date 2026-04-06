import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy.orm import session

from services.user import UserService, UserDTO
from services.ad import AdService, AdCreateDTO
from repositories.uow import UnitOfWork
from models import AdStatus, AdMediaType


@pytest.mark.asyncio
class TestUserService:
    """Tests for UserService"""

    async def test_get_or_create_new_user(self, test_db, bot_factory, user_factory):
        """Test creating new user"""
        from repositories import BotRepository, UserRepository
        from aiogram.types import User as TgUser
        from unittest.mock import MagicMock

        # Create bot first
        bot_repo = BotRepository(test_db)
        bot = bot_factory()
        created_bot = await bot_repo.create(
            token=bot.token,
            bot_id=bot.bot_id,
            username=bot.username,
            name=bot.name,
        )

        # Mock Telegram user
        tg_user = MagicMock(spec=TgUser)
        tg_user.id = 123456789
        tg_user.username = "testuser"
        tg_user.first_name = "Test"
        tg_user.last_name = "User"
        tg_user.language_code = "en"

        # Create UoW mock
        class MockUoW:
            def __init__(self, session):
                self.users = UserRepository(session)

        uow = MockUoW(test_db)
        service = UserService(uow)

        user_dto, created = await service.get_or_create(tg_user, created_bot.id)

        assert created is True
        assert user_dto.telegram_id == 123456789
        assert user_dto.username == "testuser"
        assert user_dto.language == "en"

    async def test_get_or_create_existing_user(self, test_db, bot_factory, user_factory):
        """Test getting existing user"""
        from repositories import BotRepository, UserRepository
        from aiogram.types import User as TgUser
        from unittest.mock import MagicMock

        # Create bot and user
        bot_repo = BotRepository(test_db)
        user_repo = UserRepository(test_db)

        bot = bot_factory()
        created_bot = await bot_repo.create(
            token=bot.token,
            bot_id=bot.bot_id,
            username=bot.username,
            name=bot.name,
        )

        user = user_factory(bot_id=created_bot.id)
        await user_repo.create(
            telegram_id=user.telegram_id,
            bot_id=created_bot.id,
            username=user.username,
            first_name=user.first_name,
            language=user.language,
        )

        # Mock Telegram user with same ID
        tg_user = MagicMock(spec=TgUser)
        tg_user.id = user.telegram_id
        tg_user.username = "updated_username"
        tg_user.first_name = "Updated"
        tg_user.last_name = "Name"
        tg_user.language_code = "ru"

        class MockUoW:
            def __init__(self, session):
                self.users = UserRepository(session)

        uow = MockUoW(test_db)
        service = UserService(uow)

        user_dto, created = await service.get_or_create(tg_user, created_bot.id)

        assert created is False
        assert user_dto.telegram_id == user.telegram_id


@pytest.mark.asyncio
class TestAdService:
    """Tests for AdService"""

    async def test_create_ad(self, test_db, bot_factory):
        """Test creating advertisement"""
        from repositories import BotRepository, AdRepository

        # Create bot
        bot_repo = BotRepository(test_db)
        bot = bot_factory()
        created_bot = await bot_repo.create(
            token=bot.token,
            bot_id=bot.bot_id,
            username=bot.username,
            name=bot.name,
        )

        # Create UoW mock
        class MockUoW:
            def __init__(self, session):
                self.ads = AdRepository(session)
                self.ad_deliveries = None
                self.users = None

            async def commit(self):
                await session.commit()

        uow = MockUoW(test_db)
        uow.ads = AdRepository(test_db)

        dto = AdCreateDTO(
            name="Test Campaign",
            content="Test ad content",
            media_type=AdMediaType.NONE,
            bot_ids=[created_bot.id],
        )

        service = AdService(uow)
        ad = await service.create(dto)

        assert ad is not None
        assert ad.name == "Test Campaign"
        assert ad.content == "Test ad content"
        assert ad.status == AdStatus.DRAFT