import pytest
from datetime import datetime

from repositories import BotRepository, UserRepository, MediaRepository
from models import BotStatus, MediaSource, MediaType


@pytest.mark.asyncio
class TestBotRepository:
    """Tests for BotRepository"""

    async def test_create_bot(self, test_db, bot_factory):
        """Test bot creation"""
        repo = BotRepository(test_db)
        bot_data = bot_factory()

        created = await repo.create(
            token=bot_data.token,
            bot_id=bot_data.bot_id,
            username=bot_data.username,
            name=bot_data.name,
        )

        assert created.id is not None
        assert created.token == bot_data.token
        assert created.status == BotStatus.ACTIVE

    async def test_get_by_token(self, test_db, bot_factory):
        """Test get bot by token"""
        repo = BotRepository(test_db)
        bot_data = bot_factory()

        created = await repo.create(
            token=bot_data.token,
            bot_id=bot_data.bot_id,
            username=bot_data.username,
            name=bot_data.name,
        )

        found = await repo.get_by_token(bot_data.token)

        assert found is not None
        assert found.id == created.id

    async def test_get_active_bots(self, test_db, bot_factory):
        """Test get active bots"""
        repo = BotRepository(test_db)

        # Создаём 2 активных и 1 неактивный
        for _ in range(2):
            bot = bot_factory()
            await repo.create(
                token=bot.token,
                bot_id=bot.bot_id,
                username=bot.username,
                name=bot.name,
                status=BotStatus.ACTIVE,
            )

        inactive_bot = bot_factory()
        await repo.create(
            token=inactive_bot.token,
            bot_id=inactive_bot.bot_id,
            username=inactive_bot.username,
            name=inactive_bot.name,
            status=BotStatus.INACTIVE,
        )

        active = await repo.get_active_bots()

        assert len(active) == 2


@pytest.mark.asyncio
class TestUserRepository:
    """Tests for UserRepository"""

    async def test_create_user(self, test_db, bot_factory, user_factory):
        """Test user creation"""
        bot_repo = BotRepository(test_db)
        user_repo = UserRepository(test_db)

        # Создаём бота
        bot = bot_factory()
        created_bot = await bot_repo.create(
            token=bot.token,
            bot_id=bot.bot_id,
            username=bot.username,
            name=bot.name,
        )

        # Создаём пользователя
        user = user_factory(bot_id=created_bot.id)
        created_user = await user_repo.create(
            telegram_id=user.telegram_id,
            bot_id=created_bot.id,
            username=user.username,
            first_name=user.first_name,
            language=user.language,
        )

        assert created_user.id is not None
        assert created_user.telegram_id == user.telegram_id

    async def test_get_or_create(self, test_db, bot_factory, user_factory):
        """Test get_or_create user"""
        bot_repo = BotRepository(test_db)
        user_repo = UserRepository(test_db)

        bot = bot_factory()
        created_bot = await bot_repo.create(
            token=bot.token,
            bot_id=bot.bot_id,
            username=bot.username,
            name=bot.name,
        )

        telegram_id = 123456789

        # Первый раз - создаётся
        user1, created1 = await user_repo.get_or_create(
            telegram_id=telegram_id,
            bot_id=created_bot.id,
            username="testuser",
        )
        assert created1

        # Второй раз - возвращается существующий
        user2, created2 = await user_repo.get_or_create(
            telegram_id=telegram_id,
            bot_id=created_bot.id,
            username="testuser",
        )
        assert not created2
        assert user2.id == user1.id


@pytest.mark.asyncio
class TestMediaRepository:
    """Tests for MediaRepository"""

    async def test_create_media(self, test_db, media_factory):
        """Test media creation"""
        repo = MediaRepository(test_db)
        media = media_factory()

        created = await repo.create(
            source=media.source,
            original_url=media.original_url,
            media_type=media.media_type,
        )

        assert created.id is not None

    async def test_find_cached(self, test_db):
        """Test finding cached media"""
        repo = MediaRepository(test_db)
        url = "https://youtube.com/watch?v=test123"

        # Создаём с file_id
        await repo.create(
            source=MediaSource.YOUTUBE,
            original_url=url,
            media_type=MediaType.VIDEO,
            quality="720p",
            telegram_file_id="AgACAgIAAxk...",
        )

        cached = await repo.find_cached(url, quality="720p")

        assert cached is not None
        assert cached.telegram_file_id is not None

    async def test_stats_by_source(self, test_db):
        """Test stats by source"""
        repo = MediaRepository(test_db)

        # Создаём медиа с загрузками
        await repo.create(
            source=MediaSource.YOUTUBE,
            original_url="https://youtube.com/1",
            media_type=MediaType.VIDEO,
            download_count=10,
        )
        await repo.create(
            source=MediaSource.INSTAGRAM,
            original_url="https://instagram.com/1",
            media_type=MediaType.VIDEO,
            download_count=5,
        )

        stats = await repo.get_stats_by_source()

        assert "youtube" in stats
        assert stats["youtube"] == 10