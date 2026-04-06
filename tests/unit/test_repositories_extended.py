import pytest
from datetime import datetime, timedelta

from repositories import (
    BotRepository,
    UserRepository,
    MediaRepository,
    AdRepository,
)
from models import BotStatus, MediaSource, MediaType, AdStatus


@pytest.mark.asyncio
class TestBotRepositoryExtended:
    """Extended tests for BotRepository"""

    async def test_get_by_bot_id(self, test_db, bot_factory):
        """Test getting bot by Telegram bot_id"""
        repo = BotRepository(test_db)
        bot = bot_factory()

        created = await repo.create(
            token=bot.token,
            bot_id=bot.bot_id,
            username=bot.username,
            name=bot.name,
        )

        found = await repo.get_by_bot_id(bot.bot_id)

        assert found is not None
        assert found.id == created.id
        assert found.bot_id == bot.bot_id

    async def test_get_by_username(self, test_db, bot_factory):
        """Test getting bot by username"""
        repo = BotRepository(test_db)
        bot = bot_factory()

        created = await repo.create(
            token=bot.token,
            bot_id=bot.bot_id,
            username=bot.username,
            name=bot.name,
        )

        found = await repo.get_by_username(bot.username)

        assert found is not None
        assert found.username == bot.username

    async def test_token_exists(self, test_db, bot_factory):
        """Test token existence check"""
        repo = BotRepository(test_db)
        bot = bot_factory()

        assert not await repo.token_exists(bot.token)

        await repo.create(
            token=bot.token,
            bot_id=bot.bot_id,
            username=bot.username,
            name=bot.name,
        )

        assert await repo.token_exists(bot.token)

    async def test_update_bot(self, test_db, bot_factory):
        """Test bot update"""
        repo = BotRepository(test_db)
        bot = bot_factory()

        created = await repo.create(
            token=bot.token,
            bot_id=bot.bot_id,
            username=bot.username,
            name=bot.name,
        )

        updated = await repo.update(created.id, name="Updated Name", status=BotStatus.INACTIVE)

        assert updated is not None
        assert updated.name == "Updated Name"
        assert updated.status == BotStatus.INACTIVE


@pytest.mark.asyncio
class TestUserRepositoryExtended:
    """Extended tests for UserRepository"""

    async def test_count_by_bot(self, test_db, bot_factory, user_factory):
        """Test counting users by bot"""
        from repositories import BotRepository

        bot_repo = BotRepository(test_db)
        user_repo = UserRepository(test_db)

        bot = bot_factory()
        created_bot = await bot_repo.create(
            token=bot.token,
            bot_id=bot.bot_id,
            username=bot.username,
            name=bot.name,
        )

        # Create 5 users
        for _ in range(5):
            user = user_factory(bot_id=created_bot.id)
            await user_repo.create(
                telegram_id=user.telegram_id,
                bot_id=created_bot.id,
                username=user.username,
                language=user.language,
            )

        count = await user_repo.count_by_bot(created_bot.id)
        assert count == 5

    async def test_get_language_stats(self, test_db, bot_factory, user_factory):
        """Test language statistics"""
        from repositories import BotRepository

        bot_repo = BotRepository(test_db)
        user_repo = UserRepository(test_db)

        bot = bot_factory()
        created_bot = await bot_repo.create(
            token=bot.token,
            bot_id=bot.bot_id,
            username=bot.username,
            name=bot.name,
        )

        # Create users with different languages
        for lang in ["en", "en", "ru", "ru", "ru"]:
            user = user_factory(bot_id=created_bot.id, language=lang)
            await user_repo.create(
                telegram_id=user.telegram_id,
                bot_id=created_bot.id,
                username=user.username,
                language=lang,
            )

        stats = await user_repo.get_language_stats(created_bot.id)

        assert stats["en"] == 2
        assert stats["ru"] == 3

    async def test_increment_downloads(self, test_db, bot_factory, user_factory):
        """Test download counter increment"""
        from repositories import BotRepository

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
        created_user = await user_repo.create(
            telegram_id=user.telegram_id,
            bot_id=created_bot.id,
            username=user.username,
        )

        assert created_user.total_downloads == 0

        await user_repo.increment_downloads(created_user.id)

        updated = await user_repo.get_by_id(created_user.id)
        assert updated.total_downloads == 1


@pytest.mark.asyncio
class TestMediaRepositoryExtended:
    """Extended tests for MediaRepository"""

    async def test_create_or_update_cache(self, test_db):
        """Test create or update cache"""
        repo = MediaRepository(test_db)

        url = "https://youtube.com/watch?v=test123"

        # First time - create
        media, created = await repo.create_or_update_cache(
            original_url=url,
            source=MediaSource.YOUTUBE,
            media_type=MediaType.VIDEO,
            quality="720p",
            telegram_file_id="file123",
        )

        assert created is True
        assert media.original_url == url

        # Second time - update
        media2, created2 = await repo.create_or_update_cache(
            original_url=url,
            source=MediaSource.YOUTUBE,
            media_type=MediaType.VIDEO,
            quality="720p",
            telegram_file_id="file456",
        )

        assert created2 is False
        assert media2.id == media.id
        assert media2.telegram_file_id == "file456"

    async def test_increment_downloads(self, test_db, media_factory):
        """Test download count increment"""
        repo = MediaRepository(test_db)

        media = await repo.create(
            source=MediaSource.YOUTUBE,
            original_url="https://youtube.com/test",
            media_type=MediaType.VIDEO,
            download_count=0,
        )

        await repo.increment_downloads(media.id)
        await repo.increment_downloads(media.id)
        await repo.increment_downloads(media.id)

        updated = await repo.get_by_id(media.id)
        assert updated.download_count == 3

    async def test_get_popular(self, test_db):
        """Test getting popular media"""
        repo = MediaRepository(test_db)

        # Create media with different download counts
        for i, count in enumerate([100, 50, 200, 30, 150]):
            await repo.create(
                source=MediaSource.YOUTUBE,
                original_url=f"https://youtube.com/video{i}",
                media_type=MediaType.VIDEO,
                telegram_file_id=f"file{i}",
                download_count=count,
            )

        popular = await repo.get_popular(limit=3)

        assert len(popular) == 3
        assert popular[0].download_count == 200
        assert popular[1].download_count == 150
        assert popular[2].download_count == 100


@pytest.mark.asyncio
class TestAdRepositoryExtended:
    """Extended tests for AdRepository"""

    async def test_get_by_uuid(self, test_db, ad_factory):
        """Test getting ad by UUID"""
        repo = AdRepository(test_db)

        ad = await repo.create(
            name="Test Ad",
            content="Test content",
        )

        found = await repo.get_by_uuid(ad.ad_uuid)

        assert found is not None
        assert found.id == ad.id

    async def test_get_active_ads(self, test_db, ad_factory):
        """Test getting active ads"""
        repo = AdRepository(test_db)

        # Create active and inactive ads
        await repo.create(name="Active 1", content="Content", is_active=True)
        await repo.create(name="Active 2", content="Content", is_active=True)
        await repo.create(name="Inactive", content="Content", is_active=False)

        active = await repo.get_active()

        assert len(active) == 2
        assert all(ad.is_active for ad in active)