"""Tests for DownloadService — especially send_to_user with bot_username marketing"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from services.downloader import (
    DownloadService,
    DownloadRequest,
    DownloadResult,
    MediaPlatform,
)


@pytest.fixture
def download_service():
    """Create DownloadService without registering downloaders"""
    service = DownloadService()
    service.downloaders = []  # Skip real downloader registration
    return service


@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.send_video = AsyncMock(return_value=MagicMock(message_id=1, video=MagicMock(file_id="vid_123")))
    bot.send_photo = AsyncMock(return_value=MagicMock(message_id=2, photo=[MagicMock(file_id="photo_123")]))
    bot.send_audio = AsyncMock(return_value=MagicMock(message_id=3, audio=MagicMock(file_id="audio_123")))
    bot.send_animation = AsyncMock(return_value=MagicMock(message_id=4, animation=MagicMock(file_id="anim_123")))
    bot.send_document = AsyncMock(return_value=MagicMock(message_id=5, document=MagicMock(file_id="doc_123")))
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=6))
    bot.delete_message = AsyncMock(return_value=True)
    return bot


class TestSendToUser:
    """Tests for DownloadService.send_to_user"""

    @pytest.mark.asyncio
    async def test_send_to_user_with_bot_username(self, download_service, mock_bot):
        """Test that bot_username appears in caption"""
        result = DownloadResult(
            success=True,
            file_id="test_file_id",
            title="Test Video",
            quality="720p",
        )

        success = await download_service.send_to_user(
            bot=mock_bot,
            chat_id=123456,
            result=result,
            message_id=None,
            bot_username="TestDownloaderBot",
        )

        assert success is True

        # Check that send_video was called with correct caption
        call_args = mock_bot.send_video.call_args
        assert call_args is not None
        call_kwargs = call_args.kwargs
        caption = call_kwargs.get("caption", "")
        assert "Test Video" in caption
        assert "@TestDownloaderBot" in caption

    @pytest.mark.asyncio
    async def test_send_to_user_without_bot_username(self, download_service, mock_bot):
        """Test without bot_username — no marketing line"""
        result = DownloadResult(
            success=True,
            file_id="test_file_id",
            title="Test Video",
        )

        await download_service.send_to_user(
            bot=mock_bot,
            chat_id=123456,
            result=result,
            message_id=None,
            bot_username=None,
        )

        call_args = mock_bot.send_video.call_args
        assert call_args is not None
        call_kwargs = call_args.kwargs
        caption = call_kwargs.get("caption", "")
        assert "via @" not in caption

    @pytest.mark.asyncio
    async def test_send_to_user_no_file_id(self, download_service, mock_bot):
        """Test when no file_id is available"""
        result = DownloadResult(
            success=True,
            file_id=None,
        )

        success = await download_service.send_to_user(
            bot=mock_bot,
            chat_id=123456,
            result=result,
        )

        assert success is False

    @pytest.mark.asyncio
    async def test_send_to_user_deletes_progress_message(self, download_service, mock_bot):
        """Test that progress message is deleted"""
        result = DownloadResult(
            success=True,
            file_id="test_file_id",
            title="Test Video",
        )

        await download_service.send_to_user(
            bot=mock_bot,
            chat_id=123456,
            result=result,
            message_id=999,  # Progress message ID
        )

        mock_bot.delete_message.assert_called_once_with(123456, 999)

    @pytest.mark.asyncio
    async def test_send_to_user_with_custom_caption(self, download_service, mock_bot):
        """Test custom caption override"""
        result = DownloadResult(
            success=True,
            file_id="test_file_id",
        )

        await download_service.send_to_user(
            bot=mock_bot,
            chat_id=123456,
            result=result,
            caption="My Custom Caption",
            bot_username="TestBot",
        )

        call_args = mock_bot.send_video.call_args
        assert call_args is not None
        call_kwargs = call_args.kwargs
        assert call_kwargs["caption"] == "My Custom Caption"

    @pytest.mark.asyncio
    async def test_send_to_user_caption_with_platform_icon(self, download_service, mock_bot):
        """Test caption includes platform icon"""
        result = DownloadResult(
            success=True,
            file_id="test_file_id",
            platform_icon="📸",
            title="Instagram Post",
            quality="1080p",
            filesize_str="5.2 MB",
            file_count=1,
        )

        await download_service.send_to_user(
            bot=mock_bot,
            chat_id=123456,
            result=result,
            bot_username="MyBot",
        )

        # Platform icon "📸" triggers photo send, not video
        call_args = mock_bot.send_photo.call_args
        assert call_args is not None
        call_kwargs = call_args.kwargs
        caption = call_kwargs.get("caption", "")
        assert "📸" in caption
        assert "Instagram Post" in caption
        assert "1080p" in caption

    @pytest.mark.asyncio
    async def test_send_to_user_caption_truncated(self, download_service, mock_bot):
        """Test that long title is truncated to 1024 chars"""
        long_title = "A" * 2000
        result = DownloadResult(
            success=True,
            file_id="test_file_id",
            title=long_title,
        )

        await download_service.send_to_user(
            bot=mock_bot,
            chat_id=123456,
            result=result,
        )

        call_args = mock_bot.send_video.call_args
        assert call_args is not None
        call_kwargs = call_args.kwargs
        caption = call_kwargs.get("caption", "")
        assert len(caption) <= 1024
