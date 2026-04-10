import asyncio
import os
import re
import json
import shutil
import subprocess
import tempfile

from pathlib import Path

from services.downloader import BaseDownloader, DownloadRequest, DownloadResult, MediaPlatform
from app.logging import get_logger

log = get_logger("downloader.instagram")


class InstagramDownloader(BaseDownloader):
    """
    Загрузчик для Instagram

    Использует yt-dlp для загрузки постов, reels, stories
    """

    platform = MediaPlatform.INSTAGRAM

    URL_PATTERNS = [
        r"(?:https?://)?(?:www\.)?instagram\.com/p/[\w-]+",
        r"(?:https?://)?(?:www\.)?instagram\.com/reel/[\w-]+",
        r"(?:https?://)?(?:www\.)?instagram\.com/stories/[\w]+/[\d]+",
        r"(?:https?://)?(?:www\.)?instagram\.com/[\w]+/(?:p|reel)/[\w-]+",
    ]

    def __init__(self):
        super().__init__()
        # No need for ThreadPoolExecutor with asyncio.to_thread (Python 3.12+)
        self.semaphore = asyncio.Semaphore(4)  # Allow 4 concurrent Instagram downloads

        # Проверяем yt-dlp
        self.has_yt_dlp = shutil.which("yt-dlp") is not None
        if not self.has_yt_dlp:
            self.log.warning("yt-dlp not found, Instagram downloads may fail")

    def match_url(self, url: str) -> bool:
        return "instagram.com" in url

    def extract_id(self, url: str) -> str | None:
        """Извлечь shortcode"""
        patterns = [
            r"/p/([\w-]+)",
            r"/reel/([\w-]+)",
            r"/stories/[\w]+/([\d]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def download(self, request: DownloadRequest) -> DownloadResult:
        """Скачать пост/reel с Instagram — Ultra Fast mode"""
        shortcode = self.extract_id(request.url) or "unknown"

        async with self.semaphore:
            output_dir = self.temp_dir / f"instagram_{shortcode}"
            output_dir.mkdir(parents=True, exist_ok=True)

            try:
                # Use asyncio.to_thread for Python 3.12+ (faster than executor)
                result = await asyncio.to_thread(self._download_sync, request.url, output_dir)

                if not result["success"]:
                    return DownloadResult(success=False, error=result.get("error"))

                file_paths = result.get("file_paths", [])
                if not file_paths:
                    return DownloadResult(success=False, error="File not found")

                # Sort files by size (largest first — likely the main content)
                paths = [Path(p) for p in file_paths]
                paths.sort(key=lambda p: p.stat().st_size, reverse=True)

                return DownloadResult(
                    success=True,
                    file_paths=paths,
                    title=result.get("title", f"Instagram {shortcode}"),
                )

            except Exception as e:
                self.log.exception("Instagram download failed", error=str(e))
                return DownloadResult(success=False, error=str(e))

    def _get_ydl_opts(self, output_dir: Path) -> dict:
        """
        Optimized yt-dlp options for Ultra Fast Instagram downloads.

        Uses aria2c with aggressive parallelism, connection reuse,
        and optimized buffer sizes for maximum throughput.
        """
        opts = {
            "outtmpl": str(output_dir / "%(title).100s_%(id)s_%(autonumber)s.%(ext)s"),
            # Prefer standalone mp4 for faster processing (no merge needed)
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "noprogress": True,
            # Aggressive timeouts for fast failure
            "socket_timeout": 20,
            "retries": 5,
            "fragment_retries": 5,
            "extract_flat": False,
            # Speed optimizations
            "nocheckcertificate": True,
            "prefer_insecure": False,
            # Disable unnecessary extraction
            "writethumbnail": False,
            "writeinfojson": False,
            # Fast concurrent segments
            "concurrent_fragment_downloads": 4,
        }

        # FFmpeg for fast merge
        if shutil.which("ffmpeg"):
            opts["ffmpeg_location"] = shutil.which("ffmpeg")
            opts["postprocessors"] = [
                {
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }
            ]

        # ARIA2C - Ultra Fast mode with aggressive parallelism
        if shutil.which("aria2c"):
            opts["external_downloader"] = "aria2c"
            opts["external_downloader_args"] = {
                "default": [
                    # Connection optimization
                    "-x",
                    "16",  # Max connections per server
                    "-s",
                    "16",  # Split file into 16 parts
                    "-k",
                    "4M",  # Minimum split size (larger = faster)
                    "--min-split-size=4M",
                    # Server optimization
                    "--max-connection-per-server=16",
                    "--max-concurrent-downloads=16",
                    "--max-tries=5",
                    "--retry-wait=1",
                    # Timeout & speed
                    "--timeout=15",
                    "--connect-timeout=10",
                    # Disable logging for speed
                    "--summary-interval=0",
                    "--download-result=hide",
                    "--quiet=true",
                    # Buffer optimization
                    "--file-allocation=none",  # Skip pre-allocation
                    "--allow-overwrite=true",
                    # Network optimization
                    "--disable-ipv6=true",  # Faster DNS resolution
                    "--stream-piece-selector=geom",  # Geometric piece selection
                    "--async-dns=true",
                    "--async-dns-server=8.8.8.8,1.1.1.1",
                ]
            }
            log.debug("Aria2c enabled with Ultra Fast settings")

        return opts

    def _download_sync(self, url: str, output_dir: Path) -> dict:
        """Синхронная загрузка через yt-dlp"""
        if not self.has_yt_dlp:
            return {"success": False, "error": "yt-dlp not installed"}

        import yt_dlp

        ydl_opts = self._get_ydl_opts(output_dir)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

                if not info:
                    return {"success": False, "error": "Failed to extract info"}

            # Ищем скачанные файлы
            media_files = [f for f in output_dir.glob("*") if f.suffix.lower() in (".mp4", ".jpg", ".jpeg", ".png", ".webp", ".gif")]

            if not media_files:
                return {"success": False, "error": "No media files downloaded"}

            # Пытаемся получить caption из info
            title = info.get("description") or info.get("title")

            return {
                "success": True,
                "file_paths": [str(f) for f in media_files],  # Return multiple files!
                "title": title[:100] if title else None,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
