import asyncio, os, re, shutil, tempfile, yt_dlp

from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass


from src.services.downloader import BaseDownloader, DownloadRequest, DownloadResult, MediaPlatform
from src.logging import get_logger
from src.config import settings

log = get_logger("downloader.youtube")


@dataclass
class VideoFormat:
    """Информация о формате видео"""
    format_id: str
    resolution: str
    filesize: int  # bytes
    filesize_str: str  # "10.5 MB"
    format_note: str = ""


class YouTubeDownloader(BaseDownloader):
    """
    Загрузчик для YouTube

    Поддерживает:
    - Видео с выбором качества
    - Аудио (MP3 320kbps)
    - Shorts
    """

    platform = MediaPlatform.YOUTUBE

    ALLOWED_QUALITIES = ["360p", "480p", "720p", "1080p", "1440p", "2160p"]

    URL_PATTERNS = [
        r"(?:https?://)?(?:www\.)?youtube\.com/watch\?v=[\w-]+",
        r"(?:https?://)?(?:www\.)?youtube\.com/shorts/[\w-]+",
        r"(?:https?://)?youtu\.be/[\w-]+",
        r"(?:https?://)?(?:www\.)?youtube\.com/embed/[\w-]+",
    ]

    def __init__(self):
        super().__init__()
        self.executor = ThreadPoolExecutor(max_workers=8)
        self.semaphore = asyncio.Semaphore(4)

        # Базовые настройки aria2c (если доступен)
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

        # Проверяем наличие aria2c
        self.has_aria2c = shutil.which('aria2c') is not None
        self.has_ffmpeg = shutil.which('ffmpeg') is not None

    def match_url(self, url: str) -> bool:
        return any(re.match(pattern, url) for pattern in self.URL_PATTERNS)

    def extract_id(self, url: str) -> str | None:
        """Извлечь video_id"""
        # Shorts
        if "/shorts/" in url:
            return url.split("/shorts/")[-1].split("?")[0].split("&")[0]

        # youtu.be
        parsed = urlparse(url)
        if parsed.netloc == "youtu.be":
            return parsed.path.lstrip("/")

        # Regular YouTube
        query = parse_qs(parsed.query)
        if "v" in query:
            return query["v"][0]

        # Embed
        if "/embed/" in url:
            return url.split("/embed/")[-1].split("?")[0]

        return None

    def _get_base_opts(self, output_path: str) -> dict:
        """Базовые настройки yt-dlp"""
        opts = {
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'noprogress': True,
            'socket_timeout': 30,
            'retries': 10,
            'fragment_retries': 10,
            'extractor_retries': 3,
            'http_chunk_size': 10 * 1024 * 1024,  # 10MB chunks
            'concurrent_fragments': 8,
            'nocheckcertificate': True,
            'geo_bypass': True,
            'writethumbnail': False,
            'writeinfojson': False,
            'writesubtitles': False,
        }

        # Добавляем aria2c если доступен
        if self.has_aria2c:
            opts['external_downloader'] = 'aria2c'
            opts['external_downloader_args'] = {'default': self.aria2c_args}

        # FFmpeg
        if self.has_ffmpeg:
            ffmpeg_path = shutil.which('ffmpeg')
            if ffmpeg_path:
                opts['ffmpeg_location'] = ffmpeg_path

        return opts

    async def download(self, request: DownloadRequest) -> DownloadResult:
        """
        Скачать видео/аудио с YouTube

        request.format может быть:
        - "audio" - скачать как MP3
        - format_id - скачать конкретный формат видео
        """
        video_id = self.extract_id(request.url)
        if not video_id:
            return DownloadResult(success=False, error="Invalid YouTube URL")

        # Определяем режим
        if request.format == "audio":
            return await self._download_audio(request.url, video_id)
        elif request.format:
            # Конкретный format_id
            return await self._download_video_format(request.url, video_id, request.format)
        else:
            # По умолчанию лучшее качество
            return await self._download_video_best(request.url, video_id)

    async def _download_audio(self, url: str, video_id: str) -> DownloadResult:
        """Скачать как MP3"""
        async with self.semaphore:
            output_path = str(self.temp_dir / f"yt_{video_id}_audio.%(ext)s")

            ydl_opts = self._get_base_opts(output_path)
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '320',
                }],
            })

            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self.executor,
                    partial(self._download_sync, url, ydl_opts)
                )

                if not result["success"]:
                    return DownloadResult(success=False, error=result.get("error"))

                # Ищем MP3 файл
                file_path = result.get("file_path")
                if file_path:
                    # Меняем расширение на mp3
                    mp3_path = Path(file_path).with_suffix('.mp3')
                    if mp3_path.exists():
                        file_path = str(mp3_path)
                    elif not Path(file_path).exists():
                        # Ищем любой mp3 в директории
                        mp3_files = list(self.temp_dir.glob(f"yt_{video_id}*.mp3"))
                        if mp3_files:
                            file_path = str(mp3_files[0])

                if not file_path or not Path(file_path).exists():
                    return DownloadResult(success=False, error="Audio file not found")

                return DownloadResult(
                    success=True,
                    file_path=Path(file_path),
                    title=result.get("title", "YouTube Audio"),
                    duration=result.get("duration"),
                )

            except Exception as e:
                self.log.exception("Audio download failed", error=str(e))
                return DownloadResult(success=False, error=str(e))

    async def _download_video_format(
        self,
        url: str,
        video_id: str,
        format_id: str
    ) -> DownloadResult:
        """Скачать видео в конкретном формате"""
        async with self.semaphore:
            output_path = str(self.temp_dir / f"yt_{video_id}_{format_id}.%(ext)s")

            ydl_opts = self._get_base_opts(output_path)
            ydl_opts.update({
                'format': f'{format_id}+bestaudio/best',
                'merge_output_format': 'mp4',
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }],
            })

            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self.executor,
                    partial(self._download_sync, url, ydl_opts)
                )

                if not result["success"]:
                    return DownloadResult(success=False, error=result.get("error"))

                file_path = result.get("file_path")
                if not file_path or not Path(file_path).exists():
                    # Ищем mp4 файл
                    mp4_files = list(self.temp_dir.glob(f"yt_{video_id}*.mp4"))
                    if mp4_files:
                        file_path = str(mp4_files[0])

                if not file_path or not Path(file_path).exists():
                    return DownloadResult(success=False, error="Video file not found")

                return DownloadResult(
                    success=True,
                    file_path=Path(file_path),
                    title=result.get("title", "YouTube Video"),
                    duration=result.get("duration"),
                )

            except Exception as e:
                self.log.exception("Video download failed", error=str(e))
                return DownloadResult(success=False, error=str(e))

    async def _download_video_best(self, url: str, video_id: str) -> DownloadResult:
        """Скачать лучшее качество"""
        output_path = str(self.temp_dir / f"yt_{video_id}.%(ext)s")

        ydl_opts = self._get_base_opts(output_path)
        ydl_opts.update({
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
        })

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self.executor,
                partial(self._download_sync, url, ydl_opts)
            )

            if not result["success"]:
                return DownloadResult(success=False, error=result.get("error"))

            file_path = result.get("file_path")
            if not file_path or not Path(file_path).exists():
                return DownloadResult(success=False, error="Video file not found")

            return DownloadResult(
                success=True,
                file_path=Path(file_path),
                title=result.get("title", "YouTube Video"),
                duration=result.get("duration"),
            )

        except Exception as e:
            self.log.exception("Video download failed", error=str(e))
            return DownloadResult(success=False, error=str(e))

    def _download_sync(self, url: str, ydl_opts: dict) -> dict:
        """Синхронная загрузка"""
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

                if not info:
                    return {"success": False, "error": "Failed to extract info"}

                # Определяем путь к файлу
                if "requested_downloads" in info and info["requested_downloads"]:
                    file_path = info["requested_downloads"][0].get("filepath")
                else:
                    file_path = ydl.prepare_filename(info)

                return {
                    "success": True,
                    "file_path": file_path,
                    "title": info.get("title"),
                    "duration": info.get("duration"),
                }

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def get_video_info(self, url: str) -> dict | None:
        """
        Получить информацию о видео с доступными форматами

        Returns:
            {
                "id": "xxx",
                "title": "...",
                "duration": 123,
                "thumbnail": "...",
                "formats": [VideoFormat, ...]
            }
        """
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self.executor,
                partial(self._get_info_sync, url)
            )
            return result
        except Exception as e:
            self.log.exception("Failed to get video info", error=str(e))
            return None

    def _get_info_sync(self, url: str) -> dict | None:
        """Синхронное получение информации"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

                if not info:
                    return None

                # Парсим форматы
                formats = self._parse_formats(info.get("formats", []))

                return {
                    "id": info.get("id"),
                    "title": info.get("title"),
                    "duration": info.get("duration"),
                    "thumbnail": info.get("thumbnail"),
                    "formats": formats,
                }

        except Exception as e:
            self.log.error("Failed to extract info", error=str(e))
            return None

    def _parse_formats(self, raw_formats: list) -> list[dict]:
        """
        Парсинг форматов с подсчётом размера (видео + аудио)
        """
        # Находим лучший аудио формат для подсчёта размера
        audio_formats = [
            f for f in raw_formats
            if f.get("acodec") != "none" and f.get("vcodec") == "none"
        ]
        best_audio = max(
            audio_formats,
            key=lambda x: x.get("abr") or 0,
            default=None
        ) if audio_formats else None

        audio_size = 0
        if best_audio:
            audio_size = best_audio.get("filesize") or best_audio.get("filesize_approx") or 0

        # Собираем видео форматы
        seen_qualities = set()
        formats = []

        for fmt in raw_formats:
            # Пропускаем audio-only
            if fmt.get("vcodec") == "none":
                continue

            # Определяем разрешение
            resolution = fmt.get("format_note") or fmt.get("resolution")
            if isinstance(resolution, int):
                resolution = f"{resolution}p"

            height = fmt.get("height")
            if not resolution and height:
                resolution = f"{height}p"

            if not resolution:
                continue

            # Нормализуем (убираем пробелы, lowercase)
            resolution = resolution.strip().lower()

            # Фильтруем по разрешённым качествам
            if resolution not in [q.lower() for q in self.ALLOWED_QUALITIES]:
                continue

            # Пропускаем дубликаты
            if resolution in seen_qualities:
                continue
            seen_qualities.add(resolution)

            # Считаем размер
            video_size = fmt.get("filesize") or fmt.get("filesize_approx") or 0
            total_size = video_size + audio_size

            # Форматируем размер
            if total_size < 1024 * 1024:  # < 1MB
                size_str = f"{round(total_size / 1024, 1)} KB"
            else:
                size_str = f"{round(total_size / (1024 * 1024), 1)} MB"

            formats.append({
                "format_id": fmt.get("format_id"),
                "quality": resolution,
                "resolution": resolution,
                "filesize": total_size,
                "filesize_mb": round(total_size / (1024 * 1024), 2),
                "filesize_str": size_str,
                "format_note": fmt.get("format_note", ""),
                "ext": fmt.get("ext", "mp4"),
            })

        # Сортируем по качеству (от низкого к высокому)
        quality_order = {q.lower(): i for i, q in enumerate(self.ALLOWED_QUALITIES)}
        formats.sort(key=lambda x: quality_order.get(x["quality"], 999))

        return formats

    async def get_available_formats(self, url: str) -> list[dict]:
        """Получить список доступных форматов (для совместимости)"""
        info = await self.get_video_info(url)
        if info:
            return info.get("formats", [])
        return []
