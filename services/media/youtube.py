import asyncio, os, re, shutil, tempfile, yt_dlp

from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass


from services.downloader import BaseDownloader, DownloadRequest, DownloadResult, MediaPlatform
from app.logging import get_logger

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
        self.executor = ThreadPoolExecutor(max_workers=16)
        self.semaphore = asyncio.Semaphore(8)

        # Базовые настройки aria2c (если доступен)
        self.aria2c_args = [
            '-x', '16', '-s', '16', '-k', '2M',
            '--min-split-size=2M',
            '--max-connection-per-server=16',
            '--max-concurrent-downloads=16',
            '--max-tries=3',
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

        # Проверяем наличие aria2c и ffmpeg
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
        """Базовые настройки yt-dlp — оптимизировано для скорости и совместимости"""
        opts = {
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'noprogress': True,
            'socket_timeout': 15,
            'retries': 3,
            'fragment_retries': 3,
            'extractor_retries': 3,
            'http_chunk_size': 10 * 1024 * 1024,  # 10MB chunks
            'concurrent_fragments': 8,
            'nocheckcertificate': True,
            'geo_bypass': True,
            'writethumbnail': False,
            'writeinfojson': False,
            'writesubtitles': False,
            'writeautomaticsub': False,
        }

        # Подключаем cookies если есть
        cookies_path = self._get_cookies_path()
        if cookies_path:
            opts['cookiefile'] = str(cookies_path)

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

    def _get_cookies_path(self) -> Path | None:
        """Получить путь к файлу cookies для YouTube"""
        project_root = Path(__file__).resolve().parent.parent.parent
        
        possible_paths = [
            project_root / "storage" / "cookies" / "youtube_cookies.txt",
            project_root / "cookies" / "youtube_cookies.txt",
            Path.home() / ".config" / "yt-dlp" / "cookies.txt",
        ]
        
        for path in possible_paths:
            if path.exists():
                return path
        
        return None

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
            output_path = str(self.temp_dir / f"%(title)s [{video_id}].%(ext)s")

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
                    error = result.get("error", "")
                    # Обработка DRM ошибки
                    if "DRM" in error or "drm" in error:
                        return DownloadResult(
                            success=False,
                            error="🔒 This video is DRM protected and cannot be downloaded.",
                        )
                    return DownloadResult(success=False, error=error)

                # Ищем MP3 файл
                file_path = result.get("file_path")
                if not file_path or not Path(file_path).exists():
                    mp3_files = list(self.temp_dir.glob(f"*[{video_id}]*.mp3"))
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
                error_msg = str(e)
                if "DRM" in error_msg or "drm" in error_msg:
                    return DownloadResult(
                        success=False,
                        error="🔒 This video is DRM protected and cannot be downloaded.",
                    )
                self.log.exception("Audio download failed", error=str(e))
                return DownloadResult(success=False, error=str(e))

    async def _download_video_format(
        self,
        url: str,
        video_id: str,
        format_id: str
    ) -> DownloadResult:
        """Скачать видео в конкретном формате — строго выбранный format_id + лучшее аудио"""
        async with self.semaphore:
            output_path = str(self.temp_dir / f"%(title)s_({format_id})_[{video_id}].%(ext)s")

            ydl_opts = self._get_base_opts(output_path)
            # Строго: выбранный формат + лучшее аудио, затем merged в mp4
            ydl_opts.update({
                'format': f'{format_id}+bestaudio[ext=m4a]/{format_id}',
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
                    error = result.get("error", "")
                    # Обработка DRM ошибки
                    if "DRM" in error or "drm" in error:
                        return DownloadResult(
                            success=False,
                            error="🔒 This video is DRM protected and cannot be downloaded.",
                        )
                    return DownloadResult(success=False, error=error)

                file_path = result.get("file_path")
                if not file_path or not Path(file_path).exists():
                    # Ищем файлы с нашим именем
                    merged_files = list(self.temp_dir.glob(f"*[{video_id}]*.mp4"))
                    if merged_files:
                        # Берём самый большой файл (это будет merged)
                        merged_files.sort(key=lambda p: p.stat().st_size, reverse=True)
                        file_path = str(merged_files[0])

                if not file_path or not Path(file_path).exists():
                    return DownloadResult(success=False, error="Video file not found")

                return DownloadResult(
                    success=True,
                    file_path=Path(file_path),
                    title=result.get("title", "YouTube Video"),
                    duration=result.get("duration"),
                )

            except Exception as e:
                error_msg = str(e)
                # Обработка DRM ошибки
                if "DRM" in error_msg or "drm" in error_msg:
                    return DownloadResult(
                        success=False,
                        error="🔒 This video is DRM protected and cannot be downloaded.",
                    )
                self.log.exception("Video download failed", error=str(e))
                return DownloadResult(success=False, error=str(e))

    async def _download_video_best(self, url: str, video_id: str) -> DownloadResult:
        """Скачать лучшее качество"""
        output_path = str(self.temp_dir / f"%(title)s [{video_id}].%(ext)s")

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
                merged_files = list(self.temp_dir.glob(f"*[{video_id}]*.mp4"))
                if merged_files:
                    merged_files.sort(key=lambda p: p.stat().st_size, reverse=True)
                    file_path = str(merged_files[0])

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
                # При merge yt-dlp сохраняет merged файл последним в requested_downloads
                # Ищем mp4 файл который больше по размеру (merged видео+аудио)
                file_path = None
                requested = info.get("requested_downloads", [])
                if requested:
                    # Берём последний файл (это merged после ffmpeg)
                    file_path = requested[-1].get("filepath")

                # Fallback: prepare_filename
                if not file_path:
                    file_path = ydl.prepare_filename(info)
                    # Для merged файлов yt-dlp может добавить f<id>+f<id> к имени
                    # Заменяем расширение на mp4 если это видео
                    if file_path and not file_path.endswith(".mp4"):
                        file_path = file_path.rsplit(".", 1)[0] + ".mp4"

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
        """Синхронное получение информации с метаданными"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'noprogress': True,
            'socket_timeout': 15,
            'retries': 3,
            'extractor_retries': 3,
            'nocheckcertificate': True,
            'geo_bypass': True,
        }

        # Подключаем cookies если есть
        cookies_path = self._get_cookies_path()
        if cookies_path:
            ydl_opts['cookiefile'] = str(cookies_path)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

                if not info:
                    return None

                # Парсим форматы
                formats = self._parse_formats(info.get("formats", []))

                # Форматируем длительность
                duration = info.get("duration", 0)
                duration_str = self._format_duration(duration)

                # Форматируем дату
                upload_date = info.get("upload_date", "")
                date_str = self._format_date(upload_date)

                # Просмотры
                view_count = info.get("view_count", 0)
                views_str = self._format_views(view_count)

                # Лайки
                like_count = info.get("like_count")
                likes_str = f"👍 {self._format_number(like_count)}" if like_count else ""

                return {
                    "id": info.get("id"),
                    "title": info.get("title"),
                    "duration": duration,
                    "duration_str": duration_str,
                    "thumbnail": info.get("thumbnail"),
                    "uploader": info.get("uploader") or info.get("channel") or "",
                    "view_count": view_count,
                    "views_str": views_str,
                    "like_count": like_count,
                    "likes_str": likes_str,
                    "upload_date": upload_date,
                    "date_str": date_str,
                    "formats": formats,
                }

        except Exception as e:
            self.log.error("Failed to extract info", error=str(e))
            return None

    def _format_duration(self, seconds: int) -> str:
        """Форматировать длительность в ММ:SS"""
        if not seconds:
            return "00:00"
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _format_date(self, upload_date: str) -> str:
        """Форматировать дату YYYYMMDD -> DD.MM.YYYY"""
        if not upload_date or len(upload_date) != 8:
            return ""
        return f"{upload_date[6:8]}.{upload_date[4:6]}.{upload_date[:4]}"

    def _format_views(self, count: int) -> str:
        """Форматировать количество просмотров"""
        if not count:
            return "👁 0"
        if count >= 1_000_000:
            return f"👁 {count / 1_000_000:.1f}M"
        if count >= 1_000:
            return f"👁 {count / 1_000:.1f}K"
        return f"👁 {count}"

    def _format_number(self, count: int) -> str:
        """Форматировать число"""
        if not count:
            return "0"
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        if count >= 1_000:
            return f"{count / 1_000:.1f}K"
        return str(count)

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

        # Форматируем размер аудио
        if audio_size < 1024 * 1024:
            audio_size_str = f"{round(audio_size / 1024, 1)}KB"
        else:
            audio_size_str = f"{round(audio_size / (1024 * 1024), 1)}MB"

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
                size_str = f"{round(total_size / 1024, 1)}KB"
            else:
                size_str = f"{round(total_size / (1024 * 1024), 1)}MB"

            formats.append({
                "format_id": fmt.get("format_id"),
                "quality": resolution,
                "resolution": resolution,
                "filesize": total_size,
                "filesize_mb": round(total_size / (1024 * 1024), 2),
                "filesize_str": size_str,
                "format_note": fmt.get("format_note", ""),
                "ext": fmt.get("ext", "mp4"),
                "audio_size_str": audio_size_str,  # Добавляем размер аудио
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
