import re
from dataclasses import dataclass
from typing import Any

from aiogram import Bot
from aiogram.types import Update, Message, CallbackQuery, User as TgUser

from app.logging import get_logger
from database.connection import db
from repositories.uow import UnitOfWork
from services import (
    bot_manager,
    cache,
    download_service,
    queue_service,
    MediaPlatform,
    DownloadRequest,
)
from services.user import UserService
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
            # Получаем бота
            instance = await bot_manager.get_bot_instance(bot_token)
            if not instance:
                log.warning("Bot not found", token=bot_token[:10])
                return False

            bot = instance.bot
            bot_model = instance.model

            # Парсим update
            update = Update.model_validate(update_data)

            # Извлекаем данные
            user = self._get_user(update)
            chat_id = self._get_chat_id(update)

            if not user or not chat_id:
                return False

            # Получаем/создаём пользователя в БД
            async with UnitOfWork() as uow:
                user_service = UserService(uow)
                db_user, created = await user_service.get_or_create(user, bot_model.id)
                await uow.commit()

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

        # Команда /start
        if text.startswith("/start"):
            return await self._handle_start(ctx, message)

        # Проверяем URL
        if re.match(r"https?://", text):
            return await self._handle_url(ctx, message, text)

        # Неизвестное сообщение - отправляем подсказку
        return await self._handle_unknown(ctx, message)

    async def _handle_callback(self, ctx: ProcessingContext, callback: CallbackQuery) -> bool:
        """Обработка callback query"""
        data = callback.data or ""

        # Выбор языка
        if data.startswith("set_language:"):
            return await self._handle_language_callback(ctx, callback)

        # YouTube download
        if data.startswith("yt_download:"):
            return await self._handle_youtube_callback(ctx, callback)

        # Format selection
        if data.startswith("downloader_format:"):
            return await self._handle_format_callback(ctx, callback)

        await callback.answer()
        return True

    # === Handlers ===

    async def _handle_start(self, ctx: ProcessingContext, message: Message) -> bool:
        """Обработка /start"""
        from bot.keyboards import get_language_keyboard
        from bot.messages import MESSAGES

        async with UnitOfWork() as uow:
            user_service = UserService(uow)
            db_user = await user_service.get_by_telegram_id(ctx.user_id, ctx.bot_model.id)

            if db_user and db_user.language:
                # Язык уже выбран
                text = MESSAGES["start_send_link"].get(db_user.language, MESSAGES["start_send_link"]["en"])
                await message.answer(text)
            else:
                # Предлагаем выбрать язык
                text = "🌍 Выберите язык / Choose your language:"
                kb = get_language_keyboard()
                await message.answer(text, reply_markup=kb)

        return True

    async def _handle_language_callback(self, ctx: ProcessingContext, callback: CallbackQuery) -> bool:
        """Обработка выбора языка"""
        from bot.messages import MESSAGES

        language = callback.data.split(":")[1]

        async with UnitOfWork() as uow:
            user_service = UserService(uow)
            await user_service.update_language(
                # Нужно получить db user id
                user_id=ctx.user_id,  # TODO: fix - нужен db user id
                language=language,
            )
            await uow.commit()

        # Обновляем контекст
        ctx.language = language

        # Отвечаем
        if language == "ru":
            await callback.answer("✅ Вы выбрали русский язык!")
        else:
            await callback.answer("✅ You selected English!")

        text = MESSAGES["start_send_link"].get(language, MESSAGES["start_send_link"]["en"])
        await callback.message.edit_text(text)

        return True

    async def _handle_url(self, ctx: ProcessingContext, message: Message, url: str) -> bool:
        """Обработка URL"""
        from i18n import translator

        # Определяем платформу
        platform = download_service.detect_platform(url)

        if platform == MediaPlatform.UNKNOWN:
            text = MESSAGES["unsupported_link"].get(ctx.language, MESSAGES["unsupported_link"]["en"])
            await message.reply(text)
            return True

        # YouTube - особая обработка (выбор качества)
        if platform == MediaPlatform.YOUTUBE:
            return await self._handle_youtube_url(ctx, message, url)

        # Остальные платформы - прямое скачивание
        return await self._handle_direct_download(ctx, message, url, platform)

    async def _handle_youtube_url(self, ctx: ProcessingContext, message: Message, url: str) -> bool:
        """Обработка YouTube URL - показываем выбор video/audio"""
        from bot.keyboards import get_youtube_choice_keyboard
        from bot.messages import MESSAGES
        from services.media.youtube import YouTubeDownloader

        # Извлекаем video_id
        downloader = YouTubeDownloader()
        video_id = downloader.extract_id(url)

        if not video_id:
            await message.reply(MESSAGES["error_processing"].get(ctx.language))
            return False

        # Показываем выбор
        text = MESSAGES["choose_download_type"].get(ctx.language, MESSAGES["choose_download_type"]["en"])
        kb = get_youtube_choice_keyboard(video_id, ctx.language)

        await message.reply(text, reply_markup=kb)
        return True

    async def _handle_youtube_callback(self, ctx: ProcessingContext, callback: CallbackQuery) -> bool:
        """Обработка YouTube callback (video/audio)"""
        from i18n import translator

        parts = callback.data.split(":")
        action = parts[1]  # video or audio
        video_id = parts[2]

        url = f"https://www.youtube.com/watch?v={video_id}"

        if action == "audio":
            return await self._download_youtube_audio(ctx, callback, url)
        else:
            return await self._show_youtube_formats(ctx, callback, url)

    async def _show_youtube_formats(self, ctx: ProcessingContext, callback: CallbackQuery, url: str) -> bool:
        """Показать доступные форматы YouTube"""
        from bot.keyboards import get_youtube_formats_keyboard
        from i18n import translator
        from services.media.youtube import YouTubeDownloader

        # Обновляем сообщение - "Getting formats..."
        progress_msg = await callback.message.edit_text(
            MESSAGES["processing"].get(ctx.language, "⏳ Processing..."),
            reply_markup=None,
        )

        try:
            downloader = YouTubeDownloader()
            info = await downloader.get_video_info(url)

            if not info or not info.get("formats"):
                await progress_msg.edit_text(
                    MESSAGES["no_formats_found"].get(ctx.language, "No formats found")
                )
                return False

            # Создаём клавиатуру с форматами
            kb = get_youtube_formats_keyboard(info["formats"], url)
            text = MESSAGES["check_size_video"].get(ctx.language, "Choose quality:")

            await progress_msg.edit_text(text, reply_markup=kb)
            return True

        except Exception as e:
            log.exception("Failed to get YouTube formats", error=str(e))
            await progress_msg.edit_text(
                MESSAGES["error_processing"].get(ctx.language)
            )
            return False

    async def _handle_format_callback(self, ctx: ProcessingContext, callback: CallbackQuery) -> bool:
        """Обработка выбора формата"""
        from i18n import translator

        parts = callback.data.split(":")
        format_id = parts[1]
        url = parts[2]

        # Обновляем сообщение
        progress_msg = await callback.message.edit_text(
            MESSAGES["start_download"].get(ctx.language, "⏬ Downloading..."),
            reply_markup=None,
        )

        # Создаём request
        request = DownloadRequest(
            url=url,
            platform=MediaPlatform.YOUTUBE,
            user_id=ctx.user_id,
            bot_id=ctx.bot_model.id,
            chat_id=ctx.chat_id,
            message_id=progress_msg.message_id,
            quality=None,
            format=format_id,
        )

        # Запускаем скачивание
        return await self._process_download(ctx, progress_msg, request)

    async def _download_youtube_audio(self, ctx: ProcessingContext, callback: CallbackQuery, url: str) -> bool:
        """Скачать аудио с YouTube"""
        from i18n import translator

        progress_msg = await callback.message.edit_text(
            MESSAGES["start_download"].get(ctx.language, "⏬ Downloading..."),
            reply_markup=None,
        )

        request = DownloadRequest(
            url=url,
            platform=MediaPlatform.YOUTUBE,
            user_id=ctx.user_id,
            bot_id=ctx.bot_model.id,
            chat_id=ctx.chat_id,
            message_id=progress_msg.message_id,
            format="audio",
        )

        return await self._process_download(ctx, progress_msg, request)

    async def _handle_direct_download(
        self,
        ctx: ProcessingContext,
        message: Message,
        url: str,
        platform: MediaPlatform,
    ) -> bool:
        """Прямое скачивание (Instagram, TikTok, Pinterest, VK)"""
        from i18n import translator

        # Создаём progress сообщение
        platform_msgs = {
            MediaPlatform.INSTAGRAM: "downloading_instagram",
            MediaPlatform.TIKTOK: "downloading_tiktok",
            MediaPlatform.PINTEREST: "downloading_pinterest",
        }

        msg_key = platform_msgs.get(platform, "processing")
        progress_msg = await message.reply(
            MESSAGES[msg_key].get(ctx.language, "⏬ Downloading...")
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
        from i18n import translator

        async def update_progress(text: str):
            try:
                await progress_msg.edit_text(text)
            except:
                pass

        try:
            # Скачиваем
            result = await download_service.download(
                request,
                ctx.bot,
                progress_callback=update_progress,
            )

            if not result.success:
                await progress_msg.edit_text(
                    MESSAGES["error_processing"].get(ctx.language, f"❌ Error: {result.error}")
                )
                return False

            # Отправляем пользователю
            # UX: удаляем progress сообщение и отправляем файл как reply на оригинальное
            original_message_id = None
            if progress_msg.reply_to_message:
                original_message_id = progress_msg.reply_to_message.message_id

            success = await download_service.send_to_user(
                ctx.bot,
                ctx.chat_id,
                result,
                message_id=progress_msg.message_id,  # Удалит это сообщение
                caption=result.title,
            )

            if success:
                # Обновляем статистику
                async with UnitOfWork() as uow:
                    user_service = UserService(uow)
                    # TODO: increment user downloads
                    await uow.commit()

            return success

        except Exception as e:
            log.exception("Download failed", error=str(e))
            await progress_msg.edit_text(
                MESSAGES["error_processing"].get(ctx.language, f"❌ Error")
            )
            return False

    async def _handle_unknown(self, ctx: ProcessingContext, message: Message) -> bool:
        """Обработка неизвестного сообщения"""
        from i18n import translator

        text = MESSAGES["send_link"].get(ctx.language, MESSAGES["send_link"]["en"])
        await message.reply(text)
        return True


# === Singleton ===
update_processor = UpdateProcessor()
