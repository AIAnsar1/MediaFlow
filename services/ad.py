import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from src.logging import get_logger
from src.repositories import AdRepository, AdDeliveryRepository, UserRepository
from src.repositories.uow import UnitOfWork
from src.models import Ad, AdStatus, AdMediaType, User
from src.services.bot_manager import bot_manager

log = get_logger("service.ad")


@dataclass
class AdCreateDTO:
    """DTO для создания рекламы"""
    name: str
    content: str
    media_type: AdMediaType = AdMediaType.NONE
    media_file_id: str | None = None
    button_text: str | None = None
    button_url: str | None = None
    target_language: str | None = None
    bot_ids: list[int] = None


@dataclass
class BroadcastResult:
    """Результат рассылки"""
    ad_id: int
    total_users: int
    sent: int
    failed: int
    blocked: int  # Users who blocked the bot
    duration_seconds: float


class AdService:
    """
    Сервис для управления рекламой

    Использование:
        async with UnitOfWork() as uow:
            service = AdService(uow)
            ad = await service.create(dto)
            result = await service.send(ad.id)
    """

    def __init__(self, uow: UnitOfWork):
        self.uow = uow
        self.ad_repo = uow.ads
        self.delivery_repo = uow.ad_deliveries
        self.user_repo = uow.users

    async def create(self, dto: AdCreateDTO) -> Ad:
        """Создать рекламу"""
        ad = await self.ad_repo.create(
            name=dto.name,
            content=dto.content,
            media_type=dto.media_type,
            media_file_id=dto.media_file_id,
            button_text=dto.button_text,
            button_url=dto.button_url,
            target_language=dto.target_language,
            status=AdStatus.DRAFT,
        )

        if dto.bot_ids:
            await self.ad_repo.add_target_bots(ad.id, dto.bot_ids)

        log.info("Ad created", ad_id=ad.id, name=dto.name)
        return ad

    async def get(self, ad_id: int) -> Ad | None:
        """Получить рекламу с relations"""
        return await self.ad_repo.get_with_relations(ad_id)

    async def get_by_uuid(self, uuid: str) -> Ad | None:
        """Получить по UUID"""
        return await self.ad_repo.get_by_uuid(uuid)

    async def list_active(
        self,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Ad]:
        """Список активных реклам"""
        return await self.ad_repo.get_active(offset, limit)

    async def update_status(self, ad_id: int, status: AdStatus) -> Ad | None:
        """Обновить статус"""
        return await self.ad_repo.update(ad_id, status=status)

    async def send(
        self,
        ad_id: int,
        batch_size: int = 30,
        delay_between_batches: float = 1.0,
    ) -> BroadcastResult:
        """
        Отправить рекламу всем пользователям

        Args:
            ad_id: ID рекламы
            batch_size: Размер batch для отправки
            delay_between_batches: Задержка между batch'ами (секунды)
        """
        start_time = datetime.now()

        ad = await self.ad_repo.get_with_relations(ad_id)
        if not ad:
            raise ValueError(f"Ad {ad_id} not found")

        # Обновляем статус
        await self.ad_repo.update(ad_id, status=AdStatus.SENDING, started_at=datetime.now())
        await self.uow.commit()

        # Получаем целевых ботов
        bot_ids = await self.ad_repo.get_target_bot_ids(ad_id)
        if not bot_ids:
            raise ValueError("No target bots selected")

        # Получаем пользователей
        users = await self.user_repo.get_users_for_broadcast(
            bot_ids,
            ad.target_language,
        )

        total_users = len(users)
        sent = 0
        failed = 0
        blocked = 0

        log.info(
            "Starting broadcast",
            ad_id=ad_id,
            total_users=total_users,
            target_bots=bot_ids,
        )

        # Группируем по ботам
        users_by_bot: dict[int, list[User]] = {}
        for user in users:
            users_by_bot.setdefault(user.bot_id, []).append(user)

        # Отправляем
        for bot_id, bot_users in users_by_bot.items():
            bot = await bot_manager.get_bot_by_id(bot_id)
            if not bot:
                log.warning("Bot not found", bot_id=bot_id)
                continue

            for i in range(0, len(bot_users), batch_size):
                batch = bot_users[i:i + batch_size]

                results = await asyncio.gather(*[
                    self._send_to_user(ad, user, bot)
                    for user in batch
                ], return_exceptions=True)

                for user, result in zip(batch, results):
                    if isinstance(result, Exception):
                        failed += 1
                        if isinstance(result, TelegramForbiddenError):
                            blocked += 1
                            # Помечаем как заблокированного
                            await self.user_repo.update(user.id, is_blocked=True)
                    elif result:
                        sent += 1
                    else:
                        failed += 1

                # Задержка между batch'ами
                if i + batch_size < len(bot_users):
                    await asyncio.sleep(delay_between_batches)

        # Обновляем статистику
        duration = (datetime.now() - start_time).total_seconds()

        await self.ad_repo.update(
            ad_id,
            status=AdStatus.COMPLETED,
            completed_at=datetime.now(),
            total_recipients=total_users,
            sent_count=sent,
            failed_count=failed,
        )
        await self.uow.commit()

        result = BroadcastResult(
            ad_id=ad_id,
            total_users=total_users,
            sent=sent,
            failed=failed,
            blocked=blocked,
            duration_seconds=duration,
        )

        log.info(
            "Broadcast completed",
            ad_id=ad_id,
            sent=sent,
            failed=failed,
            blocked=blocked,
            duration=f"{duration:.2f}s",
        )

        return result

    async def _send_to_user(self, ad: Ad, user: User, bot: Bot) -> bool:
        """Отправить рекламу пользователю"""
        try:
            keyboard = None
            if ad.button_text and ad.button_url:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=ad.button_text, url=ad.button_url)
                ]])

            message = None

            if ad.media_type == AdMediaType.PHOTO:
                message = await bot.send_photo(
                    user.telegram_id,
                    photo=ad.media_file_id,
                    caption=ad.content,
                    reply_markup=keyboard,
                )
            elif ad.media_type == AdMediaType.VIDEO:
                message = await bot.send_video(
                    user.telegram_id,
                    video=ad.media_file_id,
                    caption=ad.content,
                    reply_markup=keyboard,
                )
            elif ad.media_type == AdMediaType.ANIMATION:
                message = await bot.send_animation(
                    user.telegram_id,
                    animation=ad.media_file_id,
                    caption=ad.content,
                    reply_markup=keyboard,
                )
            else:
                message = await bot.send_message(
                    user.telegram_id,
                    text=ad.content,
                    reply_markup=keyboard,
                )

            # Сохраняем delivery
            await self.delivery_repo.create_delivery(
                ad_id=ad.id,
                user_id=user.id,
                bot_id=user.bot_id,
                telegram_chat_id=user.telegram_id,
                telegram_message_id=message.message_id,
                is_sent=True,
            )

            return True

        except TelegramForbiddenError:
            # Бот заблокирован
            await self.delivery_repo.create_delivery(
                ad_id=ad.id,
                user_id=user.id,
                bot_id=user.bot_id,
                telegram_chat_id=user.telegram_id,
                is_sent=False,
                error_message="Bot blocked by user",
            )
            raise

        except Exception as e:
            log.error(
                "Failed to send ad",
                user_id=user.telegram_id,
                error=str(e),
            )
            await self.delivery_repo.create_delivery(
                ad_id=ad.id,
                user_id=user.id,
                bot_id=user.bot_id,
                telegram_chat_id=user.telegram_id,
                is_sent=False,
                error_message=str(e)[:256],
            )
            return False

    async def delete_with_messages(self, ad_uuid: str) -> int:
        """Удалить рекламу и все отправленные сообщения"""
        ad = await self.ad_repo.get_by_uuid(ad_uuid)
        if not ad:
            return 0

        # Получаем доставки для удаления
        deliveries = await self.delivery_repo.filter(
            ad_id=ad.id,
            is_sent=True,
            telegram_message_id__is_null=False,
        )

        deleted_count = 0

        # Группируем по ботам
        deliveries_by_bot: dict[int, list] = {}
        for delivery in deliveries:
            deliveries_by_bot.setdefault(delivery.bot_id, []).append(delivery)

        for bot_id, bot_deliveries in deliveries_by_bot.items():
            bot = await bot_manager.get_bot_by_id(bot_id)
            if not bot:
                continue

            for delivery in bot_deliveries:
                try:
                    await bot.delete_message(
                        delivery.telegram_chat_id,
                        delivery.telegram_message_id,
                    )
                    deleted_count += 1
                except Exception as e:
                    log.warning(
                        "Failed to delete message",
                        chat_id=delivery.telegram_chat_id,
                        error=str(e),
                    )

        # Удаляем из БД
        await self.ad_repo.delete(ad.id)
        await self.uow.commit()

        log.info("Ad deleted with messages", ad_uuid=ad_uuid, deleted=deleted_count)

        return deleted_count
