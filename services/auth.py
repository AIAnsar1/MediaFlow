import bcrypt
import hmac
import jwt
import secrets
import hashlib
from datetime import datetime, timedelta
from dataclasses import dataclass

from app.config import settings
from app.logging import get_logger
from services.cache import cache

log = get_logger("service.auth")


@dataclass
class TokenPayload:
    """JWT Token payload"""
    sub: str  # username
    exp: datetime
    iat: datetime
    type: str  # "access" or "refresh"
    jti: str  # unique token id


@dataclass
class AuthUser:
    """Authenticated user"""
    username: str
    is_admin: bool = True


class AuthService:
    """
    Сервис аутентификации для админки

    - JWT токены (access + refresh)
    - Session management через Redis
    - Password hashing
    - CSRF protection
    """

    ACCESS_TOKEN_EXPIRE_MINUTES = 30
    REFRESH_TOKEN_EXPIRE_DAYS = 7
    ALGORITHM = "HS256"

    def __init__(self):
        self.secret_key = settings.secret_key

    # === Password ===

    def hash_password(self, password: str) -> str:
        """Хеширование пароля"""
        pwd_bytes = password.encode()[:72]
        return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode()

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Проверка пароля"""
        return bcrypt.checkpw(plain_password.encode()[:72], hashed_password.encode())

    # === JWT Tokens ===

    def create_access_token(self, username: str) -> str:
        """Создать access token"""
        now = datetime.utcnow()
        expire = now + timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES)

        payload = {
            "sub": username,
            "exp": expire,
            "iat": now,
            "type": "access",
            "jti": secrets.token_hex(16),
        }

        return jwt.encode(payload, self.secret_key, algorithm=self.ALGORITHM)

    def create_refresh_token(self, username: str) -> str:
        """Создать refresh token"""
        now = datetime.utcnow()
        expire = now + timedelta(days=self.REFRESH_TOKEN_EXPIRE_DAYS)

        payload = {
            "sub": username,
            "exp": expire,
            "iat": now,
            "type": "refresh",
            "jti": secrets.token_hex(16),
        }

        return jwt.encode(payload, self.secret_key, algorithm=self.ALGORITHM)

    def create_tokens(self, username: str) -> tuple[str, str]:
        """Создать пару токенов"""
        return (
            self.create_access_token(username),
            self.create_refresh_token(username),
        )

    def decode_token(self, token: str) -> TokenPayload | None:
        """Декодировать токен"""
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.ALGORITHM],
            )
            return TokenPayload(
                sub=payload["sub"],
                exp=datetime.fromtimestamp(payload["exp"]),
                iat=datetime.fromtimestamp(payload["iat"]),
                type=payload["type"],
                jti=payload["jti"],
            )
        except jwt.ExpiredSignatureError:
            log.debug("Token expired")
            return None
        except jwt.InvalidTokenError as e:
            log.debug("Invalid token", error=str(e))
            return None

    def verify_access_token(self, token: str) -> AuthUser | None:
        """Проверить access token"""
        payload = self.decode_token(token)

        if not payload:
            return None

        if payload.type != "access":
            return None

        return AuthUser(username=payload.sub)

    async def refresh_access_token(self, refresh_token: str) -> str | None:
        """Обновить access token"""
        payload = self.decode_token(refresh_token)

        if not payload:
            return None

        if payload.type != "refresh":
            return None

        # Проверяем, не отозван ли токен
        if await self.is_token_revoked(payload.jti):
            return None

        return self.create_access_token(payload.sub)

    # === Token Revocation ===

    async def revoke_token(self, token: str) -> None:
        """Отозвать токен"""
        payload = self.decode_token(token)
        if payload:
            # Сохраняем в blacklist до истечения
            ttl = int((payload.exp - datetime.utcnow()).total_seconds())
            if ttl > 0:
                await cache.set(f"revoked:{payload.jti}", "1", ttl=ttl)

    async def is_token_revoked(self, jti: str) -> bool:
        """Проверить, отозван ли токен"""
        return await cache.exists(f"revoked:{jti}")

    # === Session Management ===

    async def create_session(self, username: str) -> str:
        """Создать сессию"""
        session_id = secrets.token_hex(32)
        session_data = {
            "username": username,
            "created_at": datetime.utcnow().isoformat(),
        }

        # Сохраняем на 24 часа
        await cache.set(
            f"session:{session_id}",
            session_data,
            ttl=86400,
        )

        return session_id

    async def get_session(self, session_id: str) -> dict | None:
        """Получить сессию"""
        return await cache.get(f"session:{session_id}")

    async def delete_session(self, session_id: str) -> None:
        """Удалить сессию"""
        await cache.delete(f"session:{session_id}")

    async def extend_session(self, session_id: str) -> None:
        """Продлить сессию"""
        session = await self.get_session(session_id)
        if session:
            await cache.set(f"session:{session_id}", session, ttl=86400)

    # === CSRF ===

    def generate_csrf_token(self, session_id: str) -> str:
        """Генерация CSRF токена"""
        return hmac.new(
            self.secret_key.encode(),
            session_id.encode(),
            hashlib.sha256,
        ).hexdigest()

    def verify_csrf_token(self, session_id: str, token: str) -> bool:
        """Проверка CSRF токена"""
        expected = self.generate_csrf_token(session_id)
        return hmac.compare_digest(expected, token)

    # === Admin Authentication ===

    def authenticate_admin(self, username: str, password: str) -> bool:
        """Проверить креды админа"""
        # Простая проверка из конфига
        # В продакшене использовать БД с хешами
        return (
            username == settings.admin_username and
            password == settings.admin_password
        )


# === Singleton ===
auth_service = AuthService()
