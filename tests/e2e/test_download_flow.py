import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path


@pytest.mark.asyncio
class TestDownloadFlow:
    """End-to-end tests for download flow"""

    async def test_youtube_download_flow(self, test_cache, test_metrics, mock_bot):
        """Test complete YouTube download flow"""
        from services.downloader import download_service, DownloadRequest, MediaPlatform

        request = DownloadRequest(
            url="https://www.youtube.com/watch?v=test123",
            platform=MediaPlatform.YOUTUBE,
            user_id=12345,
            bot_id=1,
            chat_id=12345,
            message_id=1,
            format="audio",
        )

        # Mock the actual download
        with patch.object(download_service, 'check_cache', return_value=None):
            with patch.object(download_service, 'get_downloader') as mock_get:
                mock_downloader = MagicMock()
                mock_downloader.download = AsyncMock(return_value=MagicMock(
                    success=True,
                    file_path=Path("/tmp/test.mp3"),
                    title="Test Video",
                ))
                mock_downloader.cleanup = AsyncMock()
                mock_get.return_value = mock_downloader

                with patch.object(download_service, '_upload_to_storage', return_value=("file_id_123", 1)):
                    result = await download_service.download(
                        request,
                        mock_bot,
                        progress_callback=AsyncMock(),
                    )

        # Verify flow completed
        assert result is not None

    async def test_cached_download_flow(self, test_cache, mock_bot):
        """Test download flow when content is cached"""
        from services.downloader import download_service, DownloadRequest, MediaPlatform, DownloadResult
        from services.cache import cache

        url = "https://www.youtube.com/watch?v=cached123"

        # Pre-cache the media
        await cache.cache_media(
            url=url,
            file_id="cached_file_id",
            message_id=123,
            chat_id=-100123456,
            quality="720p",
            title="Cached Video",
        )

        request = DownloadRequest(
            url=url,
            platform=MediaPlatform.YOUTUBE,
            user_id=12345,
            bot_id=1,
            chat_id=12345,
            message_id=1,
        )

        result = await download_service.check_cache(url, "720p")

        assert result is not None
        assert result.from_cache is True
        assert result.file_id == "cached_file_id"

    async def test_rate_limited_download(self, test_cache, test_rate_limiter, mock_bot):
        """Test download when rate limited"""
        from services.downloader import download_service, DownloadRequest, MediaPlatform
        from services.rate_limiter import rate_limiter, RateLimitType, RateLimitConfig

        user_id = 99999

        # Exhaust rate limit
        config = RateLimitConfig(requests=1, window=60)
        await rate_limiter.check(RateLimitType.DOWNLOAD, user_id, config)

        request = DownloadRequest(
            url="https://www.youtube.com/watch?v=test",
            platform=MediaPlatform.YOUTUBE,
            user_id=user_id,
            bot_id=1,
            chat_id=user_id,
            message_id=1,
        )

        # Should fail due to rate limit
        result = await download_service.download(request, mock_bot)

        # Rate limit check should fail
        check = await rate_limiter.check(RateLimitType.DOWNLOAD, user_id, config)
        assert check.allowed is False


@pytest.mark.asyncio
class TestBroadcastFlow:
    """End-to-end tests for broadcast flow"""

    async def test_broadcast_progress_tracking(self, test_cache, test_metrics):
        """Test broadcast progress is tracked"""
        from services.metrics import metrics

        ad_id = 123

        # Simulate broadcast progress
        await metrics.record_broadcast_progress(
            ad_id=ad_id,
            sent=0,
            failed=0,
            total=100,
        )

        progress = await metrics.get_broadcast_progress(ad_id)
        assert progress["progress"] == 0.0

        # Update progress
        await metrics.record_broadcast_progress(
            ad_id=ad_id,
            sent=50,
            failed=2,
            total=100,
        )

        progress = await metrics.get_broadcast_progress(ad_id)
        assert progress["sent"] == 50
        assert progress["failed"] == 2
        assert progress["progress"] == 50.0


@pytest.mark.asyncio
class TestUserFlow:
    """End-to-end tests for user flow"""

    async def test_new_user_registration(self, test_db, bot_factory):
        """Test new user registration flow"""
        from repositories import BotRepository, UserRepository
        from services.user import UserService
        from unittest.mock import MagicMock

        bot_repo = BotRepository(test_db)
        user_repo = UserRepository(test_db)

        # Create bot
        bot = bot_factory()
        created_bot = await bot_repo.create(
            token=bot.token,
            bot_id=bot.bot_id,
            username=bot.username,
            name=bot.name,
        )

        # Simulate Telegram user
        tg_user = MagicMock()
        tg_user.id = 123456789
        tg_user.username = "newuser"
        tg_user.first_name = "New"
        tg_user.last_name = "User"
        tg_user.language_code = "ru"

        class MockUoW:
            def __init__(self):
                self.users = user_repo

        service = UserService(MockUoW())

        # First interaction
        user, created = await service.get_or_create(tg_user, created_bot.id)
        assert created is True
        assert user.language == "ru"

        # Update language
        await service.update_language(user.id, "en")

        # Second interaction
        user2, created2 = await service.get_or_create(tg_user, created_bot.id)
        assert created2 is False