import re
import asyncio
import io
import aiofiles
import contextlib

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.types import FSInputFile, InputFile

from app.config import settings
from app.logging import get_logger
from services.cache import cache

log = get_logger("service.downloader")


class MediaPlatform(StrEnum):
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
    file_paths: list[Path] | None = None  # For multiple files (carousels, etc.)
    file_id: str | None = None
    file_ids: list[str] | None = None  # For multiple files
    title: str | None = None
    duration: int | None = None
    error: str | None = None
    from_cache: bool = False

    # Дополнительные данные для caption/metadata
    quality: str | None = None
    filesize_str: str | None = None
    file_count: int = 1
    media_info: dict[str, Any] | None = None  # {"photos": 2, "videos": 1}
    platform_icon: str | None = None  # "📸", "🎥", "🎵" etc.


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
                    with contextlib.suppress(OSError):
                        parent.rmdir()

        except Exception as e:
            self.log.error("Cleanup failed", error=str(e))

    def get_platform_icon(self) -> str:
        """Get default icon for platform"""
        icons = {
            MediaPlatform.INSTAGRAM: "📸",
            MediaPlatform.TIKTOK: "🎵",
            MediaPlatform.YOUTUBE: "📺",
            MediaPlatform.PINTEREST: "📌",
            MediaPlatform.VK: "💙",
            MediaPlatform.TWITTER: "🐦",
        }
        return icons.get(self.platform, "📁")


class DownloadService:
    """
    Главный сервис загрузки

    - Определяет платформу
    - Проверяет кеш (Redis + БД)
    - Делегирует загрузчику
    - Загружает в Telegram канал (с ротацией)
    - Кеширует результат
    """

    def __init__(self):
        self.downloaders: list[BaseDownloader] = []
        self._register_downloaders()

    def _register_downloaders(self) -> None:
        """Регистрация загрузчиков"""
        from services.media.youtube import YouTubeDownloader
        from services.media.instagram import InstagramDownloader
        from services.media.tiktok import TikTokDownloader
        from services.media.pinterest import PinterestDownloader
        from services.media.vk import VKDownloader

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
        cached = await cache.get_cached_media(url, quality)

        if cached:
            log.debug("Cache HIT", url=url[:50])
            return DownloadResult(
                success=True,
                file_id=cached.get("file_id"),
                file_ids=cached.get("file_ids"),
                title=cached.get("title"),
                quality=cached.get("quality"),
                filesize_str=cached.get("filesize_str"),
                file_count=cached.get("file_count", 1),
                platform_icon=cached.get("platform_icon"),
                media_info=cached.get("media_info"),
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
        log.info(
            "📥 DownloadService.download called",
            user_id=request.user_id,
            url=request.url[:80],
            platform=request.platform.value,
        )

        # Rate limiting
        allowed, remaining = await cache.get_user_rate_limit(request.user_id)
        log.info(
            "🔒 User rate limit check",
            user_id=request.user_id,
            allowed=allowed,
            remaining_seconds=remaining,
        )
        if not allowed:
            return DownloadResult(
                success=False,
                error=f"Rate limit exceeded. Wait {remaining} seconds.",
            )

        # Глобальный rate limit
        global_allowed, _ = await cache.get_global_rate_limit()
        log.info(
            "🌐 Global rate limit check",
            allowed=global_allowed,
        )
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

            if not result.quality:
                result.quality = request.quality

            if not result.filesize_str and result.file_path and result.file_path.exists():
                size_bytes = result.file_path.stat().st_size
                if size_bytes < 1024 * 1024:
                    result.filesize_str = f"{size_bytes / 1024:.1f}KB"
                else:
                    result.filesize_str = f"{size_bytes / (1024 * 1024):.1f}MB"

            # Set platform icon
            if not result.platform_icon:
                result.platform_icon = downloader.get_platform_icon()

            # Загружаем в Telegram канал и кешируем
            files_to_upload = []
            if result.file_path:
                files_to_upload = [result.file_path]
            elif result.file_paths:
                files_to_upload = result.file_paths

            if files_to_upload and not (result.file_id or result.file_ids):
                if progress_callback:
                    await progress_callback(f"📤 Uploading ({len(files_to_upload)} files)... ⚡")

                from repositories.uow import UnitOfWork
                from services.cache_channel import CacheChannelService

                # Get rotated cache channel
                async with UnitOfWork() as uow:
                    channel_service = CacheChannelService(uow.session)
                    try:
                        storage_channel = await channel_service.get_next_active_channel()
                        storage_chat_id = storage_channel.telegram_id
                        await uow.commit()
                    except Exception as e:
                        log.warning("Failed to get rotated cache channel, using fallback", error=str(e))
                        storage_chat_id = settings.storage_channel_id

                    if not storage_chat_id:
                        log.warning("No storage channel configured — skipping cache upload")
                        return result

                uploaded_ids = []
                last_message_id = None

                # Upload files in parallel for speed (max 3 concurrent)
                upload_semaphore = asyncio.Semaphore(3)

                async def upload_single(path: Path):
                    async with upload_semaphore:
                        return await self._upload_to_storage_with_retry(bot, path, request, result.title, chat_id=storage_chat_id)

                # Create tasks for parallel upload
                upload_tasks = [upload_single(path) for path in files_to_upload]

                log.info(
                    "Starting parallel upload to storage",
                    file_count=len(files_to_upload),
                    files=[str(p) for p in files_to_upload],
                )

                upload_results = await asyncio.gather(*upload_tasks, return_exceptions=True)

                # Process results
                for upload_result in upload_results:
                    if isinstance(upload_result, Exception):
                        log.error("Parallel upload failed", error=str(upload_result))
                        continue
                    file_id, message_id = upload_result
                    if file_id:
                        uploaded_ids.append(file_id)
                        if message_id:
                            last_message_id = message_id

                if uploaded_ids:
                    # Сохраняем в кеш
                    await cache.cache_media(
                        url=request.url,
                        file_id=uploaded_ids[0] if len(uploaded_ids) == 1 else None,
                        file_ids=uploaded_ids if len(uploaded_ids) > 1 else None,
                        message_id=last_message_id,
                        chat_id=storage_chat_id,
                        quality=request.quality,
                        title=result.title,
                        filesize_str=result.filesize_str,
                        platform=request.platform.value,
                        file_count=len(uploaded_ids),
                        platform_icon=result.platform_icon,
                        media_info=result.media_info,
                    )
                    log.info("Files cached successfully", file_count=len(uploaded_ids))

                    if len(uploaded_ids) == 1:
                        result.file_id = uploaded_ids[0]
                        result.file_ids = uploaded_ids
                        result.file_count = len(uploaded_ids)
                        if not result.media_info:
                            result.media_info = {}
                        result.media_info["types"] = [f.suffix.lower() for f in files_to_upload]
                else:
                    # Upload to storage failed - skip caching but keep files for direct send
                    log.warning(
                        "Failed to upload to storage - skipping cache, files will be sent directly to user",
                        file_count=len(files_to_upload),
                    )
                    # Keep file_paths so send_to_user can upload directly
                    result.file_paths = files_to_upload
                    # Don't cleanup - files needed for direct send
                    files_to_upload = []  # Prevent cleanup below

                # Удаляем временные файлы (только если загрузка успешна)
                for path in files_to_upload:
                    await downloader.cleanup(path)

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
        chat_id: int | None = None,
    ) -> tuple[str | None, int | None]:
        """
        Загрузить в канал-хранилище — Ultra Fast mode

        Uses async file operations with timeouts to prevent hanging.
        """
        target_chat_id = chat_id or settings.storage_channel_id
        if not target_chat_id:
            log.warning("No storage channel configured")
            return None, None

        try:
            suffix = file_path.suffix.lower()
            caption = f"Cache: {request.url[:100]}"
            if title:
                caption = f"{title}\n{caption}"

            # Calculate file size to set appropriate timeout
            file_size_mb = file_path.stat().st_size / (1024 * 1024)
            # Dynamic timeout: 5 min for small files, up to 10 min for large
            upload_timeout = max(300, min(600, int(file_size_mb * 10 + 60)))

            # Create FSInputFile with explicit filename
            fs_file = FSInputFile(path=file_path, filename=file_path.name)

            log.debug(
                "Starting upload",
                path=str(file_path),
                size_mb=f"{file_size_mb:.1f}",
                timeout=upload_timeout,
                chat_id=target_chat_id,
            )

            if suffix in (".mp4", ".webm", ".mkv"):
                message = await asyncio.wait_for(
                    bot.send_video(
                        target_chat_id,
                        video=fs_file,
                        caption=caption[:1024],
                        # Speed optimizations
                        supports_streaming=False,
                    ),
                    timeout=upload_timeout,
                )
                file_id = message.video.file_id

            elif suffix in (".mp3", ".m4a", ".ogg", ".wav"):
                message = await asyncio.wait_for(
                    bot.send_audio(
                        target_chat_id,
                        audio=fs_file,
                        caption=caption[:1024],
                    ),
                    timeout=upload_timeout,
                )
                file_id = message.audio.file_id

            elif suffix in (".jpg", ".jpeg", ".png", ".webp"):
                message = await asyncio.wait_for(
                    bot.send_photo(
                        target_chat_id,
                        photo=fs_file,
                        caption=caption[:1024],
                    ),
                    timeout=upload_timeout,
                )
                file_id = message.photo[-1].file_id

            elif suffix == ".gif":
                message = await asyncio.wait_for(
                    bot.send_animation(
                        target_chat_id,
                        animation=fs_file,
                        caption=caption[:1024],
                    ),
                    timeout=upload_timeout,
                )
                file_id = message.animation.file_id

            else:
                message = await asyncio.wait_for(
                    bot.send_document(
                        target_chat_id,
                        document=fs_file,
                        caption=caption[:1024],
                    ),
                    timeout=upload_timeout,
                )
                file_id = message.document.file_id

            log.debug("Uploaded to storage", file_id=file_id[:20], chat_id=target_chat_id)
            return file_id, message.message_id

        except TimeoutError:
            file_size_mb = file_path.stat().st_size / (1024 * 1024) if file_path.exists() else 0
            log.error(
                "Upload timeout - file too large or connection slow",
                path=str(file_path),
                size_mb=f"{file_size_mb:.1f}",
                chat_id=target_chat_id,
            )
            return None, None
        except Exception as e:
            error_str = str(e).lower()
            # Check for common upload errors
            if any(keyword in error_str for keyword in ["timeout", "cancelled", "connection"]):
                log.warning(
                    "Upload failed with network error (will skip caching)",
                    error=str(e),
                    path=str(file_path),
                )
                return None, None

            log.error(
                "Upload failed",
                error=str(e),
                chat_id=target_chat_id,
                path=str(file_path),
            )
            return None, None

    async def _upload_to_storage_with_retry(
        self,
        bot: Bot,
        file_path: Path,
        request: DownloadRequest,
        title: str | None = None,
        chat_id: int | None = None,
        max_retries: int = 2,
    ) -> tuple[str | None, int | None]:
        """
        Upload to storage with retry logic and exponential backoff.

        Prevents complete failure on temporary network issues.
        """
        for attempt in range(max_retries + 1):
            try:
                result = await self._upload_to_storage(bot, file_path, request, title, chat_id)

                # Success
                if result[0]:
                    return result

                # Upload failed but no exception - don't retry
                if attempt == 0:
                    log.debug("Upload returned None, not retrying")
                return result

            except Exception as e:
                log.warning(
                    f"Upload attempt {attempt + 1}/{max_retries + 1} failed",
                    error=str(e),
                    path=str(file_path),
                )

                # Last attempt - give up
                if attempt >= max_retries:
                    log.error(
                        "All upload attempts failed",
                        attempts=attempt + 1,
                        error=str(e),
                        path=str(file_path),
                    )
                    return None, None

                # Exponential backoff: 2s, 4s, 8s
                wait_time = 2 ** (attempt + 1)
                log.debug(f"Waiting {wait_time}s before retry...")
                await asyncio.sleep(wait_time)

        return None, None

    async def send_to_user(
        self,
        bot: Bot,
        chat_id: int,
        result: DownloadResult,
        message_id: int | None = None,
        caption: str | None = None,
        reply_to: int | None = None,
        bot_username: str | None = None,
    ) -> bool:
        """
        Отправить результат пользователю

        Если file_id есть - отправляет из кеша.
        Если file_paths есть но нет file_id - загружает напрямую в чат пользователя.
        """
        try:
            # Формируем caption
            if not caption:
                parts = []
                if result.platform_icon:
                    parts.append(result.platform_icon)
                if result.title:
                    parts.append(result.title[:200])
                if result.quality:
                    parts.append(f"📹 {result.quality}")
                if result.filesize_str:
                    parts.append(f"💾 {result.filesize_str}")
                if result.file_count > 1:
                    parts.append(f"🔢 {result.file_count} files")
                # Marketing line
                if bot_username:
                    parts.append(f"📥 via @{bot_username}")

                caption = "\n".join(parts) if parts else None

            # Отправляем файл(ы)
            file_ids = []
            if result.file_id:
                file_ids = [result.file_id]
            elif result.file_ids:
                file_ids = result.file_ids

            # No cached file_id - send files directly if available
            if not file_ids and result.file_paths:
                log.info(
                    "Sending files directly to user (no cache)",
                    file_count=len(result.file_paths),
                )
                return await self._send_files_direct(
                    bot,
                    chat_id,
                    result.file_paths,
                    result,
                    message_id=message_id,
                    caption=caption,
                    reply_to=reply_to,
                )

            if not file_ids:
                return False

            if len(file_ids) == 1:
                # Single file — determine type from platform icon hint
                file_id = file_ids[0]
                send_kwargs = {"chat_id": chat_id}
                if caption:
                    send_kwargs["caption"] = caption[:1024]
                if reply_to:
                    send_kwargs["reply_to_message_id"] = reply_to

                # Pick the best send method based on platform icon
                icon = result.platform_icon or ""
                if icon in ("🎵", "🎶"):
                    ordered_methods = [
                        ("audio", bot.send_audio),
                        ("document", bot.send_document),
                    ]
                elif icon in ("📸",):
                    ordered_methods = [
                        ("photo", bot.send_photo),
                        ("document", bot.send_document),
                    ]
                else:
                    # Default: video first (most common), then document fallback
                    ordered_methods = [
                        ("video", bot.send_video),
                        ("document", bot.send_document),
                    ]

                for media_type, send_method in ordered_methods:
                    try:
                        await send_method(**{media_type: file_id, **send_kwargs})

                        # Успешно отправлено — теперь удаляем progress если есть
                        if message_id:
                            with contextlib.suppress(Exception):
                                await bot.delete_message(chat_id, message_id)

                        return True
                    except Exception as e:
                        if "message to be replied not found" in str(e) and "reply_to_message_id" in send_kwargs:
                            try:
                                del send_kwargs["reply_to_message_id"]
                                await send_method(**{media_type: file_id, **send_kwargs})

                                if message_id:
                                    with contextlib.suppress(Exception):
                                        await bot.delete_message(chat_id, message_id)

                                return True
                            except Exception:
                                pass
                        continue
            else:
                # Multiple files (Media Group)
                from aiogram.utils.media_group import MediaGroupBuilder

                builder = MediaGroupBuilder(caption=caption[:1024])
                for i, fid in enumerate(file_ids):
                    extension = ""
                    if result.file_paths and i < len(result.file_paths):
                        extension = result.file_paths[i].suffix.lower()
                    elif result.media_info and "types" in result.media_info and i < len(result.media_info["types"]):
                        extension = result.media_info["types"][i]

                    if extension in (".mp4", ".webm", ".mkv", ".mov"):
                        builder.add_video(media=fid)
                    elif extension in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                        builder.add_photo(media=fid)
                    else:
                        builder.add_document(media=fid)

                try:
                    await bot.send_media_group(chat_id=chat_id, media=builder.build(), reply_to_message_id=reply_to)

                    if message_id:
                        with contextlib.suppress(Exception):
                            await bot.delete_message(chat_id, message_id)

                    return True
                except Exception as e:
                    if "message to be replied not found" in str(e):
                        try:
                            await bot.send_media_group(chat_id=chat_id, media=builder.build())

                            if message_id:
                                with contextlib.suppress(Exception):
                                    await bot.delete_message(chat_id, message_id)

                            return True
                        except Exception:
                            pass

                return False

        except Exception as e:
            log.error("Send to user failed", error=str(e))
            return False

    async def _send_files_direct(
        self,
        bot: Bot,
        chat_id: int,
        file_paths: list[Path],
        result: DownloadResult,
        message_id: int | None = None,
        caption: str | None = None,
        reply_to: int | None = None,
    ) -> bool:
        """
        Send files directly to user chat (bypass storage channel).

        Used as fallback when storage upload fails.
        """
        try:
            if len(file_paths) == 1:
                # Single file
                path = file_paths[0]
                fs_file = FSInputFile(path=path, filename=path.name)
                suffix = path.suffix.lower()

                send_kwargs = {"chat_id": chat_id}
                if caption:
                    send_kwargs["caption"] = caption[:1024]
                if reply_to:
                    send_kwargs["reply_to_message_id"] = reply_to

                if suffix in (".mp4", ".webm", ".mkv"):
                    await bot.send_video(chat_id, video=fs_file, **{k: v for k, v in send_kwargs.items() if k != "chat_id"})
                elif suffix in (".jpg", ".jpeg", ".png", ".webp"):
                    await bot.send_photo(chat_id, photo=fs_file, **{k: v for k, v in send_kwargs.items() if k != "chat_id"})
                elif suffix in (".mp3", ".m4a", ".ogg", ".wav"):
                    await bot.send_audio(chat_id, audio=fs_file, **{k: v for k, v in send_kwargs.items() if k != "chat_id"})
                else:
                    await bot.send_document(chat_id, document=fs_file, **{k: v for k, v in send_kwargs.items() if k != "chat_id"})

                log.info("Sent single file directly", path=str(path))
            else:
                # Multiple files - media group
                from aiogram.utils.media_group import MediaGroupBuilder

                builder = MediaGroupBuilder(caption=caption[:1024] if caption else None)
                for i, path in enumerate(file_paths):
                    suffix = path.suffix.lower()
                    fs_file = FSInputFile(path=path, filename=path.name)

                    if suffix in (".mp4", ".webm", ".mkv", ".mov"):
                        builder.add_video(media=fs_file)
                    elif suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                        builder.add_photo(media=fs_file)
                    else:
                        builder.add_document(media=fs_file)

                send_kwargs = {"chat_id": chat_id, "media": builder.build()}
                if reply_to:
                    send_kwargs["reply_to_message_id"] = reply_to

                try:
                    await bot.send_media_group(**send_kwargs)
                except Exception:
                    # Retry without reply_to
                    del send_kwargs["reply_to_message_id"]
                    await bot.send_media_group(**send_kwargs)

                log.info("Sent media group directly", file_count=len(file_paths))

            # Cleanup after successful send
            for path in file_paths:
                await self.get_downloader(result.platform or MediaPlatform.UNKNOWN).__class__.cleanup(self, path)

            if message_id:
                with contextlib.suppress(Exception):
                    await bot.delete_message(chat_id, message_id)

            return True

        except Exception as e:
            log.error("Direct send failed", error=str(e))
            return False


# === Singleton ===
download_service = DownloadService()
