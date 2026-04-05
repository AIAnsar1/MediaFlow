from dataclasses import dataclass
from aiogram.types import User as TelegramUser

from src.logging import get_logger
from src.repositories import UserRepository
from src.repositories.uow import UnitOfWork
from src.models import User

log = get_logger("service.user")


@dataclass
class UserDTO:
    """Data Transfer Object для пользователя"""
    id: int
    telegram_id: int
    bot_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    language: str
    is_blocked: bool
    is_banned: bool
    total_downloads: int

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.last_name]
        return " ".join(p for p in parts if p) or "Unknown"

    @classmethod
    def from_model(cls, model: User) -> "UserDTO":
        return cls(
            id=model.id,
            telegram_id=model.telegram_id,
            bot_id=model.bot_id,
            username=model.username,
            first_name=model.first_name,
            last_name=model.last_name,
            language=model.language,
            is_blocked=model.is_blocked,
            is_banned=model.is_banned,
            total_downloads=model.total_downloads,
        )


class UserService:
    """
    Сервис для работы с пользователями

    Использование:
        async with UnitOfWork() as uow:
            service = UserService(uow)
            user = await service.get_or_create(telegram_user, bot_id)
    """

    def __init__(self, uow: UnitOfWork):
        self.uow = uow
        self.repo = uow.users

    async def get_or_create(
        self,
        telegram_user: TelegramUser,
        bot_id: int,
    ) -> tuple[UserDTO, bool]:
        """
        Получить или создать пользователя

        Returns:
            (UserDTO, created: bool)
        """
        user, created = await self.repo.get_or_create(
            telegram_id=telegram_user.id,
            bot_id=bot_id,
            username=telegram_user.username,
            first_name=telegram_user.first_name,
            last_name=telegram_user.last_name,
            language=telegram_user.language_code or "en",
        )

        if created:
            log.info(
                "New user registered",
                telegram_id=telegram_user.id,
                bot_id=bot_id,
                language=user.language,
            )

        return UserDTO.from_model(user), created

    async def get_by_telegram_id(
        self,
        telegram_id: int,
        bot_id: int,
    ) -> UserDTO | None:
        """Получить пользователя"""
        user = await self.repo.get_by_telegram_id(telegram_id, bot_id)
        return UserDTO.from_model(user) if user else None

    async def update_language(
        self,
        user_id: int,
        language: str,
    ) -> UserDTO | None:
        """Обновить язык"""
        user = await self.repo.update(user_id, language=language)
        if user:
            log.debug("Language updated", user_id=user_id, language=language)
            return UserDTO.from_model(user)
        return None

    async def increment_downloads(self, user_id: int) -> None:
        """Увеличить счётчик загрузок"""
        await self.repo.increment_downloads(user_id)

    async def set_blocked(self, user_id: int, blocked: bool = True) -> None:
        """Отметить как заблокированного (бот заблокирован пользователем)"""
        await self.repo.update(user_id, is_blocked=blocked)

    async def ban_user(self, user_id: int) -> None:
        """Забанить пользователя"""
        await self.repo.update(user_id, is_banned=True)
        log.warning("User banned", user_id=user_id)

    async def get_language(self, telegram_id: int, bot_id: int) -> str:
        """Получить язык пользователя"""
        user = await self.get_by_telegram_id(telegram_id, bot_id)
        return user.language if user else "en"

    async def get_users_for_broadcast(
        self,
        bot_ids: list[int],
        language: str | None = None,
    ) -> list[UserDTO]:
        """Получить пользователей для рассылки"""
        users = await self.repo.get_users_for_broadcast(bot_ids, language)
        return [UserDTO.from_model(u) for u in users]

    async def get_stats(self, bot_id: int | None = None) -> dict:
        """Статистика пользователей"""
        total = await self.repo.count(bot_id=bot_id) if bot_id else await self.repo.count()
        language_stats = await self.repo.get_language_stats(bot_id)

        return {
            "total": total,
            "by_language": language_stats,
        }
