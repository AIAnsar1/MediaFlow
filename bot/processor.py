import re
from dataclasses import dataclass
from typing import Any

from aiogram import Bot
from aiogram.types import Update, Message, CallbackQuery, User as TgUser

from app.logging import get_logger
from database.connection import db
from repositories.uow import UnitOfWork
from repositories.ad import AdRepository
from services import (
    bot_manager,
    cache,
    download_service,
    queue_service,
    MediaPlatform,
    DownloadRequest,
)
from services.user import UserService
from services.subscription import subscription_service
from models import Bot as BotModel

log = get_logger("bot.processor")


@dataclass
class ProcessingContext:
    """Контекст обработки update"""

    bot: Bot
    bot_model: BotModel
    update: Update
    user_id: int
    chat_id: int
    language: str = "en"


class UpdateProcessor:
    """
    Обработчик Telegram updates для multi-bot webhook

    Роутинг:
    - /start -> start_handler
    - Callback set_language:* -> language_handler
    - URL message -> download_handler
    - Callback yt_download:* -> youtube_handler
    """

    # URL паттерны для определения платформы
    URL_PATTERNS = {
        MediaPlatform.YOUTUBE: [
            r"(?:https?://)?(?:www\.)?youtube\.com",
            r"(?:https?://)?youtu\.be",
        ],
        MediaPlatform.INSTAGRAM: [
            r"(?:https?://)?(?:www\.)?instagram\.com",
        ],
        MediaPlatform.TIKTOK: [
            r"(?:https?://)?(?:www\.)?tiktok\.com",
            r"(?:https?://)?(?:vm|vt)\.tiktok\.com",
        ],
        MediaPlatform.PINTEREST: [
            r"(?:https?://)?(?:www\.)?pinterest\.",
            r"(?:https?://)?pin\.it",
        ],
    }

    async def process(self, bot_token: str, update_data: dict) -> bool:
        """
        Обработать incoming update

        Returns:
            True если обработано успешно
        """
        try:
            log.info(
                "📥 UpdateProcessor.process called",
                token=bot_token[:10],
                update_id=update_data.get("update_id"),
                has_message="message" in update_data,
                has_callback="callback_query" in update_data,
            )

            # Получаем бота
            instance = await bot_manager.get_bot_instance(bot_token)
            if not instance:
                log.warning("Bot not found", token=bot_token[:10])
                return False

            log.info(
                "✅ Bot instance acquired",
                username=instance.model.username,
            )

            bot = instance.bot
            bot_model = instance.model

            # Парсим update
            update = Update.model_validate(update_data)

            # Извлекаем данные
            user = self._get_user(update)
            chat_id = self._get_chat_id(update)

            if not user or not chat_id:
                return False

            # Получаем/создаём пользователя в БД (быстро, без лишнего commit)
            async with UnitOfWork() as uow:
                user_service = UserService(uow)
                db_user = await user_service.get_or_create_fast(user, bot_model.id)
                language = db_user.language

            # Создаём контекст
            ctx = ProcessingContext(
                bot=bot,
                bot_model=bot_model,
                update=update,
                user_id=user.id,
                chat_id=chat_id,
                language=language,
            )

            # Роутинг
            if update.message:
                return await self._handle_message(ctx, update.message)
            elif update.callback_query:
                return await self._handle_callback(ctx, update.callback_query)

            return True

        except Exception as e:
            log.exception("Update processing failed", error=str(e))
            return False

    def _get_user(self, update: Update) -> TgUser | None:
        """Получить User из update"""
        if update.message:
            return update.message.from_user
        if update.callback_query:
            return update.callback_query.from_user
        return None

    def _get_chat_id(self, update: Update) -> int | None:
        """Получить chat_id из update"""
        if update.message:
            return update.message.chat.id
        if update.callback_query and update.callback_query.message:
            return update.callback_query.message.chat.id
        return None

    async def _handle_message(self, ctx: ProcessingContext, message: Message) -> bool:
        """Обработка сообщений"""
        text = message.text or ""

        log.info(
            "💬 Handling message",
            user_id=ctx.user_id,
            chat_id=ctx.chat_id,
            text=text[:100] if text else "(empty)",
        )

        # Команда /start
        if text == "/start":
            log.info("🚀 Handling /start command")
            return await self._handle_start(ctx, message)

        # Команда /lang
        if text == "/lang":
            return await self._handle_lang_command(ctx, message)

        # Проверяем URL (теперь ищем в любом месте текста)
        if re.search(r"https?://\S+", text):
            # Извлекаем первый найденный URL
            url_match = re.search(r"https?://\S+", text)
            url = url_match.group(0)
            return await self._handle_url(ctx, message, url)

        # Остальной текст — просим прислать ссылку
        return await self._handle_unknown(ctx, message)

    async def _handle_callback(self, ctx: ProcessingContext, callback: CallbackQuery) -> bool:
        """Обработка callback query"""
        data = callback.data or ""

        # Выбор языка
        if data.startswith("set_language:"):
            return await self._handle_language_callback(ctx, callback)

        # Format selection
        if data.startswith("yt_fmt:") or data.startswith("downloader_format:"):
            return await self._handle_format_callback(ctx, callback)

        # YouTube audio download
        if data.startswith("yt_audio:"):
            return await self._handle_youtube_audio_callback(ctx, callback)

        # Subscription check retry
        if data == "check_subscription":
            return await self._handle_subscription_retry(ctx, callback)

        await ctx.bot.answer_callback_query(callback.id)
        return True

    # === Handlers ===

    async def _handle_start(self, ctx: ProcessingContext, message: Message) -> bool:
        """Обработка /start"""
        from i18n.lang import MESSAGES

        log.info(
            "📤 Sending start message",
            user_id=ctx.user_id,
            language=ctx.language,
        )

        text = MESSAGES["start"].get(ctx.language, MESSAGES["start"]["en"])
        await ctx.bot.send_message(ctx.chat_id, text)

        log.info("✅ Start message sent", user_id=ctx.user_id)
        return True

    async def _handle_lang_command(self, ctx: ProcessingContext, message: Message) -> bool:
        """Обработка /lang — показать выбор языка"""
        from bot.keyboards import get_language_keyboard
        from i18n.lang import MESSAGES

        text = MESSAGES["lang_prompt"].get(ctx.language, MESSAGES["lang_prompt"]["en"])
        kb = get_language_keyboard()
        await ctx.bot.send_message(ctx.chat_id, text, reply_markup=kb, reply_to_message_id=message.message_id)
        return True

    async def _handle_language_callback(self, ctx: ProcessingContext, callback: CallbackQuery) -> bool:
        """Обработка выбора языка"""
        from i18n.lang import MESSAGES

        language = callback.data.split(":")[1]

        # Обновляем контекст
        ctx.language = language

        async with UnitOfWork() as uow:
            user_service = UserService(uow)
            db_user = await user_service.get_by_telegram_id(ctx.user_id, ctx.bot_model.id)
            if db_user:
                await user_service.update_language(
                    user_id=db_user.id,
                    language=language,
                )
            await uow.commit()

        # Отвечаем
        answer_text = MESSAGES["lang_changed"].get(language, MESSAGES["lang_changed"]["en"])
        await ctx.bot.answer_callback_query(callback.id, answer_text)

        text = MESSAGES["start"].get(language, MESSAGES["start"]["en"])
        await ctx.bot.edit_message_text(text, chat_id=callback.message.chat.id, message_id=callback.message.message_id)

        return True

    async def _handle_url(self, ctx: ProcessingContext, message: Message, url: str) -> bool:
        """Обработка URL"""
        from i18n.lang import MESSAGES

        # Быстрая проверка подписки — только если каналы настроены
        sub_check = await self._check_subscription_fast(ctx, message)
        if not sub_check:
            return True

        # Определяем платформу
        platform = download_service.detect_platform(url)

        if platform == MediaPlatform.UNKNOWN:
            text = MESSAGES["unsupported_link"].get(ctx.language, MESSAGES["unsupported_link"]["en"])
            await ctx.bot.send_message(ctx.chat_id, text, reply_to_message_id=message.message_id)
            return True

        # YouTube - особая обработка (выбор качества)
        if platform == MediaPlatform.YOUTUBE:
            if "/shorts/" in url.lower():
                return await self._handle_direct_download(ctx, message, url, platform)
            return await self._handle_youtube_url(ctx, message, url)

        # Остальные платформы - прямое скачивание
        return await self._handle_direct_download(ctx, message, url, platform)

    async def _handle_youtube_url(self, ctx: ProcessingContext, message: Message, url: str) -> bool:
        """Обработка YouTube URL - показываем превью + информацию + форматы"""
        from bot.keyboards import get_youtube_formats_keyboard_v2
        from i18n.lang import MESSAGES
        from services.media.youtube import YouTubeDownloader

        # Show loading message
        progress_msg = await ctx.bot.send_message(
            ctx.chat_id,
            MESSAGES["loading_youtube_info"].get(ctx.language, MESSAGES["loading_youtube_info"]["en"]),
            reply_to_message_id=message.message_id,
        )

        try:
            downloader = YouTubeDownloader()
            info = await downloader.get_video_info(url)

            if not info:
                await ctx.bot.delete_message(ctx.chat_id, progress_msg.message_id)
                await ctx.bot.send_message(
                    ctx.chat_id,
                    MESSAGES["error_processing"].get(ctx.language, MESSAGES["error_processing"].get("ru")),
                    reply_to_message_id=message.message_id,
                )
                return False

            video_id = info.get("id", "")
            title = info.get("title", "")
            thumbnail = info.get("thumbnail", "")
            uploader = info.get("uploader", "")
            views_str = info.get("views_str", "")
            likes_str = info.get("likes_str", "")
            date_str = info.get("date_str", "")
            duration_str = info.get("duration_str", "")
            formats = info.get("formats", [])

            if not formats:
                await ctx.bot.delete_message(ctx.chat_id, progress_msg.message_id)
                await ctx.bot.send_message(
                    ctx.chat_id,
                    MESSAGES["no_formats_found"].get(ctx.language, MESSAGES["no_formats_found"].get("ru")),
                    reply_to_message_id=message.message_id,
                )
                return False

            # Формируем текст с информацией о видео
            caption = f"🎬 <b>{title}</b>\n\n"
            if views_str or likes_str:
                stats = []
                if views_str:
                    stats.append(views_str)
                if likes_str:
                    stats.append(likes_str.replace("👍", "👍"))
                caption += " | ".join(stats) + "\n"
            if date_str:
                caption += f"📅 {date_str}\n"
            if uploader:
                caption += f"👤 {uploader}\n"
            if duration_str:
                caption += f"⏱ {duration_str}"

            # Формируем каноничный URL как в DownloadRequest
            canonical_url = f"https://www.youtube.com/watch?v={video_id}"

            # Проверяем кеш для каждого качества
            cache_status = {}
            for fmt in formats:
                quality = fmt.get("quality", "")
                if quality:
                    cached = await cache.get_cached_media(canonical_url, quality)
                    if cached:
                        cache_status[quality] = True
            # Проверяем кеш для аудио
            audio_cached = await cache.get_cached_media(canonical_url, "audio")
            if audio_cached:
                cache_status["audio"] = True

            # Создаём клавиатуру с форматами
            kb = get_youtube_formats_keyboard_v2(formats, video_id, cache_status)

            # Delete progress message
            await ctx.bot.delete_message(ctx.chat_id, progress_msg.message_id)

            # Отправляем превью + информация + кнопки
            if thumbnail:
                await ctx.bot.send_photo(
                    ctx.chat_id,
                    photo=thumbnail,
                    caption=caption,
                    reply_markup=kb,
                    reply_to_message_id=message.message_id,
                )
            else:
                await ctx.bot.send_message(
                    ctx.chat_id,
                    caption,
                    reply_markup=kb,
                    reply_to_message_id=message.message_id,
                )

            return True

        except Exception as e:
            log.exception("Failed to get YouTube info", error=str(e))
            await ctx.bot.delete_message(ctx.chat_id, progress_msg.message_id)
            await ctx.bot.send_message(
                ctx.chat_id,
                MESSAGES["error_processing"].get(ctx.language, MESSAGES["error_processing"].get("ru")),
                reply_to_message_id=message.message_id,
            )
            return False

    async def _handle_format_callback(self, ctx: ProcessingContext, callback: CallbackQuery) -> bool:
        """Обработка выбора формата"""
        from i18n.lang import MESSAGES

        parts = callback.data.split(":")
        if parts[0] == "yt_fmt":
            # Новый формат: yt_fmt:{format_id}:{quality}:{video_id}
            if len(parts) == 4:
                format_id = parts[1]
                quality = parts[2]
                video_id = parts[3]
            else:
                format_id = parts[1]
                video_id = parts[2]
                quality = None
            url = f"https://www.youtube.com/watch?v={video_id}"
        else:
            # Старый формат
            format_id = parts[1]
            url = parts[2]
            quality = None

        await ctx.bot.answer_callback_query(callback.id)

        # Редактируем сообщение с форматами вместо удаления
        chat_id = callback.message.chat.id
        msg_id = callback.message.message_id
        text = MESSAGES["start_download"].get(ctx.language, "⏬ Downloading...")

        try:
            if getattr(callback.message, "photo", None):
                await ctx.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=msg_id,
                    caption=text,
                )
            else:
                await ctx.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=text,
                )
        except Exception:
            pass

        progress_msg = callback.message

        # Создаём request
        request = DownloadRequest(
            url=url,
            platform=MediaPlatform.YOUTUBE,
            user_id=ctx.user_id,
            bot_id=ctx.bot_model.id,
            chat_id=ctx.chat_id,
            message_id=progress_msg.message_id,
            quality=quality,
            format=format_id,
        )

        # Запускаем скачивание
        return await self._process_download(ctx, progress_msg, request)

    async def _handle_youtube_audio_callback(self, ctx: ProcessingContext, callback: CallbackQuery) -> bool:
        """Обработка callback audio из нового интерфейса"""
        from i18n.lang import MESSAGES

        parts = callback.data.split(":")
        video_id = parts[1]

        url = f"https://www.youtube.com/watch?v={video_id}"

        await ctx.bot.answer_callback_query(callback.id)

        # Редактируем сообщение с форматами вместо удаления
        chat_id = callback.message.chat.id
        msg_id = callback.message.message_id
        text = MESSAGES["downloading_audio_mp3"].get(ctx.language, "⏬ Downloading MP3 audio...")

        try:
            if getattr(callback.message, "photo", None):
                await ctx.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=msg_id,
                    caption=text,
                )
            else:
                await ctx.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=text,
                )
        except Exception:
            pass

        progress_msg = callback.message

        request = DownloadRequest(
            url=url,
            platform=MediaPlatform.YOUTUBE,
            user_id=ctx.user_id,
            bot_id=ctx.bot_model.id,
            chat_id=ctx.chat_id,
            message_id=progress_msg.message_id,
            quality="audio",
            format="audio",
        )

        return await self._process_download(ctx, progress_msg, request)

    # _download_youtube_audio removed — merged into _handle_youtube_audio_callback

    async def _handle_direct_download(
        self,
        ctx: ProcessingContext,
        message: Message,
        url: str,
        platform: MediaPlatform,
    ) -> bool:
        """Прямое скачивание (Instagram, TikTok, Pinterest, VK)"""
        from i18n.lang import MESSAGES

        # Создаём progress сообщение
        platform_msgs = {
            MediaPlatform.INSTAGRAM: "downloading_instagram",
            MediaPlatform.TIKTOK: "downloading_tiktok",
            MediaPlatform.PINTEREST: "downloading_pinterest",
        }

        msg_key = platform_msgs.get(platform, "processing")
        progress_msg = await ctx.bot.send_message(
            ctx.chat_id,
            MESSAGES[msg_key].get(ctx.language, "⏬ Downloading..."),
            reply_to_message_id=message.message_id,
        )

        request = DownloadRequest(
            url=url,
            platform=platform,
            user_id=ctx.user_id,
            bot_id=ctx.bot_model.id,
            chat_id=ctx.chat_id,
            message_id=progress_msg.message_id,
        )

        return await self._process_download(ctx, progress_msg, request)

    async def _process_download(
        self,
        ctx: ProcessingContext,
        progress_msg: Message,
        request: DownloadRequest,
    ) -> bool:
        """Основной процесс скачивания"""
        from i18n.lang import MESSAGES

        async def update_progress(text: str):
            try:
                if getattr(progress_msg, "photo", None):
                    await ctx.bot.edit_message_caption(
                        caption=text,
                        chat_id=progress_msg.chat.id,
                        message_id=progress_msg.message_id,
                    )
                else:
                    await ctx.bot.edit_message_text(
                        text,
                        chat_id=progress_msg.chat.id,
                        message_id=progress_msg.message_id,
                    )
            except Exception:
                pass  # Ignore edit_message errors

        try:
            log.info(
                "⬇️ Starting download",
                user_id=ctx.user_id,
                url=request.url[:80],
                platform=request.platform.value,
            )

            # Скачиваем
            result = await download_service.download(
                request,
                ctx.bot,
                progress_callback=update_progress,
            )

            log.info(
                "✅ Download completed",
                user_id=ctx.user_id,
                success=result.success,
                error=result.error,
            )

            if not result.success:
                await ctx.bot.edit_message_text(
                    MESSAGES["error_processing"].get(ctx.language, f"❌ Error: {result.error}"),
                    chat_id=progress_msg.chat.id,
                    message_id=progress_msg.message_id,
                )
                return False

            # Отправляем пользователю
            original_message_id = None
            if progress_msg.reply_to_message:
                original_message_id = progress_msg.reply_to_message.message_id

            platform_name = "YouTube" if request.platform == MediaPlatform.YOUTUBE else request.platform.name.capitalize()
            video_text = MESSAGES.get("your_media_from", {}).get(ctx.language, "🎥 Ваше Видео из {}").format(platform_name)

            title_part = f"🎬 {result.title}\n\n" if result.title else ""

            # Добавим информацию о качестве и весе
            quality_info = ""
            if result.quality and result.quality.lower() != "none" and result.quality != "audio":
                quality_info = f"📹 {result.quality}"
                if result.filesize_str:
                    quality_info += f" - 💾 {result.filesize_str}"
                quality_info += "\n\n"
            elif result.quality == "audio":
                quality_info = f"🔊 Audio"
                if result.filesize_str:
                    quality_info += f" - 💾 {result.filesize_str}"
                quality_info += "\n\n"

            caption = f"{title_part}{quality_info}{video_text}\n🤖 @{ctx.bot_model.username}"

            success = await download_service.send_to_user(
                ctx.bot,
                ctx.chat_id,
                result,
                message_id=progress_msg.message_id,
                caption=caption,
                reply_to=original_message_id,
            )

            if success:
                # Send post-download ad if available
                await self._send_post_download_ad(ctx)

            return success

        except Exception as e:
            log.exception("Download failed", error=str(e))
            await ctx.bot.edit_message_text(
                MESSAGES["error_processing"].get(ctx.language, f"❌ Error"),
                chat_id=progress_msg.chat.id,
                message_id=progress_msg.message_id,
            )
            return False

    # === Subscription Check ===

    async def _check_subscription_fast(
        self,
        ctx: ProcessingContext,
        message: Message,
    ) -> bool:
        """
        Быстрая проверка подписки — сначала проверяем есть ли каналы.
        Если каналов нет — сразу True без запросов к Telegram API.
        """
        channels = await subscription_service.get_required_channels(ctx.bot_model.id)
        if not channels:
            return True  # Нет каналов — разрешаем

        # Каналы есть — проверяем подписку
        result = await subscription_service.check_user_subscription(
            ctx.user_id,
            ctx.bot,
            channels,
        )

        if result.is_subscribed:
            return True

        # User is not subscribed — show prompt
        text = subscription_service.build_prompt_message(result.channels)
        keyboard = subscription_service.build_subscribe_keyboard(result.channels)
        await ctx.bot.send_message(ctx.chat_id, text, reply_markup=keyboard, reply_to_message_id=message.message_id)
        return False

    # _check_subscription removed — was identical to _check_subscription_fast

    async def _handle_subscription_retry(
        self,
        ctx: ProcessingContext,
        callback: CallbackQuery,
    ) -> bool:
        """User pressed 'I've subscribed' — re-check."""
        channels = await subscription_service.get_required_channels(ctx.bot_model.id)
        if not channels:
            await ctx.bot.answer_callback_query(callback.id, "✅ No subscription required!")
            return True

        result = await subscription_service.check_user_subscription(
            ctx.user_id,
            ctx.bot,
            channels,
        )

        if result.is_subscribed:
            await ctx.bot.edit_message_text(
                "✅ **Thank you for subscribing!**\n\nNow you can use the bot. Send me a link to download media.",
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
            )
            await ctx.bot.answer_callback_query(callback.id, "✅ Subscribed!")
        else:
            text = subscription_service.build_prompt_message(result.channels)
            keyboard = subscription_service.build_subscribe_keyboard(result.channels)
            await ctx.bot.edit_message_reply_markup(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                reply_markup=keyboard,
            )
            await ctx.bot.answer_callback_query(callback.id, "⚠️ You haven't subscribed yet!", show_alert=True)

        return True

    # === Post-Download Ad ===

    async def _send_post_download_ad(self, ctx: ProcessingContext) -> None:
        """Send post-download ad if one is configured for this bot."""
        try:
            async with UnitOfWork() as uow:
                repo = AdRepository(uow.session)
                ad = await repo.get_post_download_ad(ctx.bot_model.id)
                await uow.commit()

            if not ad:
                return

            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

            keyboard = None
            if ad.button_text and ad.button_url:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=ad.button_text, url=ad.button_url)]])

            await ctx.bot.send_message(
                ctx.chat_id,
                text=ad.content,
                reply_markup=keyboard,
            )
        except Exception as e:
            log.warning("Failed to send post-download ad", error=str(e))

    async def _handle_unknown(self, ctx: ProcessingContext, message: Message) -> bool:
        """Обработка неизвестного сообщения"""
        from i18n.lang import MESSAGES

        text = MESSAGES["send_link"].get(ctx.language, MESSAGES["send_link"]["en"])
        try:
            await ctx.bot.send_message(ctx.chat_id, text, reply_to_message_id=message.message_id)
        except Exception:
            await ctx.bot.send_message(ctx.chat_id, text)
        return True


# === Singleton ===
update_processor = UpdateProcessor()
