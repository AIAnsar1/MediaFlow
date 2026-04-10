"""Tests for SubscriptionService and SubscriptionChannelRepository"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.exceptions import TelegramForbiddenError

from models.subscription import SubscriptionChannel, SubscriptionStatus
from repositories.subscription import SubscriptionChannelRepository
from services.subscription import SubscriptionService, SubscriptionCheckResult


class TestSubscriptionCheckResult:
    """Test SubscriptionCheckResult"""

    def test_subscribed(self):
        result = SubscriptionCheckResult(is_subscribed=True)
        assert result.is_subscribed is True
        assert result.channels == []

    def test_not_subscribed(self):
        ch = MagicMock()
        result = SubscriptionCheckResult(is_subscribed=False, channels=[ch])
        assert result.is_subscribed is False
        assert len(result.channels) == 1


class TestSubscriptionChannelRepository:
    """Tests for SubscriptionChannelRepository"""

    @pytest.mark.asyncio
    async def test_get_all(self, test_db):
        repo = SubscriptionChannelRepository(test_db)

        await repo.create(bot_id=1, channel_chat_id=-1001234567890)
        await repo.create(bot_id=1, channel_chat_id=-1009876543210)
        await test_db.commit()

        channels = await repo.get_all()
        assert len(channels) == 2

    @pytest.mark.asyncio
    async def test_get_all_by_bot_id(self, test_db):
        repo = SubscriptionChannelRepository(test_db)

        await repo.create(bot_id=1, channel_chat_id=-1001111111111)
        await repo.create(bot_id=2, channel_chat_id=-1002222222222)
        await test_db.commit()

        bot1_channels = await repo.get_all(bot_id=1)
        assert len(bot1_channels) == 1
        assert bot1_channels[0].channel_chat_id == -1001111111111

    @pytest.mark.asyncio
    async def test_get_active_required(self, test_db):
        repo = SubscriptionChannelRepository(test_db)

        await repo.create(bot_id=1, channel_chat_id=-1001111111111, channel_username="test_channel")
        await test_db.commit()

        channels = await repo.get_active_required(1)
        assert len(channels) == 1
        assert channels[0].channel_username == "test_channel"

    @pytest.mark.asyncio
    async def test_get_active_required_excludes_inactive(self, test_db):
        repo = SubscriptionChannelRepository(test_db)

        ch = await repo.create(bot_id=1, channel_chat_id=-1001111111111)
        await test_db.commit()

        # Deactivate
        await repo.toggle_active(ch.id)
        await test_db.commit()

        channels = await repo.get_active_required(1)
        assert len(channels) == 0

    @pytest.mark.asyncio
    async def test_get_by_id(self, test_db):
        repo = SubscriptionChannelRepository(test_db)

        ch = await repo.create(
            bot_id=1,
            channel_chat_id=-1001111111111,
            channel_username="my_channel",
            channel_title="My Channel",
        )
        await test_db.commit()

        found = await repo.get_by_id(ch.id)
        assert found is not None
        assert found.channel_title == "My Channel"

    @pytest.mark.asyncio
    async def test_update(self, test_db):
        repo = SubscriptionChannelRepository(test_db)

        ch = await repo.create(bot_id=1, channel_chat_id=-1001111111111)
        await test_db.commit()

        updated = await repo.update(ch.id, channel_title="Updated Title")
        assert updated is not None
        assert updated.channel_title == "Updated Title"

    @pytest.mark.asyncio
    async def test_toggle_active(self, test_db):
        repo = SubscriptionChannelRepository(test_db)

        ch = await repo.create(bot_id=1, channel_chat_id=-1001111111111)
        await test_db.commit()

        assert ch.is_active is True

        toggled = await repo.toggle_active(ch.id)
        assert toggled is not None
        assert toggled.is_active is False

        toggled = await repo.toggle_active(ch.id)
        assert toggled.is_active is True

    @pytest.mark.asyncio
    async def test_delete(self, test_db):
        repo = SubscriptionChannelRepository(test_db)

        ch = await repo.create(bot_id=1, channel_chat_id=-1001111111111)
        await test_db.commit()

        await repo.delete(ch.id)
        await test_db.commit()

        found = await repo.get_by_id(ch.id)
        assert found is None


class TestSubscriptionService:
    """Tests for SubscriptionService"""

    @pytest.mark.asyncio
    async def test_get_required_channels(self, test_db):
        service = SubscriptionService()

        from repositories.uow import UnitOfWork
        from repositories.subscription import SubscriptionChannelRepository

        # Manually create a channel
        repo = SubscriptionChannelRepository(test_db)
        await repo.create(
            bot_id=1,
            channel_chat_id=-1001111111111,
            channel_username="test_channel",
        )
        await test_db.commit()

        channels = await service.get_required_channels(bot_id=1)
        assert len(channels) == 1
        assert channels[0].channel_username == "test_channel"

    @pytest.mark.asyncio
    async def test_check_user_subscription_no_channels(self):
        service = SubscriptionService()
        mock_bot = AsyncMock()

        result = await service.check_user_subscription(
            user_id=123,
            bot=mock_bot,
            channels=[],
        )

        assert result.is_subscribed is True

    @pytest.mark.asyncio
    async def test_check_user_subscription_subscribed(self):
        service = SubscriptionService()
        mock_bot = AsyncMock()
        mock_member = MagicMock()
        mock_member.status = "member"
        mock_bot.get_chat_member.return_value = mock_member

        channel = SubscriptionChannel(
            bot_id=1,
            channel_chat_id=-1001111111111,
        )

        result = await service.check_user_subscription(
            user_id=123,
            bot=mock_bot,
            channels=[channel],
        )

        assert result.is_subscribed is True
        assert result.channels == []

    @pytest.mark.asyncio
    async def test_check_user_subscription_not_subscribed(self):
        service = SubscriptionService()
        mock_bot = AsyncMock()
        mock_member = MagicMock()
        mock_member.status = "left"
        mock_bot.get_chat_member.return_value = mock_member

        channel = SubscriptionChannel(
            bot_id=1,
            channel_chat_id=-1001111111111,
        )

        result = await service.check_user_subscription(
            user_id=123,
            bot=mock_bot,
            channels=[channel],
        )

        assert result.is_subscribed is False
        assert len(result.channels) == 1

    @pytest.mark.asyncio
    async def test_check_user_subscription_telegram_forbidden_error(self):
        """Should fail-open on TelegramForbiddenError"""
        service = SubscriptionService()
        mock_bot = AsyncMock()
        mock_bot.get_chat_member.side_effect = TelegramForbiddenError(
            "Bot is not a member of the chat", {}
        )

        channel = SubscriptionChannel(
            bot_id=1,
            channel_chat_id=-1001111111111,
        )

        result = await service.check_user_subscription(
            user_id=123,
            bot=mock_bot,
            channels=[channel],
        )

        # Should fail-open (assume subscribed)
        assert result.is_subscribed is True

    def test_build_subscribe_keyboard(self):
        service = SubscriptionService()

        channels = [
            MagicMock(
                id=1,
                channel_username="my_channel",
                channel_title="My Awesome Channel",
            ),
        ]

        keyboard = service.build_subscribe_keyboard(channels)

        assert len(keyboard.inline_keyboard) == 2  # Subscribe button + Check button
        assert "my_channel" in keyboard.inline_keyboard[0][0].url
        assert "Subscribe" in keyboard.inline_keyboard[0][0].text
        assert keyboard.inline_keyboard[1][0].callback_data == "check_subscription"

    def test_build_prompt_message_empty(self):
        service = SubscriptionService()
        msg = service.build_prompt_message([])
        assert "You can use the bot" in msg

    def test_build_prompt_message_with_channels(self):
        service = SubscriptionService()

        channels = [
            MagicMock(
                channel_title="Channel One",
                channel_username=None,
                id=1,
            ),
        ]

        msg = service.build_prompt_message(channels)

        assert "Access Restricted" in msg
        assert "Channel One" in msg
        assert "subscribe" in msg.lower()
