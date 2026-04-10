import pytest
from datetime import datetime, timedelta, timezone

from services.auth import auth_service, AuthUser


class TestAuthService:
    """Tests for AuthService"""

    def test_hash_password(self):
        """Test password hashing"""
        password = "test_password_123"
        hashed = auth_service.hash_password(password)

        assert hashed != password
        assert auth_service.verify_password(password, hashed)
        assert not auth_service.verify_password("wrong_password", hashed)

    def test_create_access_token(self):
        """Test access token creation"""
        token = auth_service.create_access_token("testuser")

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 50

    def test_create_refresh_token(self):
        """Test refresh token creation"""
        token = auth_service.create_refresh_token("testuser")

        assert token is not None
        assert isinstance(token, str)

    def test_verify_access_token(self):
        """Test access token verification"""
        token = auth_service.create_access_token("testuser")
        user = auth_service.verify_access_token(token)

        assert user is not None
        assert isinstance(user, AuthUser)
        assert user.username == "testuser"

    def test_verify_invalid_token(self):
        """Test invalid token rejection"""
        user = auth_service.verify_access_token("invalid_token")
        assert user is None

    def test_verify_refresh_token_as_access(self):
        """Test that refresh token can't be used as access token"""
        refresh_token = auth_service.create_refresh_token("testuser")
        user = auth_service.verify_access_token(refresh_token)
        assert user is None

    def test_decode_token(self):
        """Test token decoding"""
        token = auth_service.create_access_token("testuser")
        payload = auth_service.decode_token(token)

        assert payload is not None
        assert payload.sub == "testuser"
        assert payload.type == "access"
        # Use timezone-aware datetime to compare with token exp
        assert payload.exp > datetime.now(timezone.utc)

    def test_authenticate_admin_success(self):
        """Test successful admin authentication"""
        # Используем креды из conftest
        assert auth_service.authenticate_admin("admin", "testpassword123")

    def test_authenticate_admin_failure(self):
        """Test failed admin authentication"""
        assert not auth_service.authenticate_admin("admin", "wrongpassword")
        assert not auth_service.authenticate_admin("wronguser", "testpassword")

    def test_csrf_token(self):
        """Test CSRF token generation and verification"""
        session_id = "test_session_123"
        csrf_token = auth_service.generate_csrf_token(session_id)

        assert auth_service.verify_csrf_token(session_id, csrf_token)
        assert not auth_service.verify_csrf_token(session_id, "invalid_token")
        assert not auth_service.verify_csrf_token("other_session", csrf_token)


@pytest.mark.asyncio
class TestAuthServiceAsync:
    """Async tests for AuthService"""

    async def test_create_session(self, test_cache):
        """Test session creation"""
        session_id = await auth_service.create_session("testuser")

        assert session_id is not None
        assert len(session_id) == 64  # hex(32)

        session = await auth_service.get_session(session_id)
        assert session is not None
        assert session["username"] == "testuser"

    async def test_delete_session(self, test_cache):
        """Test session deletion"""
        session_id = await auth_service.create_session("testuser")

        await auth_service.delete_session(session_id)

        session = await auth_service.get_session(session_id)
        assert session is None

    async def test_revoke_token(self, test_cache):
        """Test token revocation"""
        token = auth_service.create_access_token("testuser")
        payload = auth_service.decode_token(token)

        await auth_service.revoke_token(token)

        is_revoked = await auth_service.is_token_revoked(payload.jti)
        assert is_revoked

    async def test_refresh_access_token(self, test_cache):
        """Test access token refresh"""
        refresh_token = auth_service.create_refresh_token("testuser")

        new_access_token = await auth_service.refresh_access_token(refresh_token)

        assert new_access_token is not None
        user = auth_service.verify_access_token(new_access_token)
        assert user.username == "testuser"
