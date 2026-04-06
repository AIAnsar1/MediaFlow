import asyncio
from typing import Callable, Any
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import Update

from app.config import settings
from app.logging import get_logger
from database.connection import db
from repositories import BotRepository
from models import Bot as BotModel, BotStatus

log = get_logger("service.bot_manager")


@dataclass
class BotInstance:
    """Инстанс бота с метаданными"""
    model: BotModel
    bot: Bot
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())


class BotManager:
    """
    Менеджер ботов для multi-bot webhook архитектуры

    - Хранит пул Bot instances
    - Автоматически создаёт/кеширует инстансы
    - Управляет webhook'ами
    """

    def __init__(self, max_bots: int = 100, bot_ttl: int = 3600):
        self._bots: dict[str, BotInstance] = {}  # token -> BotInstance
        self._bots_by_id: dict[int, str] = {}  # bot_id -> token
        self._max_bots = max_bots
        self._bot_ttl = bot_ttl
        self._session: AiohttpSession | None = None
        self._lock = asyncio.Lock()

    async def setup(self) -> None:
        """Инициализация менеджера"""
        # Создаём общую сессию для всех ботов
        if settings.telegram_api_server:
            from aiogram.client.telegram import TelegramAPIServer
            self._session = AiohttpSession(
                api=TelegramAPIServer.from_base(settings.telegram_api_server)
            )
            log.info("Using custom Telegram API server", url=settings.telegram_api_server)
        else:
            self._session = AiohttpSession()

        # Загружаем активные боты из БД
        await self._preload_active_bots()

    async def shutdown(self) -> None:
        """Закрытие всех соединений"""
        log.info("Shutting down bot manager...")

        for token, instance in self._bots.items():
            try:
                await instance.bot.session.close()
            except Exception as e:
                log.error("Error closing bot session", error=str(e))

        self._bots.clear()
        self._bots_by_id.clear()

        if self._session:
            await self._session.close()

    async def _preload_active_bots(self) -> None:
        """Предзагрузка активных ботов"""
        async with db.session() as session:
            repo = BotRepository(session)
            bots = await repo.get_active_bots()

            for bot_model in bots:
                await self._create_bot_instance(bot_model)

            log.info("Preloaded bots", count=len(bots))

    async def _create_bot_instance(self, model: BotModel) -> BotInstance:
        """Создать инстанс бота"""
        bot = Bot(
            token=model.token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            session=self._session,
        )

        instance = BotInstance(model=model, bot=bot)
        self._bots[model.token] = instance
        self._bots_by_id[model.bot_id] = model.token

        log.debug("Created bot instance", username=model.username)
        return instance

    async def get_bot(self, token: str) -> Bot | None:
        """Получить Bot по токену"""
        instance = await self.get_bot_instance(token)
        return instance.bot if instance else None

    async def get_bot_instance(self, token: str) -> BotInstance | None:
        """Получить BotInstance по токену"""
        # Проверяем кеш
        if token in self._bots:
            return self._bots[token]

        # Ищем в БД
        async with self._lock:
            # Double-check после получения блокировки
            if token in self._bots:
                return self._bots[token]

            async with db.session() as session:
                repo = BotRepository(session)
                model = await repo.get_by_token(token)

                if not model or model.status != BotStatus.ACTIVE:
                    return None

                # Очищаем старые инстансы если превышен лимит
                await self._cleanup_old_bots()

                return await self._create_bot_instance(model)

    async def get_bot_by_id(self, bot_id: int) -> Bot | None:
        """Получить Bot по bot_id"""
        if bot_id in self._bots_by_id:
            token = self._bots_by_id[bot_id]
            return self._bots[token].bot

        async with db.session() as session:
            repo = BotRepository(session)
            model = await repo.get_by_bot_id(bot_id)

            if model and model.status == BotStatus.ACTIVE:
                instance = await self._create_bot_instance(model)
                return instance.bot

        return None

    async def get_all_active_bots(self) -> list[tuple[BotModel, Bot]]:
        """Получить все активные боты"""
        async with db.session() as session:
            repo = BotRepository(session)
            models = await repo.get_active_bots()

            result = []
            for model in models:
                if model.token in self._bots:
                    result.append((model, self._bots[model.token].bot))
                else:
                    instance = await self._create_bot_instance(model)
                    result.append((model, instance.bot))

            return result

    async def _cleanup_old_bots(self) -> None:
        """Очистка старых инстансов"""
        if len(self._bots) < self._max_bots:
            return

        current_time = asyncio.get_event_loop().time()
        to_remove = []

        for token, instance in self._bots.items():
            if current_time - instance.created_at > self._bot_ttl:
                to_remove.append(token)

        for token in to_remove[:len(self._bots) - self._max_bots // 2]:
            instance = self._bots.pop(token, None)
            if instance:
                self._bots_by_id.pop(instance.model.bot_id, None)
                try:
                    await instance.bot.session.close()
                except:
                    pass

        if to_remove:
            log.debug("Cleaned up old bot instances", count=len(to_remove))

    # === Webhook Management ===

    async def setup_webhook(self, bot_model: BotModel, base_url: str) -> bool:
        """Установить webhook для бота"""
        bot = await self.get_bot(bot_model.token)
        if not bot:
            return False

        webhook_url = f"{base_url}/webhook/{bot_model.token}"

        try:
            await bot.set_webhook(
                url=webhook_url,
                secret_token=bot_model.webhook_secret,
                drop_pending_updates=True,
            )
            log.info("Webhook set", username=bot_model.username, url=webhook_url)
            return True
        except Exception as e:
            log.error("Failed to set webhook", username=bot_model.username, error=str(e))
            return False

    async def setup_all_webhooks(self, base_url: str) -> dict[str, bool]:
        """Установить webhook'и для всех активных ботов"""
        async with db.session() as session:
            repo = BotRepository(session)
            bots = await repo.get_active_bots()

            results = {}
            for bot_model in bots:
                results[bot_model.username] = await self.setup_webhook(bot_model, base_url)

            return results

    async def remove_webhook(self, token: str) -> bool:
        """Удалить webhook"""
        bot = await self.get_bot(token)
        if not bot:
            return False

        try:
            await bot.delete_webhook()
            return True
        except Exception as e:
            log.error("Failed to remove webhook", error=str(e))
            return False


# === Singleton ===
bot_manager = BotManager()
