import pytest

from services.cache import cache


@pytest.mark.asyncio
class TestCacheService:
    """Tests for CacheService"""

    async def test_set_and_get(self, test_cache):
        """Test basic set and get"""
        await cache.set("test_key", "test_value")
        result = await cache.get("test_key")

        assert result == "test_value"

    async def test_set_dict(self, test_cache):
        """Test set and get dict"""
        data = {"key": "value", "number": 42}
        await cache.set("test_dict", data)
        result = await cache.get("test_dict")

        assert result == data

    async def test_delete(self, test_cache):
        """Test delete"""
        await cache.set("test_delete", "value")
        assert await cache.exists("test_delete")

        await cache.delete("test_delete")
        assert not await cache.exists("test_delete")

    async def test_exists(self, test_cache):
        """Test exists"""
        assert not await cache.exists("nonexistent_key")

        await cache.set("existing_key", "value")
        assert await cache.exists("existing_key")

    async def test_incr(self, test_cache):
        """Test increment"""
        await cache.set("counter", "0")

        result = await cache.incr("counter")
        assert result == 1

        result = await cache.incr("counter", 5)
        assert result == 6

    async def test_cache_media(self, test_cache):
        """Test media caching"""
        url = "https://example.com/video.mp4"
        file_id = "AgACAgIAAxk..."

        await cache.cache_media(
            url=url,
            file_id=file_id,
            message_id=123,
            chat_id=-100123456,
            quality="720p",
            title="Test Video",
        )

        cached = await cache.get_cached_media(url, "720p")

        assert cached is not None
        assert cached["file_id"] == file_id
        assert cached["quality"] == "720p"

    async def test_user_state(self, test_cache):
        """Test user state management"""
        user_id = 12345
        bot_id = 67890

        await cache.set_user_state(
            user_id=user_id,
            bot_id=bot_id,
            state="waiting_for_url",
            data={"some": "data"},
        )

        state = await cache.get_user_state(user_id, bot_id)

        assert state is not None
        assert state["state"] == "waiting_for_url"
        assert state["data"]["some"] == "data"

        await cache.clear_user_state(user_id, bot_id)
        state = await cache.get_user_state(user_id, bot_id)
        assert state is None

    async def test_rate_limit_check(self, test_cache):
        """Test rate limit check"""
        allowed, remaining = await cache.check_rate_limit(
            key="test_rate_limit",
            limit=5,
            window=60,
        )

        assert allowed
        assert remaining == 4