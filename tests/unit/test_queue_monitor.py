import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock

from services.queue_monitor import queue_monitor, QueueMonitorService, JobState, QueueStats


@pytest.mark.asyncio
class TestQueueMonitorService:
    """Tests for QueueMonitorService"""

    async def test_get_queue_stats(self, test_cache):
        """Test queue statistics retrieval"""
        with patch.object(queue_monitor, 'get_pool', new_callable=AsyncMock):
            stats = await queue_monitor.get_queue_stats()

            assert isinstance(stats, QueueStats)
            assert stats.pending >= 0
            assert stats.running >= 0
            assert stats.complete >= 0
            assert stats.failed >= 0
            assert 0 <= stats.success_rate <= 100

    async def test_get_pending_jobs_empty(self, test_cache):
        """Test getting pending jobs when queue is empty"""
        jobs = await queue_monitor.get_pending_jobs(limit=10)

        assert isinstance(jobs, list)
        assert len(jobs) == 0

    async def test_get_running_jobs_empty(self, test_cache):
        """Test getting running jobs when none running"""
        jobs = await queue_monitor.get_running_jobs()

        assert isinstance(jobs, list)
        assert len(jobs) == 0

    async def test_get_failed_jobs_empty(self, test_cache):
        """Test getting failed jobs when none failed"""
        jobs = await queue_monitor.get_failed_jobs(limit=10)

        assert isinstance(jobs, list)
        assert len(jobs) == 0

    async def test_get_recent_jobs(self, test_cache):
        """Test getting recent jobs"""
        jobs = await queue_monitor.get_recent_jobs(limit=20)

        assert isinstance(jobs, list)

    async def test_delete_job(self, test_cache):
        """Test job deletion"""
        # Delete non-existent job should return True (no error)
        result = await queue_monitor.delete_job("non_existent_job_id")
        assert result is True

    async def test_get_workers_status_empty(self, test_cache):
        """Test workers status when no workers"""
        workers = await queue_monitor.get_workers_status()

        assert isinstance(workers, list)

    async def test_get_active_broadcasts_empty(self, test_cache):
        """Test active broadcasts when none active"""
        broadcasts = await queue_monitor.get_active_broadcasts()

        assert isinstance(broadcasts, list)
        assert len(broadcasts) == 0

    async def test_get_active_broadcasts_with_data(self, test_cache):
        """Test active broadcasts with data"""
        from services.metrics import metrics

        # Create a broadcast progress
        await metrics.record_broadcast_progress(
            ad_id=123,
            sent=50,
            failed=5,
            total=100,
        )

        broadcasts = await queue_monitor.get_active_broadcasts()

        assert len(broadcasts) >= 1
        broadcast = next((b for b in broadcasts if b["ad_id"] == 123), None)
        assert broadcast is not None
        assert broadcast["sent"] == 50