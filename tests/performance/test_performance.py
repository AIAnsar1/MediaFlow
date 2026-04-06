import pytest
import asyncio
import time


@pytest.mark.asyncio
class TestPerformance:
    """Performance tests"""

    async def test_cache_performance(self, test_cache):
        """Test cache read/write performance"""
        from services.cache import cache

        start = time.time()

        # Write 1000 keys
        for i in range(1000):
            await cache.set(f"perf_test_{i}", {"value": i})

        write_time = time.time() - start

        start = time.time()

        # Read 1000 keys
        for i in range(1000):
            await cache.get(f"perf_test_{i}")

        read_time = time.time() - start

        # Should complete in reasonable time
        assert write_time < 5.0  # 5 seconds for 1000 writes
        assert read_time < 3.0   # 3 seconds for 1000 reads

        # Cleanup
        for i in range(1000):
            await cache.delete(f"perf_test_{i}")

    async def test_rate_limiter_performance(self, test_cache, test_rate_limiter):
        """Test rate limiter performance under load"""
        from services.rate_limiter import rate_limiter, RateLimitType

        start = time.time()

        # Check rate limit 500 times
        tasks = [
            rate_limiter.check(RateLimitType.USER, f"user_{i % 50}")
            for i in range(500)
        ]

        results = await asyncio.gather(*tasks)

        elapsed = time.time() - start

        # Should complete quickly
        assert elapsed < 3.0  # 3 seconds for 500 checks
        assert len(results) == 500

    async def test_metrics_performance(self, test_cache, test_metrics):
        """Test metrics recording performance"""
        from services.metrics import metrics

        start = time.time()

        # Record 1000 metrics
        tasks = [
            metrics.increment(f"perf_counter_{i % 10}")
            for i in range(1000)
        ]

        await asyncio.gather(*tasks)

        elapsed = time.time() - start

        # Should be fast
        assert elapsed < 5.0  # 5 seconds for 1000 increments

    async def test_concurrent_downloads_check(self, test_cache):
        """Test concurrent download checks"""
        from services.downloader import download_service, MediaPlatform

        urls = [
            f"https://www.youtube.com/watch?v=test{i}"
            for i in range(100)
        ]

        start = time.time()

        # Check platform for 100 URLs
        results = [download_service.detect_platform(url) for url in urls]

        elapsed = time.time() - start

        # Should be instant (no I/O)
        assert elapsed < 0.1
        assert all(r == MediaPlatform.YOUTUBE for r in results)