import asyncio, re, shutil, yt_dlp

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


from services.downloader import BaseDownloader, DownloadRequest, DownloadResult, MediaPlatform
from app.logging import get_logger

log = get_logger("downloader.vk")


class VKDownloader(BaseDownloader):
    """Загрузчик для VK Video"""

    platform = MediaPlatform.OTHER  # или добавить VK в enum

    def __init__(self):
        super().__init__()
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.semaphore = asyncio.Semaphore(2)

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
        """Скачать видео с VK"""
        video_id = self.extract_id(request.url) or "unknown"

        async with self.semaphore:
            output_path = str(self.temp_dir / f"vk_{video_id}.%(ext)s")

            ydl_opts = {
                'format': 'best[ext=mp4]/best',
                'outtmpl': output_path,
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
                'socket_timeout': 30,
                'retries': 5,
            }

            # FFmpeg
            ffmpeg_path = shutil.which('ffmpeg')
            if ffmpeg_path:
                ydl_opts['ffmpeg_location'] = ffmpeg_path
                ydl_opts['merge_output_format'] = 'mp4'

            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self.executor,
                    lambda: self._download_sync(request.url, ydl_opts)
                )

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

                # Определяем путь
                if "requested_downloads" in info and info["requested_downloads"]:
                    file_path = info["requested_downloads"][0].get("filepath")
                else:
                    file_path = ydl.prepare_filename(info)

                return {
                    "success": True,
                    "file_path": file_path,
                    "title": info.get("title", "VK Video"),
                    "duration": info.get("duration"),
                }

        except Exception as e:
            return {"success": False, "error": str(e)}
