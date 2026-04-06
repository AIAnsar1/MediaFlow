import pytest
from datetime import datetime, timedelta

from services.metrics import metrics, MetricsService, MetricsTimer


@pytest.mark.asyncio
class TestMetricsService:
    """Tests for MetricsService"""

    async def test_increment_counter(self, test_cache):
        """Test counter increment"""
        result = await metrics.increment("test_counter")
        assert result == 1

        result = await metrics.increment("test_counter")
        assert result == 2

        result = await metrics.increment("test_counter", value=5)
        assert result == 7

    async def test_increment_with_labels(self, test_cache):
        """Test counter with labels"""
        await metrics.increment("downloads", labels={"platform": "youtube"})
        await metrics.increment("downloads", labels={"platform": "youtube"})
        await metrics.increment("downloads", labels={"platform": "instagram"})

        yt_count = await metrics.get_counter("downloads", labels={"platform": "youtube"})
        ig_count = await metrics.get_counter("downloads", labels={"platform": "instagram"})

        assert yt_count == 2
        assert ig_count == 1

    async def test_set_and_get_gauge(self, test_cache):
        """Test gauge operations"""
        await metrics.set_gauge("cpu_usage", 45.5)
        value = await metrics.get_gauge("cpu_usage")

        assert value == 45.5

        await metrics.set_gauge("cpu_usage", 60.0)
        value = await metrics.get_gauge("cpu_usage")

        assert value == 60.0

    async def test_record_timing(self, test_cache):
        """Test timing recording"""
        await metrics.record_timing("api_request", 150.5)
        await metrics.record_timing("api_request", 200.0)
        await metrics.record_timing("api_request", 100.0)

        avg = await metrics.get_gauge("api_request_avg")
        count = await metrics.get_counter("api_request_count")

        assert count == 3
        # Average should be around 150
        assert 140 < avg < 160

    async def test_record_download(self, test_cache):
        """Test download metrics recording"""
        await metrics.record_download(
            platform="youtube",
            bot_id=1,
            duration_ms=500.0,
            success=True,
            from_cache=False,
        )

        total = await metrics.get_counter("downloads_total", labels={"platform": "youtube", "bot_id": "1"})
        success = await metrics.get_counter("downloads_success", labels={"platform": "youtube", "bot_id": "1"})

        assert total == 1
        assert success == 1

    async def test_record_download_cached(self, test_cache):
        """Test cached download metrics"""
        await metrics.record_download(
            platform="instagram",
            bot_id=1,
            duration_ms=50.0,
            success=True,
            from_cache=True,
        )

        cached = await metrics.get_counter("downloads_cached", labels={"platform": "instagram", "bot_id": "1"})
        assert cached == 1

    async def test_record_download_failed(self, test_cache):
        """Test failed download metrics"""
        await metrics.record_download(
            platform="tiktok",
            bot_id=1,
            duration_ms=1000.0,
            success=False,
        )

        failed = await metrics.get_counter("downloads_failed", labels={"platform": "tiktok", "bot_id": "1"})
        assert failed == 1

    async def test_record_error(self, test_cache):
        """Test error recording"""
        await metrics.record_error("TelegramAPIError", bot_id=1)
        await metrics.record_error("TelegramAPIError", bot_id=1)
        await metrics.record_error("DownloadError", bot_id=2)

        api_errors = await metrics.get_counter("errors_total", labels={"type": "TelegramAPIError", "bot_id": "1"})
        dl_errors = await metrics.get_counter("errors_total", labels={"type": "DownloadError", "bot_id": "2"})

        assert api_errors == 2
        assert dl_errors == 1

    async def test_broadcast_progress(self, test_cache):
        """Test broadcast progress tracking"""
        await metrics.record_broadcast_progress(
            ad_id=1,
            sent=50,
            failed=2,
            total=100,
        )

        progress = await metrics.get_broadcast_progress(1)

        assert progress is not None
        assert progress["sent"] == 50
        assert progress["failed"] == 2
        assert progress["total"] == 100
        assert progress["progress"] == 50.0

    async def test_get_dashboard_stats(self, test_cache):
        """Test dashboard stats aggregation"""
        # Record some data
        for _ in range(5):
            await metrics.increment("downloads_youtube")
        for _ in range(3):
            await metrics.increment("downloads_instagram")

        stats = await metrics.get_dashboard_stats()

        assert "downloads_today" in stats
        assert "by_platform" in stats
        assert "success_rate" in stats
        assert stats["by_platform"]["youtube"] == 5
        assert stats["by_platform"]["instagram"] == 3

    async def test_get_hourly_stats(self, test_cache):
        """Test hourly stats retrieval"""
        # Record some timeseries data
        await metrics.increment("downloads_total")
        await metrics.increment("downloads_total")

        hourly = await metrics.get_hourly_stats(hours=24)

        assert isinstance(hourly, list)
        # Should have data for current hour at least
        assert len(hourly) <= 24


@pytest.mark.asyncio
class TestMetricsTimer:
    """Tests for MetricsTimer context manager"""

    async def test_timer_context_manager(self, test_cache):
        """Test timing with context manager"""
        import asyncio

        async with metrics.timer("test_operation"):
            await asyncio.sleep(0.1)  # 100ms

        avg = await metrics.get_gauge("test_operation_avg")
        count = await metrics.get_counter("test_operation_count")

        assert count == 1
        assert avg >= 90  # At least 90ms