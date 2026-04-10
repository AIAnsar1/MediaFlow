"""Tests for user CRUD controller endpoints"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from models import TelegramUser
from repositories import UserRepository


class TestUserRepository:
    """Tests for UserRepository"""

    @pytest.mark.asyncio
    async def test_get_all_with_offset(self, test_db):
        repo = UserRepository(test_db)

        # Create some users
        for i in range(5):
            await repo.create(
                telegram_id=1000 + i,
                bot_id=1,
                username=f"user_{i}",
                first_name=f"User {i}",
            )
        await test_db.commit()

        # First page
        users = await repo.get_all(offset=0, limit=3)
        assert len(users) == 3

        # Second page
        users = await repo.get_all(offset=3, limit=3)
        assert len(users) == 2

    @pytest.mark.asyncio
    async def test_get_by_id(self, test_db):
        repo = UserRepository(test_db)

        user = await repo.create(
            telegram_id=123456789,
            bot_id=1,
            username="testuser",
            first_name="Test",
        )
        await test_db.commit()

        found = await repo.get_by_id(user.id)
        assert found is not None
        assert found.username == "testuser"

    @pytest.mark.asyncio
    async def test_update_is_banned(self, test_db):
        """Test banning/unbanning user"""
        repo = UserRepository(test_db)

        user = await repo.create(
            telegram_id=123456789,
            bot_id=1,
            username="testuser",
            first_name="Test",
        )
        await test_db.commit()

        updated = await repo.update(user.id, is_banned=True)
        assert updated is not None
        assert updated.is_banned is True

    @pytest.mark.asyncio
    async def test_delete_user(self, test_db):
        """Test user deletion"""
        repo = UserRepository(test_db)

        user = await repo.create(
            telegram_id=123456789,
            bot_id=1,
            username="testuser",
            first_name="Test",
        )
        await test_db.commit()

        await repo.delete(user.id)
        await test_db.commit()

        found = await repo.get_by_id(user.id)
        assert found is None

    @pytest.mark.asyncio
    async def test_count(self, test_db):
        repo = UserRepository(test_db)

        for i in range(3):
            await repo.create(
                telegram_id=1000 + i,
                bot_id=1,
                username=f"user_{i}",
                first_name=f"User {i}",
            )
        await test_db.commit()

        total = await repo.count()
        assert total == 3
