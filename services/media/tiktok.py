import asyncio
import contextlib
import os
import re
import subprocess
import tempfile
import shutil
import yt_dlp

from pathlib import Path

from services.downloader import BaseDownloader, DownloadRequest, DownloadResult, MediaPlatform
from app.logging import get_logger

log = get_logger("downloader.tiktok")


class TikTokDownloader(BaseDownloader):
    """
    Загрузчик для TikTok — Ultra Fast mode

    - Uses asyncio.to_thread (Python 3.12+)
    - aria2c with aggressive parallelism
    - Watermark removal via ffmpeg (crop)
    """

    platform = MediaPlatform.TIKTOK

    URL_PATTERNS = [
        r"(?:https?://)?(?:www\.)?tiktok\.com/@[\w.]+/video/\d+",
        r"(?:https?://)?(?:vm|vt)\.tiktok\.com/[\w]+",
        r"(?:https?://)?(?:www\.)?tiktok\.com/t/[\w]+",
    ]

    HEADERS = {"user-agent": ("Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_6_3; en-us; Silk/1.0.146.3-Gen4_12000410) AppleWebKit/533.16 (KHTML, like Gecko) Version/5.0 Safari/533.16 Silk-Accelerated=true")}

    def __init__(self):
        super().__init__()
        self.semaphore = asyncio.Semaphore(6)  # 6 concurrent TikTok downloads

        # Проверяем наличие инструментов
        self.has_aria2c = shutil.which("aria2c") is not None
        self.has_ffmpeg = shutil.which("ffmpeg") is not None

    def match_url(self, url: str) -> bool:
        # Простая проверка
        return "tiktok.com" in url

    def extract_id(self, url: str) -> str | None:
        """Извлечь video ID"""
        match = re.search(r"/video/(\d+)", url)
        if match:
            return match.group(1)
        # Для коротких ссылок
        match = re.search(r"tiktok\.com/[\w/]+/([\w]+)", url)
        if match:
            return match.group(1)
        return None

    async def download(self, request: DownloadRequest) -> DownloadResult:
        """Скачать видео с TikTok — Ultra Fast"""
        video_id = self.extract_id(request.url) or "unknown"

        async with self.semaphore:
            output_dir = self.temp_dir / f"tiktok_{video_id}"
            output_dir.mkdir(parents=True, exist_ok=True)

            ydl_opts = self._get_ydl_opts(output_dir)

            try:
                # Use asyncio.to_thread for Python 3.12+
                result = await asyncio.to_thread(self._download_sync, request.url, ydl_opts, output_dir)

                if not result["success"]:
                    return DownloadResult(success=False, error=result.get("error"))

                file_paths = result.get("file_paths", [])
                if not file_paths:
                    return DownloadResult(success=False, error="File not found")

                # Удаляем водяной знак если есть ffmpeg (для видео)
                if self.has_ffmpeg:
                    for i, path_str in enumerate(file_paths):
                        if path_str.endswith(".mp4"):
                            try:
                                new_path = await self._remove_watermark(path_str)
                                if new_path and Path(new_path).exists():
                                    file_paths[i] = new_path
                            except Exception as e:
                                self.log.warning(f"Watermark removal failed for {path_str}", error=str(e))

                return DownloadResult(
                    success=True,
                    file_paths=[Path(p) for p in file_paths],
                    title=result.get("title", "TikTok Video"),
                    duration=result.get("duration"),
                )

            except Exception as e:
                self.log.exception("TikTok download failed", error=str(e))
                return DownloadResult(success=False, error=str(e))

    def _get_ydl_opts(self, output_dir: Path) -> dict:
        """Настройки yt-dlp для TikTok — Ultra Fast"""
        opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
            "outtmpl": str(output_dir / "%(title).100s_%(id)s_%(autonumber)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "noprogress": True,
            "http_headers": self.HEADERS,
            # Aggressive timeouts for fast failure
            "socket_timeout": 20,
            "retries": 5,
            "fragment_retries": 5,
            "extract_flat": False,
            # Speed optimizations
            "nocheckcertificate": True,
            "noplaylist": True,
            "writethumbnail": False,
            "writeinfojson": False,
            "concurrent_fragment_downloads": 4,
        }

        # FFmpeg postprocessor
        if self.has_ffmpeg:
            opts["postprocessors"] = [
                {
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }
            ]
            ffmpeg_path = shutil.which("ffmpeg")
            if ffmpeg_path:
                opts["ffmpeg_location"] = ffmpeg_path

        # ARIA2C - Ultra Fast mode
        if self.has_aria2c:
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
                    "--enable-http-keep-alive=true",
                    "--enable-http-pipelining=true",
                    "--file-allocation=none",
                    "--no-conf=true",
                    "--disable-ipv6=true",
                    "--stream-piece-selector=geom",
                    "--async-dns=true",
                    "--async-dns-server=8.8.8.8,1.1.1.1",
                ]
            }

        return opts

    def _download_sync(self, url: str, ydl_opts: dict, output_dir: Path) -> dict:
        """Синхронная загрузка"""
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

                if not info:
                    return {"success": False, "error": "Failed to extract info"}

            # Ищем скачанные файлы
            media_files = [str(f) for f in output_dir.glob("*") if f.suffix.lower() in (".mp4", ".jpg", ".jpeg", ".png", ".webp", ".gif")]

            if not media_files:
                return {"success": False, "error": "Downloaded file not found"}

            return {
                "success": True,
                "file_paths": media_files,
                "title": info.get("description") or info.get("title") or "TikTok Video",
                "duration": info.get("duration"),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _remove_watermark(self, file_path: str) -> str | None:
        """
        Удаление водяного знака TikTok через crop
        Обрезает нижние 185 пикселей
        """
        if not os.path.exists(file_path):
            return None

        new_path = file_path.replace(".mp4", "_nowm.mp4")

        try:
            command = [
                "ffmpeg",
                "-i",
                file_path,
                "-filter:v",
                "crop=in_w:in_h-185",  # Обрезаем водяной знак снизу
                "-c:a",
                "copy",
                "-preset",
                "ultrafast",
                "-movflags",
                "+faststart",
                "-y",
                new_path,
            ]

            self.log.debug("Removing watermark...")

            loop = asyncio.get_event_loop()
            process = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=120,
                ),
            )

            if process.returncode != 0:
                self.log.warning("FFmpeg failed", stderr=process.stderr[:200])
                return file_path

            if os.path.exists(new_path) and os.path.getsize(new_path) > 0:
                # Remove original
                with contextlib.suppress(BaseException):
                    os.remove(file_path)
                return new_path

            return file_path

        except Exception as e:
            self.log.warning("Watermark removal error", error=str(e))
            return file_path
