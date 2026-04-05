import re, asyncio

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Any

from aiogram import Bot
from aiogram.types import FSInputFile

from src.config import settings
from src.logging import get_logger
from src.services.cache import cache

log = get_logger("service.downloader")


class MediaPlatform(str, Enum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    PINTEREST = "pinterest"
    VK = "vk"
    TWITTER = "twitter"
    OTHER = "other"
    UNKNOWN = "unknown"


@dataclass
class DownloadRequest:
    """Запрос на загрузку"""
    url: str
    platform: MediaPlatform
    user_id: int
    bot_id: int
    chat_id: int
    message_id: int  # Progress message ID
    quality: str | None = None
    format: str | None = None  # "audio", format_id, etc.


@dataclass
class DownloadResult:
    """Результат загрузки"""
    success: bool
    file_path: Path | None = None
    file_id: str | None = None  # Telegram file_id (from cache)
    title: str | None = None
    duration: int | None = None
    error: str | None = None
    from_cache: bool = False

    # Дополнительные данные для caption
    quality: str | None = None
    filesize_str: str | None = None


class BaseDownloader(ABC):
    """Базовый класс для загрузчиков"""

    platform: MediaPlatform

    def __init__(self):
        self.log = get_logger(f"downloader.{self.platform.value}")
        self.temp_dir = Path(settings.temp_download_path)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    async def download(self, request: DownloadRequest) -> DownloadResult:
        """Загрузить медиа"""
        pass

    @abstractmethod
    def match_url(self, url: str) -> bool:
        """Проверить соответствие URL"""
        pass

    def extract_id(self, url: str) -> str | None:
        """Извлечь ID контента"""
        return None

    async def cleanup(self, file_path: Path) -> None:
        """Удалить временный файл"""
        try:
            if file_path and file_path.exists():
                file_path.unlink()
                self.log.debug("Cleaned up", path=str(file_path))

                # Удаляем родительскую директорию если пустая
                parent = file_path.parent
                if parent != self.temp_dir and parent.exists():
                    try:
                        parent.rmdir()
                    except OSError:
                        pass  # Не пустая - OK

        except Exception as e:
            self.log.error("Cleanup failed", error=str(e))


class DownloadService:
    """
    Главный сервис загрузки

    - Определяет платформу
    - Проверяет кеш (Redis + БД)
    - Делегирует загрузчику
    - Загружает в Telegram канал
    - Кеширует результат
    """

    def __init__(self):
        self.downloaders: list[BaseDownloader] = []
        self._register_downloaders()

    def _register_downloaders(self) -> None:
        """Регистрация загрузчиков"""
        from src.services.media.youtube import YouTubeDownloader
        from src.services.media.instagram import InstagramDownloader
        from src.services.media.tiktok import TikTokDownloader
        from src.services.media.pinterest import PinterestDownloader
        from src.services.media.vk import VKDownloader

        self.downloaders = [
            YouTubeDownloader(),
            InstagramDownloader(),
            TikTokDownloader(),
            PinterestDownloader(),
            VKDownloader(),
        ]

    def detect_platform(self, url: str) -> MediaPlatform:
        """Определить платформу по URL"""
        for downloader in self.downloaders:
            if downloader.match_url(url):
                return downloader.platform
        return MediaPlatform.UNKNOWN

    def get_downloader(self, platform: MediaPlatform) -> BaseDownloader | None:
        """Получить загрузчик"""
        for downloader in self.downloaders:
            if downloader.platform == platform:
                return downloader
        return None

    async def check_cache(
        self,
        url: str,
        quality: str | None = None,
        format_type: str | None = None,
    ) -> DownloadResult | None:
        """Проверить кеш"""
        # Ключ включает качество/формат
        cache_key = f"{url}:{quality or 'default'}:{format_type or 'video'}"

        cached = await cache.get_cached_media(url, quality)

        if cached:
            log.debug("Cache HIT", url=url[:50])
            return DownloadResult(
                success=True,
                file_id=cached["file_id"],
                title=cached.get("title"),
                quality=cached.get("quality"),
                filesize_str=cached.get("filesize_str"),
                from_cache=True,
            )

        return None

    async def download(
        self,
        request: DownloadRequest,
        bot: Bot,
        progress_callback: Callable[[str], Any] | None = None,
    ) -> DownloadResult:
        """
        Скачать медиа
        """
        # Rate limiting
        allowed, remaining = await cache.get_user_rate_limit(request.user_id)
        if not allowed:
            return DownloadResult(
                success=False,
                error=f"Rate limit exceeded. Wait {remaining} seconds.",
            )

        # Глобальный rate limit
        global_allowed, _ = await cache.get_global_rate_limit()
        if not global_allowed:
            return DownloadResult(
                success=False,
                error="Server busy. Try again later.",
            )

        # Проверяем кеш
        if progress_callback:
            await progress_callback("🔍 Checking cache...")

        cached = await self.check_cache(request.url, request.quality, request.format)
        if cached:
            return cached

        # Получаем загрузчик
        downloader = self.get_downloader(request.platform)
        if not downloader:
            return DownloadResult(
                success=False,
                error=f"Unsupported platform: {request.platform}",
            )

        # Загружаем
        if progress_callback:
            await progress_callback("⏬ Downloading...")

        try:
            result = await downloader.download(request)

            if not result.success:
                return result

            # Загружаем в Telegram канал и кешируем
            if result.file_path and not result.file_id:
                if progress_callback:
                    await progress_callback("📤 Uploading...")

                file_id, message_id = await self._upload_to_storage(
                    bot,
                    result.file_path,
                    request,
                    result.title,
                )

                if file_id:
                    # Сохраняем в кеш
                    await cache.cache_media(
                        url=request.url,
                        file_id=file_id,
                        message_id=message_id,
                        chat_id=settings.storage_channel_id,
                        quality=request.quality,
                        title=result.title,
                        platform=request.platform.value,
                    )

                    result.file_id = file_id

                # Удаляем временный файл
                await downloader.cleanup(result.file_path)

            return result

        except Exception as e:
            log.exception("Download failed", error=str(e))
            return DownloadResult(success=False, error=str(e))

    async def _upload_to_storage(
        self,
        bot: Bot,
        file_path: Path,
        request: DownloadRequest,
        title: str | None = None,
    ) -> tuple[str | None, int | None]:
        """Загрузить в канал-хранилище"""
        try:
            suffix = file_path.suffix.lower()
            caption = f"Cache: {request.url[:100]}"
            if title:
                caption = f"{title}\n{caption}"

            if suffix in (".mp4", ".webm", ".mkv"):
                message = await bot.send_video(
                    settings.storage_channel_id,
                    video=FSInputFile(file_path),
                    caption=caption[:1024],
                )
                file_id = message.video.file_id

            elif suffix in (".mp3", ".m4a", ".ogg", ".wav"):
                message = await bot.send_audio(
                    settings.storage_channel_id,
                    audio=FSInputFile(file_path),
                    caption=caption[:1024],
                )
                file_id = message.audio.file_id

            elif suffix in (".jpg", ".jpeg", ".png", ".webp"):
                message = await bot.send_photo(
                    settings.storage_channel_id,
                    photo=FSInputFile(file_path),
                    caption=caption[:1024],
                )
                file_id = message.photo[-1].file_id

            elif suffix == ".gif":
                message = await bot.send_animation(
                    settings.storage_channel_id,
                    animation=FSInputFile(file_path),
                    caption=caption[:1024],
                )
                file_id = message.animation.file_id

            else:
                message = await bot.send_document(
                    settings.storage_channel_id,
                    document=FSInputFile(file_path),
                    caption=caption[:1024],
                )
                file_id = message.document.file_id

            log.debug("Uploaded to storage", file_id=file_id[:20])
            return file_id, message.message_id

        except Exception as e:
            log.error("Upload failed", error=str(e))
            return None, None

    async def send_to_user(
        self,
        bot: Bot,
        chat_id: int,
        result: DownloadResult,
        message_id: int | None = None,
        caption: str | None = None,
        reply_to: int | None = None,
    ) -> bool:
        """
        Отправить результат пользователю

        UX: удаляем progress сообщение, отправляем файл
        """
        try:
            # Удаляем progress сообщение
            if message_id:
                try:
                    await bot.delete_message(chat_id, message_id)
                except:
                    pass

            # Формируем caption
            if not caption:
                parts = []
                if result.title:
                    parts.append(result.title[:200])
                if result.quality:
                    parts.append(f"📹 {result.quality}")
                if result.filesize_str:
                    parts.append(f"💾 {result.filesize_str}")
                caption = " | ".join(parts) if parts else None

            # Отправляем файл
            if result.file_id:
                # Пробуем разные типы
                send_methods = [
                    ("video", bot.send_video),
                    ("audio", bot.send_audio),
                    ("photo", bot.send_photo),
                    ("animation", bot.send_animation),
                    ("document", bot.send_document),
                ]

                for media_type, send_method in send_methods:
                    try:
                        kwargs = {
                            "chat_id": chat_id,
                            media_type: result.file_id,
                        }
                        if caption:
                            kwargs["caption"] = caption[:1024]
                        if reply_to:
                            kwargs["reply_to_message_id"] = reply_to

                        await send_method(**kwargs)
                        return True

                    except Exception:
                        continue

            return False

        except Exception as e:
            log.error("Send to user failed", error=str(e))
            return False


# === Singleton ===
download_service = DownloadService()
