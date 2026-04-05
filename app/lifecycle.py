from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from litestar import Litestar
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.static_files import create_static_files_router
from litestar.template import TemplateConfig

from src.config import settings
from src.logging import setup_logging, get_logger
from src.database.connection import db
from src.services import cache, bot_manager, queue_service
from src.services.rate_limiter import rate_limiter
from src.workers.scheduler import scheduler
from src.web.middleware.rate_limit import RateLimitMiddleware
from src.web.middleware.auth import AuthMiddleware
from src.web.controllers import (
    AdminController,
    AuthController,
    BotController,
    AdController,
    StatsController,
    QueueController,
    WebhookController,
    HealthController,
    IndexController,
    UserController,
)

setup_logging()
log = get_logger("app")


@asynccontextmanager
async def lifespan(app: Litestar):
    """Application lifecycle"""
    log.info("Starting application...")

    await db.connect()
    await cache.connect()
    await rate_limiter.start()
    await bot_manager.setup()
    await queue_service.start()
    await scheduler.start()

    if settings.webhook_base_url:
        results = await bot_manager.setup_all_webhooks(settings.webhook_base_url)
        log.info("Webhooks setup", results=results)

    log.info("Application started successfully")
    yield

    log.info("Shutting down application...")
    await scheduler.stop()
    await queue_service.stop()
    await bot_manager.shutdown()
    await rate_limiter.stop()
    await cache.disconnect()
    await db.disconnect()
    log.info("Application stopped")


def _get_now(*args, **kwargs) -> datetime:
    return datetime.now()


def create_app(lifespan_handlers=None) -> Litestar:       # ← Добавь параметр
    return Litestar(
        route_handlers=[
            AdminController,
            AuthController,
            BotController,
            AdController,
            StatsController,
            WebhookController,
            QueueController,
            HealthController,
            IndexController,
            UserController,
            create_static_files_router(path="/static", directories=["static"]),
        ],
        template_config=TemplateConfig(
            engine=JinjaTemplateEngine,
            directory=Path("src/web/templates"),
            engine_callback=lambda engine: engine.register_template_callable("now", _get_now),
        ),
        middleware=[
            RateLimitMiddleware,
            AuthMiddleware,
        ],
        lifespan=lifespan_handlers if lifespan_handlers is not None else [lifespan],  # ← Тут
        debug=settings.debug,
    )



app = create_app()
