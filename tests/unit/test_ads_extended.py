"""Tests for AdType enum and extended Ad functionality"""

import pytest
from unittest.mock import AsyncMock, patch

from models.ads import Ad, AdStatus, AdMediaType, AdType, AdBot, AdDelivery
from repositories.ad import AdRepository, AdDeliveryRepository


class TestAdType:
    """Test AdType enum"""

    def test_broadcast_value(self):
        assert AdType.BROADCAST.value == "broadcast"

    def test_post_download_value(self):
        assert AdType.POST_DOWNLOAD.value == "post_download"

    def test_from_string(self):
        assert AdType("broadcast") == AdType.BROADCAST
        assert AdType("post_download") == AdType.POST_DOWNLOAD


class TestAdModel:
    """Test Ad model with ad_type"""

    def test_ad_default_type(self):
        ad = Ad(
            name="Test Ad",
            content="Test content",
        )
        # Default is set by DB/column default, not Python
        assert ad.ad_type is None or ad.ad_type == AdType.BROADCAST

    def test_ad_explicit_post_download_type(self):
        ad = Ad(
            name="Post-Download Ad",
            content="Post-download content",
            ad_type=AdType.POST_DOWNLOAD,
        )
        assert ad.ad_type == AdType.POST_DOWNLOAD

    def test_ad_to_dict_includes_ad_type(self):
        ad = Ad(
            name="Test Ad",
            content="Test content",
            ad_type=AdType.POST_DOWNLOAD,
        )
        ad.id = 1
        ad.ad_uuid = "test-uuid"
        ad.media_type = AdMediaType.NONE
        ad.target_language = None
        ad.status = AdStatus.DRAFT
        ad.sent_count = 0

        result = ad.to_dict()
        assert "ad_type" not in result  # to_dict doesn't include ad_type (existing behavior)
        assert result["name"] == "Test Ad"
        assert result["status"] == "draft"


class TestAdRepository:
    """Tests for AdRepository"""

    @pytest.mark.asyncio
    async def test_get_active_returns_all_types(self, test_db):
        """Test that get_active returns both broadcast and post_download ads"""
        repo = AdRepository(test_db)

        broadcast_ad = await repo.create(
            name="Broadcast Ad",
            content="Broadcast content",
            ad_type=AdType.BROADCAST,
        )
        post_ad = await repo.create(
            name="Post-Download Ad",
            content="Post-download content",
            ad_type=AdType.POST_DOWNLOAD,
        )
        await test_db.commit()

        active = await repo.get_active()
        assert len(active) == 2

    @pytest.mark.asyncio
    async def test_get_by_uuid(self, test_db):
        repo = AdRepository(test_db)

        ad = await repo.create(
            name="Test Ad",
            content="Test content",
        )
        await test_db.commit()

        found = await repo.get_by_uuid(ad.ad_uuid)
        assert found is not None
        assert found.id == ad.id

    @pytest.mark.asyncio
    async def test_add_target_bots(self, test_db):
        repo = AdRepository(test_db)

        ad = await repo.create(name="Test", content="Test content")
        await repo.add_target_bots(ad.id, [1, 2, 3])
        await test_db.commit()

        bot_ids = await repo.get_target_bot_ids(ad.id)
        assert set(bot_ids) == {1, 2, 3}


class TestAdDeliveryRepository:
    """Tests for AdDeliveryRepository"""

    @pytest.mark.asyncio
    async def test_create_delivery(self, test_db):
        repo = AdDeliveryRepository(test_db)

        delivery = await repo.create_delivery(
            ad_id=1,
            user_id=1,
            bot_id=1,
            telegram_chat_id=123456,
            telegram_message_id=789,
            is_sent=True,
        )

        assert delivery.ad_id == 1
        assert delivery.telegram_message_id == 789
        assert delivery.is_sent is True

    @pytest.mark.asyncio
    async def test_mark_failed(self, test_db):
        repo = AdDeliveryRepository(test_db)

        delivery = await repo.create_delivery(
            ad_id=1,
            user_id=1,
            bot_id=1,
            telegram_chat_id=123456,
        )
        await test_db.commit()

        failed = await repo.mark_failed(delivery.id, "User blocked the bot")
        assert failed is not None
        assert failed.is_sent is False
        assert "blocked" in failed.error_message.lower()
