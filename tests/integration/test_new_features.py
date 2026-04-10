"""Integration tests for new controller endpoints: telemetry, subscriptions, user CRUD"""

import pytest


@pytest.mark.asyncio
class TestTelemetryController:
    """Integration tests for Telemetry endpoints"""

    async def test_telemetry_requires_auth(self, client):
        """Telemetry page should require auth"""
        response = await client.get("/admin/telemetry", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers.get("location", "")

    async def test_telemetry_api_requires_auth(self, client):
        """Telemetry API should require auth"""
        response = await client.get("/admin/telemetry/api/snapshot", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers.get("location", "")

    async def test_telemetry_page_accessible_with_auth(self, auth_client):
        """Telemetry page should be accessible with auth"""
        response = await auth_client.get("/admin/telemetry")
        assert response.status_code == 200

    async def test_telemetry_api_returns_data(self, auth_client):
        """Telemetry API should return telemetry snapshot"""
        response = await auth_client.get("/admin/telemetry/api/snapshot")
        assert response.status_code == 200

        data = response.json()
        assert "cpu" in data
        assert "memory" in data
        assert "disks" in data
        assert "network" in data
        assert "uptime" in data

        # Check CPU data
        assert "percent" in data["cpu"]
        assert "cores_logical" in data["cpu"]
        assert isinstance(data["cpu"]["percent"], (int, float))

        # Check Memory data
        assert "total_gb" in data["memory"]
        assert "percent" in data["memory"]
        assert isinstance(data["memory"]["total_gb"], (int, float))


@pytest.mark.asyncio
class TestSubscriptionController:
    """Integration tests for Subscription endpoints"""

    async def test_subscriptions_requires_auth(self, client):
        """Subscriptions page should require auth"""
        response = await client.get("/admin/subscriptions", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers.get("location", "")

    async def test_subscriptions_page_with_auth(self, auth_client):
        """Subscriptions page should be accessible with auth"""
        response = await auth_client.get("/admin/subscriptions")
        assert response.status_code == 200

    async def test_subscription_create_form(self, auth_client):
        """Create form should load"""
        response = await auth_client.get("/admin/subscriptions/create")
        assert response.status_code == 200

    async def test_subscription_create_requires_fields(self, auth_client):
        """Create should redirect on missing fields"""
        response = await auth_client.post(
            "/admin/subscriptions/create",
            data={
                "bot_id": "1",
                # Missing channel_chat_id
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "error" in response.headers.get("location", "")


@pytest.mark.asyncio
class TestUserController:
    """Integration tests for User CRUD endpoints"""

    async def test_users_list_requires_auth(self, client):
        """Users list should require auth"""
        response = await client.get("/admin/users", follow_redirects=False)
        assert response.status_code == 302
        assert "/login" in response.headers.get("location", "")

    async def test_users_list_with_auth(self, auth_client):
        """Users list should work with auth"""
        response = await auth_client.get("/admin/users")
        assert response.status_code == 200

    async def test_users_pagination(self, auth_client):
        """Users list should support pagination"""
        response = await auth_client.get("/admin/users?page=1&limit=20")
        assert response.status_code == 200


@pytest.mark.asyncio
class TestAdControllerExtended:
    """Integration tests for extended Ad controller (ad_type)"""

    async def test_ad_create_form_loads(self, auth_client):
        """Ad create form should load"""
        response = await auth_client.get("/admin/ads/create")
        assert response.status_code == 200

    async def test_ad_create_post_download_type(self, auth_client):
        """Creating a post-download ad should work"""
        response = await auth_client.post(
            "/admin/ads/create",
            data={
                "name": "Test Post-Download Ad",
                "content": "Check out our sponsor!",
                "ad_type": "post_download",
                "button_text": "Visit Sponsor",
                "button_url": "https://example.com",
                "target_language": "en",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers.get("location", "")
        assert "/admin/ads/" in location

    async def test_ad_create_broadcast_requires_bot(self, auth_client):
        """Broadcast ad requires at least one bot or should fail gracefully"""
        response = await auth_client.post(
            "/admin/ads/create",
            data={
                "name": "Test Broadcast",
                "content": "Broadcast content",
                "ad_type": "broadcast",
                # No bot_ids — should fail
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert "error" in response.headers.get("location", "")
