import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
class TestWebhookHandler:
    """Integration tests for Webhook handler"""

    async def test_webhook_valid_update(self, client):
        """Test webhook with valid update"""
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
            "/webhook/123456789:ABCdefGHI",
            json=update,
        )

        # Always returns 200 for Telegram
        assert response.status_code == 200
        assert response.json()["ok"] is True

    async def test_webhook_callback_query(self, client):
        """Test webhook with callback query"""
        update = {
            "update_id": 123456790,
            "callback_query": {
                "id": "123",
                "from": {
                    "id": 12345,
                    "first_name": "Test",
                    "is_bot": False,
                },
                "chat_instance": "123456",
                "data": "set_language:en",
                "message": {
                    "message_id": 1,
                    "chat": {
                        "id": 12345,
                        "type": "private",
                    },
                    "date": 1234567890,
                },
            },
        }

        response = await client.post(
            "/webhook/123456789:ABCdefGHI",
            json=update,
        )

        assert response.status_code == 200

    async def test_webhook_url_message(self, client):
        """Test webhook with URL message"""
        update = {
            "update_id": 123456791,
            "message": {
                "message_id": 2,
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
                "text": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            },
        }

        response = await client.post(
            "/webhook/123456789:ABCdefGHI",
            json=update,
        )

        assert response.status_code == 200

    async def test_webhook_invalid_token(self, client):
        """Test webhook with non-existent bot token"""
        update = {
            "update_id": 123456792,
            "message": {
                "message_id": 1,
                "from": {"id": 12345, "first_name": "Test", "is_bot": False},
                "chat": {"id": 12345, "type": "private"},
                "date": 1234567890,
                "text": "/start",
            },
        }

        response = await client.post(
            "/webhook/invalid_token",
            json=update,
        )

        # Still returns 200 to not trigger Telegram retries
        assert response.status_code == 200

    async def test_webhook_empty_body(self, client):
        """Test webhook with empty body"""
        response = await client.post(
            "/webhook/123456789:ABCdefGHI",
            json={},
        )

        assert response.status_code == 200