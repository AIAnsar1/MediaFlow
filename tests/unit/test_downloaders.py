import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from services.downloader import (
    download_service,
    DownloadService,
    DownloadRequest,
    DownloadResult,
    MediaPlatform,
)
from services.media.youtube import YouTubeDownloader
from services.media.instagram import InstagramDownloader
from services.media.tiktok import TikTokDownloader
from services.media.pinterest import PinterestDownloader


class TestDownloadService:
    """Tests for DownloadService"""

    def test_detect_platform_youtube(self, sample_urls):
        """Test YouTube URL detection"""
        assert download_service.detect_platform(sample_urls["youtube"]) == MediaPlatform.YOUTUBE
        assert download_service.detect_platform(sample_urls["youtube_short"]) == MediaPlatform.YOUTUBE
        assert download_service.detect_platform(sample_urls["youtube_shorts"]) == MediaPlatform.YOUTUBE

    def test_detect_platform_instagram(self, sample_urls):
        """Test Instagram URL detection"""
        assert download_service.detect_platform(sample_urls["instagram_post"]) == MediaPlatform.INSTAGRAM
        assert download_service.detect_platform(sample_urls["instagram_reel"]) == MediaPlatform.INSTAGRAM

    def test_detect_platform_tiktok(self, sample_urls):
        """Test TikTok URL detection"""
        assert download_service.detect_platform(sample_urls["tiktok"]) == MediaPlatform.TIKTOK
        assert download_service.detect_platform(sample_urls["tiktok_short"]) == MediaPlatform.TIKTOK

    def test_detect_platform_pinterest(self, sample_urls):
        """Test Pinterest URL detection"""
        assert download_service.detect_platform(sample_urls["pinterest"]) == MediaPlatform.PINTEREST
        assert download_service.detect_platform(sample_urls["pinterest_short"]) == MediaPlatform.PINTEREST

    def test_detect_platform_unknown(self, sample_urls):
        """Test unknown URL detection"""
        assert download_service.detect_platform(sample_urls["invalid"]) == MediaPlatform.UNKNOWN

    def test_get_downloader(self):
        """Test getting downloader for platform"""
        assert isinstance(download_service.get_downloader(MediaPlatform.YOUTUBE), YouTubeDownloader)
        assert isinstance(download_service.get_downloader(MediaPlatform.INSTAGRAM), InstagramDownloader)
        assert isinstance(download_service.get_downloader(MediaPlatform.TIKTOK), TikTokDownloader)
        assert isinstance(download_service.get_downloader(MediaPlatform.PINTEREST), PinterestDownloader)
        assert download_service.get_downloader(MediaPlatform.UNKNOWN) is None


class TestYouTubeDownloader:
    """Tests for YouTubeDownloader"""

    def setup_method(self):
        self.downloader = YouTubeDownloader()

    def test_match_url_valid(self, sample_urls):
        """Test valid YouTube URL matching"""
        assert self.downloader.match_url(sample_urls["youtube"])
        assert self.downloader.match_url(sample_urls["youtube_short"])
        assert self.downloader.match_url(sample_urls["youtube_shorts"])

    def test_match_url_invalid(self, sample_urls):
        """Test invalid URL rejection"""
        assert not self.downloader.match_url(sample_urls["instagram_post"])
        assert not self.downloader.match_url(sample_urls["invalid"])

    def test_extract_id_regular(self):
        """Test extracting video ID from regular URL"""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert self.downloader.extract_id(url) == "dQw4w9WgXcQ"

    def test_extract_id_short(self):
        """Test extracting video ID from short URL"""
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert self.downloader.extract_id(url) == "dQw4w9WgXcQ"

    def test_extract_id_shorts(self):
        """Test extracting video ID from shorts URL"""
        url = "https://www.youtube.com/shorts/abc123xyz"
        assert self.downloader.extract_id(url) == "abc123xyz"

    def test_extract_id_invalid(self):
        """Test extracting ID from invalid URL"""
        url = "https://example.com/video"
        assert self.downloader.extract_id(url) is None

    @pytest.mark.asyncio
    async def test_get_video_info_mock(self):
        """Test getting video info with mock"""
        with patch.object(self.downloader, '_get_info_sync') as mock_info:
            mock_info.return_value = {
                "id": "test123",
                "title": "Test Video",
                "duration": 120,
                "formats": [
                    {"format_id": "22", "height": 720, "ext": "mp4", "filesize": 10000000},
                    {"format_id": "18", "height": 360, "ext": "mp4", "filesize": 5000000},
                ],
            }

            info = await self.downloader.get_video_info("https://youtube.com/watch?v=test123")

            assert info is not None
            assert info["id"] == "test123"
            assert info["title"] == "Test Video"
            assert len(info["formats"]) > 0


class TestInstagramDownloader:
    """Tests for InstagramDownloader"""

    def setup_method(self):
        self.downloader = InstagramDownloader()

    def test_match_url_post(self, sample_urls):
        """Test Instagram post URL matching"""
        assert self.downloader.match_url(sample_urls["instagram_post"])

    def test_match_url_reel(self, sample_urls):
        """Test Instagram reel URL matching"""
        assert self.downloader.match_url(sample_urls["instagram_reel"])

    def test_match_url_invalid(self, sample_urls):
        """Test invalid URL rejection"""
        assert not self.downloader.match_url(sample_urls["youtube"])

    def test_extract_id_post(self):
        """Test extracting shortcode from post URL"""
        url = "https://www.instagram.com/p/ABC123xyz/"
        assert self.downloader.extract_id(url) == "ABC123xyz"

    def test_extract_id_reel(self):
        """Test extracting shortcode from reel URL"""
        url = "https://www.instagram.com/reel/XYZ789abc/"
        assert self.downloader.extract_id(url) == "XYZ789abc"


class TestTikTokDownloader:
    """Tests for TikTokDownloader"""

    def setup_method(self):
        self.downloader = TikTokDownloader()

    def test_match_url_video(self, sample_urls):
        """Test TikTok video URL matching"""
        assert self.downloader.match_url(sample_urls["tiktok"])

    def test_match_url_short(self, sample_urls):
        """Test TikTok short URL matching"""
        assert self.downloader.match_url(sample_urls["tiktok_short"])

    def test_match_url_invalid(self, sample_urls):
        """Test invalid URL rejection"""
        assert not self.downloader.match_url(sample_urls["youtube"])

    def test_extract_id(self):
        """Test extracting video ID"""
        url = "https://www.tiktok.com/@user/video/1234567890123456789"
        assert self.downloader.extract_id(url) == "1234567890123456789"


class TestPinterestDownloader:
    """Tests for PinterestDownloader"""

    def setup_method(self):
        self.downloader = PinterestDownloader()

    def test_match_url_pin(self, sample_urls):
        """Test Pinterest pin URL matching"""
        assert self.downloader.match_url(sample_urls["pinterest"])

    def test_match_url_short(self, sample_urls):
        """Test Pinterest short URL matching"""
        assert self.downloader.match_url(sample_urls["pinterest_short"])

    def test_match_url_invalid(self, sample_urls):
        """Test invalid URL rejection"""
        assert not self.downloader.match_url(sample_urls["youtube"])

    def test_extract_id(self):
        """Test extracting pin ID"""
        url = "https://www.pinterest.com/pin/123456789012345678/"
        assert self.downloader.extract_id(url) == "123456789012345678"