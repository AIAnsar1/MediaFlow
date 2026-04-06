import pytest
import asyncio

from services.rate_limiter import (
    rate_limiter,
    RateLimitType,
    RateLimitConfig,
    RateLimitResult,
)


@pytest.mark.asyncio
class TestRateLimiter:
    """Tests for RateLimiter"""

    async def test_check_allows_first_request(self, test_cache):
        """Test that first request is allowed"""
        result = await rate_limiter.check(
            RateLimitType.USER,
            identifier="test_user_1",
            config=RateLimitConfig(requests=10, window=60),
        )

        assert result.allowed
        assert result.remaining == 9

    async def test_check_blocks_after_limit(self, test_cache):
        """Test that requests are blocked after limit"""
        config = RateLimitConfig(requests=3, window=60)
        identifier = "test_user_limit"

        # Делаем 3 запроса
        for i in range(3):
            result = await rate_limiter.check(
                RateLimitType.USER,
                identifier=identifier,
                config=config,
            )
            assert result.allowed

        # 4-й запрос должен быть заблокирован
        result = await rate_limiter.check(
            RateLimitType.USER,
            identifier=identifier,
            config=config,
        )

        assert not result.allowed
        assert result.remaining == 0
        assert result.retry_after > 0

    async def test_check_user_rate_limit(self, test_cache):
        """Test user rate limit check"""
        result = await rate_limiter.check_user(user_id=12345)

        assert isinstance(result, RateLimitResult)
        assert result.allowed

    async def test_check_download_rate_limit(self, test_cache):
        """Test download rate limit check"""
        result = await rate_limiter.check_download(user_id=12345)

        assert isinstance(result, RateLimitResult)
        assert result.allowed

    async def test_check_global_rate_limit(self, test_cache):
        """Test global rate limit check"""
        result = await rate_limiter.check_global()

        assert isinstance(result, RateLimitResult)
        assert result.allowed

    async def test_check_all_combined(self, test_cache):
        """Test combined rate limit check"""
        result = await rate_limiter.check_all(
            user_id=12345,
            bot_id=67890,
            action=RateLimitType.DOWNLOAD,
        )

        assert isinstance(result, RateLimitResult)
        assert result.allowed

    async def test_reset_rate_limit(self, test_cache):
        """Test rate limit reset"""
        config = RateLimitConfig(requests=1, window=60)
        identifier = "test_user_reset"

        # Исчерпываем лимит
        await rate_limiter.check(RateLimitType.USER, identifier, config)
        result = await rate_limiter.check(RateLimitType.USER, identifier, config)
        assert not result.allowed

        # Сбрасываем
        await rate_limiter.reset(RateLimitType.USER, identifier)

        # Теперь должно работать
        result = await rate_limiter.check(RateLimitType.USER, identifier, config)
        assert result.allowed

    async def test_different_identifiers_independent(self, test_cache):
        """Test that different identifiers have independent limits"""
        config = RateLimitConfig(requests=1, window=60)

        result1 = await rate_limiter.check(RateLimitType.USER, "user_a", config)
        result2 = await rate_limiter.check(RateLimitType.USER, "user_b", config)

        # Оба должны быть разрешены
        assert result1.allowed
        assert result2.allowed