from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from litestar import Litestar
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.static_files import create_static_files_router
from litestar.template import TemplateConfig

from app.config import settings
from app.logging import setup_logging, get_logger

if TYPE_CHECKING:
    pass

# Логирование настраивается один раз — при явном вызове setup_logging() из main.py,
# а не на уровне модуля. Здесь только получаем logger.
log = get_logger("app")

# ---------------------------------------------------------------------------
# Webhook coordination via Redis lock (replaces fragile /tmp file approach)
# ---------------------------------------------------------------------------

_WEBHOOK_LOCK_KEY = "mediaflow:webhook_setup_lock"
_WEBHOOK_LOCK_TTL = 60  # seconds


async def _acquire_webhook_lock() -> bool:
    """
    Try to acquire a distributed Redis lock.
    Returns True if this process is the one that should set webhooks.
    """
    from services import cache  # local import to avoid circular deps

    acquired = await cache.set_nx(_WEBHOOK_LOCK_KEY, str(os.getpid()), ttl=_WEBHOOK_LOCK_TTL)
    return bool(acquired)


async def _setup_webhooks_once() -> dict:
    """
    Set webhooks exactly once across all Granian workers using a Redis lock.
    If another worker already holds the lock — skip silently.
    """
    from services import bot_manager

    pid = os.getpid()

    if not await _acquire_webhook_lock():
        log.info("Webhooks already set by another worker, skipping", pid=pid)
        return {"skipped": True, "pid": pid}

    log.info("This worker acquired webhook lock, setting webhooks", pid=pid)
    try:
        result = await bot_manager.setup_all_webhooks(settings.webhook_base_url)
        log.info("Webhooks configured", result=result, pid=pid)
        return result
    except Exception:
        log.exception("Failed to set webhooks", pid=pid)
        raise


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: Litestar):
    """Application lifecycle — startup → yield → shutdown."""
    from database.connection import db
    from services import cache, bot_manager, queue_service
    from services.rate_limiter import rate_limiter
    from workers.scheduler import scheduler

    log.info("Starting MediaFlow...", pid=os.getpid(), debug=settings.debug)

    # --- Startup ---
    try:
        await db.connect()
        log.debug("Database connected")

        await cache.connect()
        log.debug("Cache connected")

        await rate_limiter.start()
        await bot_manager.setup()
        await queue_service.start()
        await scheduler.start()

        if settings.webhook_base_url:
            results = await _setup_webhooks_once()
            log.info("Webhook setup done", results=results)

    except Exception:
        log.exception("Startup failed — shutting down")
        raise

    log.info("MediaFlow started successfully")
    yield

    # --- Shutdown (reverse order) ---
    log.info("Shutting down MediaFlow...")

    await scheduler.stop()
    await queue_service.stop()
    await bot_manager.shutdown()
    await rate_limiter.stop()
    await cache.disconnect()
    await db.disconnect()

    log.info("MediaFlow stopped cleanly")


# ---------------------------------------------------------------------------
# Jinja2 helpers
# ---------------------------------------------------------------------------


def _format_bytes(n: int | float) -> str:
    """Human-readable byte size: 1048576 → '1.0 MB'."""
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024.0:
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} PB"


def _get_now(*_args, **_kwargs) -> datetime:
    return datetime.now()


def _setup_jinja2(engine) -> None:
    """Register custom Jinja2 filters and globals."""
    engine.register_template_callable("now", _get_now)
    engine.engine.filters["format_bytes"] = _format_bytes


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(lifespan_handlers: list | None = None) -> Litestar:
    from app.controllers import (
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
        TelemetryController,
        SubscriptionController,
    )
    from app.controllers.cache_channels import CacheChannelWebController
    from app.middleware.rate_limit import RateLimitMiddleware
    from app.middleware.auth import AuthMiddleware

    # Use provided lifespan_handlers (for tests) or default
    lifespan_to_use = lifespan_handlers if lifespan_handlers is not None else [lifespan]

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
            TelemetryController,
            SubscriptionController,
            CacheChannelWebController,
            create_static_files_router(path="/static", directories=["static"]),
        ],
        template_config=TemplateConfig(
            engine=JinjaTemplateEngine,
            directory=Path("resources"),
            engine_callback=_setup_jinja2,
        ),
        middleware=[
            RateLimitMiddleware,
            AuthMiddleware,
        ],
        lifespan=lifespan_to_use,
        debug=settings.debug,
    )


app = create_app()
