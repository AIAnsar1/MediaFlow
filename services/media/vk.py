import asyncio
import re
import shutil
import yt_dlp

from pathlib import Path


from services.downloader import BaseDownloader, DownloadRequest, DownloadResult, MediaPlatform
from app.logging import get_logger

log = get_logger("downloader.vk")


class VKDownloader(BaseDownloader):
    """
    Загрузчик для VK Video — Ultra Fast mode
    """

    platform = MediaPlatform.OTHER  # или добавить VK в enum

    def __init__(self):
        super().__init__()
        self.semaphore = asyncio.Semaphore(6)  # 6 concurrent VK downloads

    def match_url(self, url: str) -> bool:
        return "vk.com" in url or "vkvideo.ru" in url

    def extract_id(self, url: str) -> str | None:
        """Извлечь video ID"""
        match = re.search(r"video(-?\d+_\d+)", url)
        if match:
            return match.group(1)
        match = re.search(r"clip(-?\d+_\d+)", url)
        if match:
            return match.group(1)
        return None

    async def download(self, request: DownloadRequest) -> DownloadResult:
        """Скачать видео с VK — Ultra Fast"""
        video_id = self.extract_id(request.url) or "unknown"

        async with self.semaphore:
            output_path = str(self.temp_dir / f"vk_{video_id}.%(ext)s")

            ydl_opts = {
                "format": "best[ext=mp4]/best",
                "outtmpl": output_path,
                "quiet": True,
                "no_warnings": True,
                "ignoreerrors": True,
                # Speed optimizations
                "socket_timeout": 20,
                "retries": 5,
                "fragment_retries": 5,
                "nocheckcertificate": True,
                "noplaylist": True,
                "writethumbnail": False,
                "writeinfojson": False,
                "concurrent_fragment_downloads": 4,
            }

            # FFmpeg
            ffmpeg_path = shutil.which("ffmpeg")
            if ffmpeg_path:
                ydl_opts["ffmpeg_location"] = ffmpeg_path
                ydl_opts["merge_output_format"] = "mp4"

            # ARIA2C - Ultra Fast mode
            if shutil.which("aria2c"):
                ydl_opts["external_downloader"] = "aria2c"
                ydl_opts["external_downloader_args"] = {
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

            try:
                # Use asyncio.to_thread for Python 3.12+
                result = await asyncio.to_thread(self._download_sync, request.url, ydl_opts)

                if not result["success"]:
                    return DownloadResult(success=False, error=result.get("error"))

                file_path = result.get("file_path")
                if not file_path or not Path(file_path).exists():
                    # Пробуем найти файл
                    mp4_files = list(self.temp_dir.glob(f"vk_{video_id}*.mp4"))
                    if mp4_files:
                        file_path = str(mp4_files[0])

                if not file_path or not Path(file_path).exists():
                    return DownloadResult(success=False, error="File not found")

                return DownloadResult(
                    success=True,
                    file_path=Path(file_path),
                    title=result.get("title", "VK Video"),
                    duration=result.get("duration"),
                )

            except Exception as e:
                self.log.exception("VK download failed", error=str(e))
                return DownloadResult(success=False, error=str(e))

    def _download_sync(self, url: str, ydl_opts: dict) -> dict:
        """Синхронная загрузка"""
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

                if not info:
                    return {"success": False, "error": "Failed to extract info"}

                # Determine file path
                file_path = info.get("requested_downloads", [{}])[0].get("filepath") or ydl.prepare_filename(info)

                return {
                    "success": True,
                    "file_path": file_path,
                    "title": info.get("title", "VK Video"),
                    "duration": info.get("duration"),
                }

        except Exception as e:
            return {"success": False, "error": str(e)}
