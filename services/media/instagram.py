import asyncio, os, re, json, shutil, subprocess, tempfile

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from services.downloader import BaseDownloader, DownloadRequest, DownloadResult, MediaPlatform
from app.logging import get_logger

log = get_logger("downloader.instagram")


class InstagramDownloader(BaseDownloader):
    """
    Загрузчик для Instagram

    Использует gallery-dl для загрузки постов, reels, stories
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
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.semaphore = asyncio.Semaphore(2)

        # Проверяем gallery-dl
        self.has_gallery_dl = shutil.which('gallery-dl') is not None
        if not self.has_gallery_dl:
            self.log.warning("gallery-dl not found, Instagram downloads may fail")

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
        """Скачать пост/reel с Instagram"""
        shortcode = self.extract_id(request.url) or "unknown"

        async with self.semaphore:
            output_dir = self.temp_dir / f"instagram_{shortcode}"
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
                    title=result.get("title", f"Instagram {shortcode}"),
                )

            except Exception as e:
                self.log.exception("Instagram download failed", error=str(e))
                return DownloadResult(success=False, error=str(e))

    def _download_sync(self, url: str, output_dir: Path) -> dict:
        """Синхронная загрузка через gallery-dl"""
        if not self.has_gallery_dl:
            return {"success": False, "error": "gallery-dl not installed"}

        try:
            cmd = [
                "gallery-dl",
                "--directory", str(output_dir),
                "--filename", "{category}_{id}.{extension}",
                "--no-mtime",
                "--write-info-json",
                url
            ]

            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
            )

            if process.returncode != 0:
                error_msg = process.stderr[:500] if process.stderr else "Unknown error"
                self.log.error("gallery-dl failed", stderr=error_msg)
                return {"success": False, "error": error_msg}

            # Ищем скачанные файлы
            media_files = [
                f for f in output_dir.glob("*")
                if f.suffix.lower() in (".mp4", ".jpg", ".jpeg", ".png", ".webp", ".gif")
            ]

            if not media_files:
                return {"success": False, "error": "No media files downloaded"}

            # Приоритет видео
            video_files = [f for f in media_files if f.suffix.lower() == ".mp4"]
            file_path = video_files[0] if video_files else media_files[0]

            # Пытаемся получить caption из info.json
            title = None
            info_files = list(output_dir.glob("*.json"))
            if info_files:
                try:
                    with open(info_files[0]) as f:
                        info = json.load(f)
                        desc = info.get("description", "")
                        if desc:
                            title = desc[:100]  # Первые 100 символов
                except:
                    pass

            return {
                "success": True,
                "file_path": str(file_path),
                "title": title,
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Download timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}
