import pytest


@pytest.mark.asyncio
class TestBotsAPI:
    """Integration tests for Bots API"""

    async def test_bots_list_unauthorized(self, client):
        """Test bots list requires auth"""
        response = await client.get("/admin/bots", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers.get("location", "")

    async def test_bots_list_authorized(self, auth_client, test_db, bot_factory):
        """Test bots list with auth"""
        from repositories import BotRepository

        repo = BotRepository(test_db)
        bot = bot_factory()
        await repo.create(
            token=bot.token,
            bot_id=bot.bot_id,
            username=bot.username,
            name=bot.name,
        )

        response = await auth_client.get("/admin/bots")

        assert response.status_code == 200
        assert b"Bots" in response.content

    async def test_bot_create_page(self, auth_client):
        """Test bot create page loads"""
        response = await auth_client.get("/admin/bots/create")

        assert response.status_code == 200
        assert b"Add" in response.content or b"Create" in response.content


@pytest.mark.asyncio
class TestAdsAPI:
    """Integration tests for Ads API"""

    async def test_ads_list_unauthorized(self, client):
        """Test ads list requires auth"""
        response = await client.get("/admin/ads", follow_redirects=False)
        assert response.status_code == 302

    async def test_ads_list_authorized(self, auth_client):
        """Test ads list with auth"""
        response = await auth_client.get("/admin/ads")

        assert response.status_code == 200
        assert b"Advertising" in response.content or b"Ads" in response.content

    async def test_ads_create_page(self, auth_client):
        """Test ads create page loads"""
        response = await auth_client.get("/admin/ads/create")

        assert response.status_code == 200


@pytest.mark.asyncio
class TestQueuesAPI:
    """Integration tests for Queues API"""

    async def test_queues_dashboard_unauthorized(self, client):
        """Test queues dashboard requires auth"""
        response = await client.get("/admin/queues", follow_redirects=False)
        assert response.status_code == 302

    async def test_queues_dashboard_authorized(self, auth_client):
        """Test queues dashboard with auth"""
        response = await auth_client.get("/admin/queues")

        assert response.status_code == 200
        assert b"Queue" in response.content

    async def test_queues_jobs_list(self, auth_client):
        """Test jobs list"""
        response = await auth_client.get("/admin/queues/jobs")

        assert response.status_code == 200


@pytest.mark.asyncio
class TestStatsAPI:
    """Integration tests for Stats API"""

    async def test_stats_overview_unauthorized(self, client):
        """Test stats overview requires auth"""
        response = await client.get("/admin/stats", follow_redirects=False)
        assert response.status_code == 302

    async def test_stats_overview_authorized(self, auth_client):
        """Test stats overview with auth"""
        response = await auth_client.get("/admin/stats")

        assert response.status_code == 200
        assert b"Statistics" in response.content

    async def test_stats_chart_data(self, auth_client):
        """Test chart data API"""
        response = await auth_client.get("/admin/stats/api/chart-data?metric=downloads")

        assert response.status_code == 200
        data = response.json()
        assert "labels" in data
        assert "datasets" in data


@pytest.mark.asyncio
class TestHealthAPI:
    """Integration tests for Health API"""

    async def test_health_check(self, client):
        """Test health check endpoint"""
        response = await client.get("/health")

        assert response.status_code in [200, 503]
        data = response.json()
        assert "status" in data
        assert "database" in data
        assert "cache" in data

    async def test_readiness_check(self, client):
        """Test readiness endpoint"""
        response = await client.get("/health/ready")

        assert response.status_code == 200
        assert response.json()["ready"] is True

    async def test_liveness_check(self, client):
        """Test liveness endpoint"""
        response = await client.get("/health/live")

        assert response.status_code == 200
        assert response.json()["live"] is True