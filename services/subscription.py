"""Service for managing required subscription channels."""

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from app.logging import get_logger
from repositories.subscription import SubscriptionChannelRepository
from repositories.uow import UnitOfWork
from services import cache

log = get_logger("service.subscription")


class SubscriptionCheckResult:
    """Result of subscription check."""
    is_subscribed: bool
    channels: list  # List of channels user hasn't subscribed to

    def __init__(self, is_subscribed: bool, channels: list | None = None):
        self.is_subscribed = is_subscribed
        self.channels = channels or []


class SubscriptionService:
    """
    Manages required subscription channels.

    - Check if user is subscribed to all required channels
    - Get subscription prompt message with buttons
    - Caches results to avoid slow Telegram API calls
    """

    # Кэш проверок подписки: 5 минут
    CACHE_TTL = 300

    async def get_required_channels(self, bot_id: int) -> list:
        """Get all active required channels for a bot."""
        from types import SimpleNamespace

        # Кэшируем каналы на 10 минут
        cache_key = f"channels:{bot_id}"
        cached = await cache.get(cache_key)
        if cached is not None:
            # Restore as objects with attribute access
            return [SimpleNamespace(**ch) for ch in cached]

        async with UnitOfWork() as uow:
            repo = SubscriptionChannelRepository(uow.session)
            channels = await repo.get_active_required(bot_id)
            await uow.commit()

        # Serialize ORM objects to plain dicts for Redis
        channels_data = [
            {
                "id": ch.id,
                "bot_id": ch.bot_id,
                "channel_chat_id": ch.channel_chat_id,
                "channel_username": ch.channel_username,
                "channel_title": ch.channel_title,
                "is_active": ch.is_active,
            }
            for ch in channels
        ]
        await cache.set(cache_key, channels_data, ttl=600)
        return channels

    async def check_user_subscription(
        self,
        user_id: int,
        bot: Bot,
        channels: list | None = None,
    ) -> SubscriptionCheckResult:
        """
        Быстрая проверка: если каналов нет — сразу True.
        Если каналы есть — проверяем с кэшированием.
        """
        if not channels:
            # Нет каналов — сразу пропускаем
            return SubscriptionCheckResult(is_subscribed=True)

        # Если каналы есть — проверяем подписку
        unsubscribed = []

        for channel in channels:
            try:
                if channel.channel_chat_id:
                    member = await bot.get_chat_member(
                        chat_id=channel.channel_chat_id,
                        user_id=user_id,
                    )
                    if member.status in ("left", "kicked"):
                        unsubscribed.append(channel)
                elif channel.channel_username:
                    member = await bot.get_chat_member(
                        chat_id=f"@{channel.channel_username.lstrip('@')}",
                        user_id=user_id,
                    )
                    if member.status in ("left", "kicked"):
                        unsubscribed.append(channel)
            except TelegramForbiddenError:
                # Bot not in channel — fail-open
                pass
            except Exception as e:
                log.warning(
                    "Failed to check channel membership",
                    channel_id=channel.channel_chat_id,
                    error=str(e),
                )
                unsubscribed.append(channel)

        return SubscriptionCheckResult(
            is_subscribed=len(unsubscribed) == 0,
            channels=unsubscribed,
        )

    def build_subscribe_keyboard(self, channels: list) -> object:
        """Build inline keyboard with subscribe buttons."""
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        buttons = []
        for channel in channels:
            if channel.channel_username:
                url = f"https://t.me/{channel.channel_username.lstrip('@')}"
            else:
                url = f"https://t.me/c/{channel.channel_chat_id}" if channel.channel_chat_id else "#"

            label = channel.channel_title or f"Channel #{channel.id}"
            buttons.append([
                InlineKeyboardButton(text=f"📢 Subscribe to {label}", url=url)
            ])

        buttons.append([
            InlineKeyboardButton(text="✅ I've subscribed — Try again", callback_data="check_subscription")
        ])

        return InlineKeyboardMarkup(inline_keyboard=buttons)

    def build_prompt_message(self, channels: list) -> str:
        """Build the subscription prompt message text."""
        if not channels:
            return "✅ You can use the bot!"

        lines = ["🔒 **Access Restricted**\n"]
        lines.append("To use this bot, you must subscribe to the following channels:\n")

        for i, ch in enumerate(channels, 1):
            title = ch.channel_title or (f"@{ch.channel_username}" if ch.channel_username else f"Channel #{ch.id}")
            lines.append(f"{i}. {title}")

        lines.append("\n👇 Click the buttons below to subscribe, then press **I've subscribed**.")

        return "\n".join(lines)


# Singleton
subscription_service = SubscriptionService()
