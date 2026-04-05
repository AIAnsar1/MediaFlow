import asyncio, os, re, subprocess, shutil

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.services.downloader import BaseDownloader, DownloadRequest, DownloadResult, MediaPlatform
from src.logging import get_logger

log = get_logger("downloader.pinterest")


class PinterestDownloader(BaseDownloader):
    """
    Загрузчик для Pinterest

    Использует gallery-dl
    """

    platform = MediaPlatform.PINTEREST

    URL_PATTERNS = [
        r"(?:https?://)?(?:www\.)?pinterest\.com/pin/[\d]+",
        r"(?:https?://)?(?:www\.)?pinterest\.\w+/pin/[\d]+",
        r"(?:https?://)?pin\.it/[\w]+",
    ]

    def __init__(self):
        super().__init__()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.semaphore = asyncio.Semaphore(4)

        self.has_gallery_dl = shutil.which('gallery-dl') is not None

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

    async def download(self, request: DownloadRequest) -> DownloadResult:
        """Скачать пин"""
        pin_id = self.extract_id(request.url) or "unknown"

        async with self.semaphore:
            output_dir = self.temp_dir / f"pinterest_{pin_id}"
            output_dir.mkdir(parents=True, exist_ok=True)

            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self.executor,
                    lambda: self._download_sync(request.url, output_dir)
                )

                if not result["success"]:
                    return DownloadResult(success=False, error=result.get("error"))

                file_path = result.get("file_path")
                if not file_path or not Path(file_path).exists():
                    return DownloadResult(success=False, error="File not found")

                return DownloadResult(
                    success=True,
                    file_path=Path(file_path),
                    title=result.get("title", f"Pinterest {pin_id}"),
                )

            except Exception as e:
                self.log.exception("Pinterest download failed", error=str(e))
                return DownloadResult(success=False, error=str(e))

    def _download_sync(self, url: str, output_dir: Path) -> dict:
        """Синхронная загрузка"""
        if not self.has_gallery_dl:
            return {"success": False, "error": "gallery-dl not installed"}

        try:
            cmd = [
                "gallery-dl",
                "--directory", str(output_dir),
                "--filename", "{category}_{id}.{extension}",
                "--no-mtime",
                url
            ]

            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if process.returncode != 0:
                error_msg = process.stderr[:500] if process.stderr else "Unknown error"
                return {"success": False, "error": error_msg}

            # Ищем файлы
            media_files = [
                f for f in output_dir.glob("*")
                if f.suffix.lower() in (".mp4", ".jpg", ".jpeg", ".png", ".gif", ".webp")
            ]

            if not media_files:
                return {"success": False, "error": "No media files"}

            # Приоритет: видео > gif > изображения
            video_files = [f for f in media_files if f.suffix.lower() in (".mp4", ".gif")]
            file_path = video_files[0] if video_files else media_files[0]

            return {
                "success": True,
                "file_path": str(file_path),
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}
