from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from repositories.base import BaseRepository
from models import Ad, AdBot, AdDelivery, AdStatus


class AdRepository(BaseRepository[Ad]):
    model = Ad

    async def get_by_uuid(self, ad_uuid: str) -> Ad | None:
        stmt = (
            select(Ad)
            .where(Ad.ad_uuid == ad_uuid)
            .options(
                selectinload(Ad.target_bots),
                selectinload(Ad.deliveries),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_with_relations(self, ad_id: int) -> Ad | None:
        stmt = (
            select(Ad)
            .where(Ad.id == ad_id)
            .options(
                selectinload(Ad.target_bots).selectinload(AdBot.bot),
                selectinload(Ad.deliveries),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active(self, offset: int = 0, limit: int = 50) -> list[Ad]:
        return list(await self.filter(
            is_active=True,
            offset=offset,
            limit=limit,
            order_by="created_at",
        ))

    async def add_target_bots(self, ad_id: int, bot_ids: list[int]) -> None:
        """Добавить боты для рассылки"""
        for bot_id in bot_ids:
            ad_bot = AdBot(ad_id=ad_id, bot_id=bot_id)
            self.session.add(ad_bot)
        await self.session.flush()

    async def get_target_bot_ids(self, ad_id: int) -> list[int]:
        """Получить ID ботов для рассылки"""
        stmt = select(AdBot.bot_id).where(AdBot.ad_id == ad_id)
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]

    async def update_delivery_stats(self, ad_id: int) -> None:
        """Пересчитать статистику доставки"""
        stmt = select(
            func.count().filter(AdDelivery.is_sent == True),
            func.count().filter(AdDelivery.is_sent == False),
        ).where(AdDelivery.ad_id == ad_id)

        result = await self.session.execute(stmt)
        sent, failed = result.one()

        await self.update(ad_id, sent_count=sent, failed_count=failed)


class AdDeliveryRepository(BaseRepository[AdDelivery]):
    model = AdDelivery

    async def create_delivery(
        self,
        ad_id: int,
        user_id: int,
        bot_id: int,
        telegram_chat_id: int,
        telegram_message_id: int | None = None,
        is_sent: bool = False,
        error_message: str | None = None,
    ) -> AdDelivery:
        return await self.create(
            ad_id=ad_id,
            user_id=user_id,
            bot_id=bot_id,
            telegram_chat_id=telegram_chat_id,
            telegram_message_id=telegram_message_id,
            is_sent=is_sent,
            error_message=error_message,
        )

    async def mark_sent(
        self,
        delivery_id: int,
        telegram_message_id: int,
    ) -> AdDelivery | None:
        return await self.update(
            delivery_id,
            is_sent=True,
            telegram_message_id=telegram_message_id,
        )

    async def mark_failed(
        self,
        delivery_id: int,
        error: str,
    ) -> AdDelivery | None:
        return await self.update(
            delivery_id,
            is_sent=False,
            error_message=error[:256],
        )

    async def get_deliveries_for_deletion(self, ad_id: int) -> list[AdDelivery]:
        """Получить доставки для удаления сообщений"""
        return list(await self.filter(
            ad_id=ad_id,
            is_sent=True,
            telegram_message_id__is_null=False,
        ))
