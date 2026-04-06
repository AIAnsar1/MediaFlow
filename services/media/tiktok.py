import asyncio, os, re, subprocess, tempfile, shutil, yt_dlp

from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from services.downloader import BaseDownloader, DownloadRequest, DownloadResult, MediaPlatform
from app.logging import get_logger

log = get_logger("downloader.tiktok")


class TikTokDownloader(BaseDownloader):
    """
    Загрузчик для TikTok

    - Использует yt-dlp с aria2c
    - Удаление водяного знака через ffmpeg (crop)
    """

    platform = MediaPlatform.TIKTOK

    URL_PATTERNS = [
        r"(?:https?://)?(?:www\.)?tiktok\.com/@[\w.]+/video/\d+",
        r"(?:https?://)?(?:vm|vt)\.tiktok\.com/[\w]+",
        r"(?:https?://)?(?:www\.)?tiktok\.com/t/[\w]+",
    ]

    HEADERS = {
        'user-agent': (
            'Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_6_3; en-us; Silk/1.0.146.3-Gen4_12000410) '
            'AppleWebKit/533.16 (KHTML, like Gecko) Version/5.0 Safari/533.16 Silk-Accelerated=true'
        )
    }

    def __init__(self):
        super().__init__()
        self.executor = ThreadPoolExecutor(max_workers=8)
        self.semaphore = asyncio.Semaphore(4)

        # Проверяем наличие инструментов
        self.has_aria2c = shutil.which('aria2c') is not None
        self.has_ffmpeg = shutil.which('ffmpeg') is not None

        # Настройки aria2c
        self.aria2c_args = [
            '-x', '16', '-s', '16', '-k', '2M',
            '--min-split-size=2M',
            '--max-connection-per-server=16',
            '--max-concurrent-downloads=16',
            '--max-tries=10',
            '--retry-wait=1',
            '--timeout=10',
            '--summary-interval=0',
            '--download-result=hide',
            '--quiet=true',
            '--enable-http-keep-alive=true',
            '--enable-http-pipelining=true',
            '--file-allocation=none',
            '--no-conf=true',
        ]

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
        """Скачать видео с TikTok"""
        video_id = self.extract_id(request.url) or "unknown"

        async with self.semaphore:
            output_path = str(self.temp_dir / f"tiktok_{video_id}.mp4")

            ydl_opts = self._get_ydl_opts(output_path)

            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self.executor,
                    partial(self._download_sync, request.url, ydl_opts)
                )

                if not result["success"]:
                    return DownloadResult(success=False, error=result.get("error"))

                file_path = result.get("file_path")
                if not file_path or not Path(file_path).exists():
                    return DownloadResult(success=False, error="File not found")

                # Удаляем водяной знак если есть ffmpeg
                if self.has_ffmpeg:
                    try:
                        new_path = await self._remove_watermark(file_path)
                        if new_path and Path(new_path).exists():
                            file_path = new_path
                    except Exception as e:
                        self.log.warning("Watermark removal failed", error=str(e))

                return DownloadResult(
                    success=True,
                    file_path=Path(file_path),
                    title=result.get("title", "TikTok Video"),
                    duration=result.get("duration"),
                )

            except Exception as e:
                self.log.exception("TikTok download failed", error=str(e))
                return DownloadResult(success=False, error=str(e))

    def _get_ydl_opts(self, output_path: str) -> dict:
        """Настройки yt-dlp для TikTok"""
        opts = {
            'format': 'best',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'noprogress': True,
            'http_headers': self.HEADERS,
            'socket_timeout': 30,
            'retries': 10,
            'fragment_retries': 10,
            'http_chunk_size': 500 * 1024 * 1024,
            'concurrent_fragments': 5,
            'noplaylist': True,
            'extract_flat': False,
        }

        # FFmpeg postprocessor
        if self.has_ffmpeg:
            opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
            ffmpeg_path = shutil.which('ffmpeg')
            if ffmpeg_path:
                opts['ffmpeg_location'] = ffmpeg_path

        # aria2c
        if self.has_aria2c:
            opts['external_downloader'] = shutil.which('aria2c')
            opts['external_downloader_args'] = {'default': self.aria2c_args}

        return opts

    def _download_sync(self, url: str, ydl_opts: dict) -> dict:
        """Синхронная загрузка"""
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

                if not info:
                    return {"success": False, "error": "Failed to extract info"}

                file_path = ydl_opts.get("outtmpl")

                # Проверяем существование файла
                if not os.path.exists(file_path):
                    # Пробуем найти файл
                    base_path = Path(file_path).parent
                    mp4_files = list(base_path.glob("tiktok_*.mp4"))
                    if mp4_files:
                        file_path = str(mp4_files[0])

                if not os.path.exists(file_path):
                    return {"success": False, "error": "Downloaded file not found"}

                return {
                    "success": True,
                    "file_path": file_path,
                    "title": info.get("title", "TikTok Video"),
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
                'ffmpeg',
                '-i', file_path,
                '-filter:v', 'crop=in_w:in_h-185',  # Обрезаем водяной знак снизу
                '-c:a', 'copy',
                '-preset', 'ultrafast',
                '-movflags', '+faststart',
                '-y',
                new_path
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
                )
            )

            if process.returncode != 0:
                self.log.warning("FFmpeg failed", stderr=process.stderr[:200])
                return file_path

            if os.path.exists(new_path) and os.path.getsize(new_path) > 0:
                # Удаляем оригинал
                try:
                    os.remove(file_path)
                except:
                    pass
                return new_path

            return file_path

        except Exception as e:
            self.log.warning("Watermark removal error", error=str(e))
            return file_path
