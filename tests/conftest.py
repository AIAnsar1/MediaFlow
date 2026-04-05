import asyncio
import os
from contextlib import asynccontextmanager, suppress
from typing import AsyncGenerator  # noqa: UP035
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from faker import Faker
from litestar import Litestar
from litestar.testing import AsyncTestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Тестовое окружение ДО импортов
os.environ["USE_FAKEREDIS"] = "true"
os.environ["DEBUG"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"] = "test-secret-key-minimum-32-characters-long"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "testpassword123"
os.environ["STORAGE_CHANNEL_ID"] = "-1001234567890"
os.environ["TEMP_DOWNLOAD_PATH"] = "/tmp/mediadownloader_test"

from app.lifecycle import create_app
from database.base import Base
from database.connection import db
from models import (
    Ad,
    AdStatus,
    Bot,
    BotStatus,
    Download,
    Media,
    MediaSource,
    MediaType,
    User,
)
from services.cache import CacheService, cache
from services.metrics import MetricsService, metrics
from services.rate_limiter import rate_limiter

fake = Faker()



@asynccontextmanager
async def _test_lifespan(app: Litestar):
    """Минимальный lifespan: fixtures уже настроили db/cache/redis"""
    yield


# === Database ===

@pytest_asyncio.fixture(scope="function", autouse=True)
async def test_db() -> AsyncGenerator[AsyncSession, None]:
    """Fresh in-memory DB per test"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    # Подменяем синглтон
    db._engine = engine
    db._session_factory = session_factory
    db._loop = asyncio.get_running_loop()

    # Создаём таблицы
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        yield session
        await session.rollback()

    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()
    db._engine = None
    db._session_factory = None


# === Cache ===

@pytest_asyncio.fixture(scope="function", autouse=True)
async def test_cache() -> AsyncGenerator[CacheService, None]:
    """Fresh FakeRedis per test"""
    cache._redis = None
    await cache.connect()
    yield cache
    if cache._redis:
        with suppress(Exception):
            await cache._redis.flushall()
    cache._redis = None


# === Metrics ===

@pytest_asyncio.fixture(scope="function")
async def test_metrics(test_cache) -> MetricsService:
    return metrics


# === Rate Limiter ===

@pytest_asyncio.fixture(scope="function")
async def test_rate_limiter(test_cache):
    if cache._redis:
        await cache._redis.flushall()
    await rate_limiter.start()
    yield rate_limiter
    await rate_limiter.stop()
    if cache._redis:
        await cache._redis.flushall()


# === App Client — использует _test_lifespan ===

@pytest_asyncio.fixture(scope="function")
async def client() -> AsyncGenerator[AsyncTestClient, None]:
    app = create_app(lifespan_handlers=[_test_lifespan])
    async with AsyncTestClient(app=app) as ac:
        yield ac


# === Authenticated Client ===

@pytest_asyncio.fixture(scope="function")
async def auth_client(client: AsyncTestClient) -> AsyncTestClient:
    from services.auth import auth_service

    session_id = await auth_service.create_session("admin")
    csrf_token = auth_service.generate_csrf_token(session_id)

    client.cookies.set("session_id", session_id)
    client.cookies.set("csrf_token", csrf_token)
    client.headers["X-CSRF-Token"] = csrf_token

    return client


# === Mock Bot ===

@pytest.fixture
def mock_bot():
    bot = AsyncMock()
    bot.get_me = AsyncMock(return_value=MagicMock(
        id=123456789, username="test_bot", first_name="Test Bot",
    ))
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    bot.send_photo = AsyncMock(return_value=MagicMock(message_id=2))
    bot.send_video = AsyncMock(return_value=MagicMock(message_id=3))
    bot.send_audio = AsyncMock(return_value=MagicMock(message_id=4))
    bot.send_document = AsyncMock(return_value=MagicMock(message_id=5))
    bot.delete_message = AsyncMock(return_value=True)
    bot.session = AsyncMock()
    bot.session.close = AsyncMock()
    return bot


# === Model Factories (без изменений) ===

@pytest.fixture
def bot_factory():
    def _create(**kwargs):
        defaults = {
            "token": f"{fake.random_int(100000000, 999999999)}:{fake.hexify('*' * 35)}",
            "bot_id": fake.random_int(100000000, 999999999),
            "username": fake.user_name()[:32],
            "name": fake.name()[:64],
            "status": BotStatus.ACTIVE,
        }
        defaults.update(kwargs)
        return Bot(**defaults)
    return _create


@pytest.fixture
def user_factory():
    def _create(bot_id: int = 1, **kwargs):
        defaults = {
            "telegram_id": fake.random_int(100000000, 999999999),
            "bot_id": bot_id,
            "username": fake.user_name()[:32],
            "first_name": fake.first_name()[:64],
            "last_name": fake.last_name()[:64],
            "language": fake.random_element(["en", "ru"]),
            "is_blocked": False,
            "is_banned": False,
        }
        defaults.update(kwargs)
        return User(**defaults)
    return _create


@pytest.fixture
def ad_factory():
    def _create(**kwargs):
        defaults = {
            "name": fake.sentence(nb_words=3)[:64],
            "content": fake.text(max_nb_chars=200),
            "status": AdStatus.DRAFT,
            "is_active": True,
        }
        defaults.update(kwargs)
        return Ad(**defaults)
    return _create


@pytest.fixture
def media_factory():
    def _create(**kwargs):
        defaults = {
            "source": fake.random_element(list(MediaSource)),
            "original_url": fake.url(),
            "media_type": fake.random_element(list(MediaType)),
            "title": fake.sentence(nb_words=5),
        }
        defaults.update(kwargs)
        return Media(**defaults)
    return _create


@pytest.fixture
def download_factory():
    def _create(user_id: int = 1, bot_id: int = 1, **kwargs):
        defaults = {
            "user_id": user_id,
            "bot_id": bot_id,
            "original_url": fake.url(),
            "source": fake.random_element(list(MediaSource)),
        }
        defaults.update(kwargs)
        return Download(**defaults)
    return _create


@pytest.fixture
def sample_urls():
    return {
        "youtube": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "youtube_short": "https://youtu.be/dQw4w9WgXcQ",
        "youtube_shorts": "https://www.youtube.com/shorts/abc123",
        "instagram_post": "https://www.instagram.com/p/ABC123/",
        "instagram_reel": "https://www.instagram.com/reel/XYZ789/",
        "tiktok": "https://www.tiktok.com/@user/video/1234567890",
        "tiktok_short": "https://vm.tiktok.com/abc123/",
        "pinterest": "https://www.pinterest.com/pin/123456789/",
        "pinterest_short": "https://pin.it/abc123",
        "vk": "https://vk.com/video-123_456",
        "invalid": "https://example.com/not-supported",
    }
