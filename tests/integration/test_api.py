import pytest


@pytest.mark.asyncio
class TestAdminAPI:
    """Integration tests for Admin API"""

    async def test_login_page(self, client):
        """Test login page loads"""
        response = await client.get("/admin/login")

        assert response.status_code == 200
        assert b"Login" in response.content or b"Sign In" in response.content

    async def test_login_success(self, client, test_cache):
        """Test successful login"""
        response = await client.post(
            "/admin/login",
            data={
                "username": "admin",
                "password": "testpassword123",
            },
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.headers.get("location") == "/admin"
        assert "session_id" in response.cookies

    async def test_login_failure(self, client, test_cache):
        """Test failed login"""
        response = await client.post(
            "/admin/login",
            data={
                "username": "admin",
                "password": "wrongpassword",
            },
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert "error" in response.headers.get("location", "")

    async def test_protected_route_requires_auth(self, client):
        """Test that protected routes require authentication"""
        response = await client.get("/admin", follow_redirects=False)

        assert response.status_code == 302
        assert "/login" in response.headers.get("location", "")

    async def test_protected_route_with_auth(self, auth_client):
        """Test protected route with authentication"""
        response = await auth_client.get("/admin")

        assert response.status_code == 200


@pytest.mark.asyncio
class TestWebhookAPI:
    """Integration tests for Webhook API"""

    async def test_webhook_accepts_update(self, client):
        """Test webhook accepts Telegram update"""
        # Имитируем Telegram update
        update = {
            "update_id": 123456789,
            "message": {
                "message_id": 1,
                "from": {
                    "id": 12345,
                    "first_name": "Test",
                    "is_bot": False,
                },
                "chat": {
                    "id": 12345,
                    "type": "private",
                },
                "date": 1234567890,
                "text": "/start",
            },
        }

        response = await client.post(
            "/webhook/fake_token_12345",
            json=update,
        )

        # Всегда 200 OK для Telegram
        assert response.status_code == 200
        assert response.json()["ok"]