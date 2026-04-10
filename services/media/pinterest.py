import asyncio
import os
import re
import subprocess
import shutil

from pathlib import Path

from services.downloader import BaseDownloader, DownloadRequest, DownloadResult, MediaPlatform
from app.logging import get_logger

log = get_logger("downloader.pinterest")


class PinterestDownloader(BaseDownloader):
    """
    Загрузчик для Pinterest — Ultra Fast mode

    Uses yt-dlp with aria2c for maximum speed
    """

    platform = MediaPlatform.PINTEREST

    URL_PATTERNS = [
        r"(?:https?://)?(?:www\.)?pinterest\.com/pin/[\d]+",
        r"(?:https?://)?(?:www\.)?pinterest\.\w+/pin/[\d]+",
        r"(?:https?://)?pin\.it/[\w]+",
    ]

    def __init__(self):
        super().__init__()
        self.semaphore = asyncio.Semaphore(6)  # 6 concurrent Pinterest downloads
        self.has_yt_dlp = shutil.which("yt-dlp") is not None

    def match_url(self, url: str) -> bool:
        return "pinterest" in url or "pin.it" in url

    def extract_id(self, url: str) -> str | None:
        """Извлечь pin ID"""
        match = re.search(r"/pin/(\d+)", url)
        if match:
            return match.group(1)
        match = re.search(r"pin\.it/([\w]+)", url)
        if match:
            return match.group(1)
        return None

    def _get_ydl_opts(self, output_dir: Path) -> dict:
        """Ultra Fast yt-dlp settings for Pinterest"""
        opts = {
            "outtmpl": str(output_dir / "%(title).100s_%(id)s_%(autonumber)s.%(ext)s"),
            "format": "bestvideo[ext=mp4]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "noprogress": True,
            # Speed optimizations
            "socket_timeout": 20,
            "retries": 5,
            "fragment_retries": 5,
            "extract_flat": False,
            "nocheckcertificate": True,
            "writethumbnail": False,
            "writeinfojson": False,
            "concurrent_fragment_downloads": 4,
        }

        if shutil.which("ffmpeg"):
            opts["ffmpeg_location"] = shutil.which("ffmpeg")

        # ARIA2C - Ultra Fast mode
        if shutil.which("aria2c"):
            opts["external_downloader"] = "aria2c"
            opts["external_downloader_args"] = {
                "default": [
                    "-x",
                    "16",
                    "-s",
                    "16",
                    "-k",
                    "4M",
                    "--min-split-size=4M",
                    "--max-connection-per-server=16",
                    "--max-concurrent-downloads=16",
                    "--max-tries=5",
                    "--retry-wait=1",
                    "--timeout=15",
                    "--connect-timeout=10",
                    "--summary-interval=0",
                    "--download-result=hide",
                    "--quiet=true",
                    "--file-allocation=none",
                    "--disable-ipv6=true",
                    "--stream-piece-selector=geom",
                    "--async-dns=true",
                    "--async-dns-server=8.8.8.8,1.1.1.1",
                ]
            }

        return opts

    async def download(self, request: DownloadRequest) -> DownloadResult:
        """Скачать пин — Ultra Fast"""
        pin_id = self.extract_id(request.url) or "unknown"

        async with self.semaphore:
            output_dir = self.temp_dir / f"pinterest_{pin_id}"
            output_dir.mkdir(parents=True, exist_ok=True)

            try:
                # Use asyncio.to_thread for Python 3.12+
                result = await asyncio.to_thread(self._download_sync, request.url, output_dir)

                if not result["success"]:
                    return DownloadResult(success=False, error=result.get("error"))

                file_paths = result.get("file_paths", [])
                if not file_paths:
                    return DownloadResult(success=False, error="File not found")

                return DownloadResult(
                    success=True,
                    file_paths=[Path(p) for p in file_paths],
                    title=result.get("title", f"Pinterest {pin_id}"),
                )

            except Exception as e:
                self.log.exception("Pinterest download failed", error=str(e))
                return DownloadResult(success=False, error=str(e))

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
