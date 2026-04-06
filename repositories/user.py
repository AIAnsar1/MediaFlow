from sqlalchemy import select, func
from repositories.base import BaseRepository
from models import TelegramUser


class UserRepository(BaseRepository[TelegramUser]):
    model = TelegramUser

    async def get_by_telegram_id(self, telegram_id: int, bot_id: int) -> TelegramUser | None:
        return await self.get_one(telegram_id=telegram_id, bot_id=bot_id)

    async def get_or_create(
        self,
        telegram_id: int,
        bot_id: int,
        **defaults,
    ) -> tuple[TelegramUser, bool]:
        """Получить или создать пользователя"""
        return await self.upsert(
            lookup={"telegram_id": telegram_id, "bot_id": bot_id},
            defaults=defaults,
        )

    async def get_users_by_bot(
        self,
        bot_id: int,
        language: str | None = None,
        exclude_blocked: bool = True,
        offset: int = 0,
        limit: int = 100,
    ) -> list[TelegramUser]:
        """Получить пользователей бота"""
        filters = {"bot_id": bot_id}
        if language:
            filters["language"] = language
        if exclude_blocked:
            filters["is_blocked"] = False
            filters["is_banned"] = False

        return list(await self.filter(offset=offset, limit=limit, **filters))

    async def get_users_for_broadcast(
        self,
        bot_ids: list[int],
        language: str | None = None,
    ) -> list[TelegramUser]:
        """Получить всех пользователей для рассылки"""
        stmt = select(TelegramUser).where(
            TelegramUser.bot_id.in_(bot_ids),
            TelegramUser.is_blocked == False,
            TelegramUser.is_banned == False,
        )
        if language:
            stmt = stmt.where(TelegramUser.language == language)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_language_stats(self, bot_id: int | None = None) -> dict[str, int]:
        """Статистика по языкам"""
        stmt = select(TelegramUser.language, func.count(TelegramUser.id)).group_by(TelegramUser.language)
        if bot_id:
            stmt = stmt.where(TelegramUser.bot_id == bot_id)

        result = await self.session.execute(stmt)
        return dict(result.all())

    async def count_by_bot(self, bot_id: int) -> int:
        return await self.count(bot_id=bot_id, is_banned=False)

    async def increment_downloads(self, user_id: int) -> None:
        """Увеличить счётчик загрузок"""
        user = await self.get_by_id(user_id)
        if user:
            user.total_downloads += 1
            await self.session.flush()
