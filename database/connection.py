import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from typing import Self

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from app.config import settings
from app.logging import get_logger

log = get_logger("database")


class Database:

    _instance: Self | None = None
    _engine: AsyncEngine | None = None
    _session_factory: async_sessionmaker[AsyncSession] | None = None
    _loop: asyncio.AbstractEventLoop | None = None

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._session_factory

    async def connect(self) -> None:
        """Создание подключения к БД"""
        current_loop = asyncio.get_running_loop()
        if self._engine is not None:
            if self._loop == current_loop:
                log.warning("Database already connected")
                return
            log.warning("Loop changed, reconnecting database")
            await self.disconnect()

        self._loop = current_loop
        log.info("Connecting to database...", url=str(settings.database_url).split("@")[-1])
        db_url = str(settings.database_url)
        is_sqlite = db_url.startswith("sqlite")
        is_memory = is_sqlite and ":memory:" in db_url

        from sqlalchemy.pool import StaticPool
        if is_memory:
            pool_class = StaticPool
        else:
            pool_class = NullPool if (settings.debug or is_sqlite) else AsyncAdaptedQueuePool
        engine_kwargs = dict(echo=settings.database_echo,poolclass=pool_class)

        if not is_sqlite and pool_class is not NullPool and hasattr(pool_class, '__name__') and pool_class.__name__ != 'StaticPool':
            engine_kwargs.update(pool_size=settings.database_pool_size,max_overflow=20,pool_pre_ping=True,pool_recycle=3600)  # ty:ignore[invalid-argument-type]
        self._engine = create_async_engine(db_url, **engine_kwargs)
        self._session_factory = async_sessionmaker(self._engine,class_=AsyncSession,expire_on_commit=False,autoflush=False)

        try:
            async with self._engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            log.success("Database connected successfully")
        except Exception as e:
            log.exception("Failed to connect to database", error=str(e))
            raise

    async def disconnect(self) -> None:
        """Закрытие подключения"""
        if self._engine is None:
            return
        log.info("Disconnecting from database...")

        with suppress(Exception):
            await self._engine.dispose()
        self._engine = None
        self._session_factory = None
        self._loop = None
        log.info("Database disconnected")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        if self._session_factory is None:
            await self.connect()
        session = self._session_factory()  # ty:ignore[call-non-callable]

        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            log.error("Session rollback", error=str(e))
            raise
        finally:
            await session.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.session() as session, session.begin():
            yield session


db = Database()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency injection для контроллеров"""
    async with db.session() as session:
        yield session
