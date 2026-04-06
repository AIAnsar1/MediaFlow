from datetime import date, timedelta
from litestar import Controller, get
from litestar.response import Template, Response
from litestar.di import Provide
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database.connection import get_session
from services.metrics import metrics
from services.queue_monitor import queue_monitor
from repositories import BotRepository, UserRepository, MediaRepository
from models import Download, Media, MediaSource, DailyStats
from middleware.auth import admin_guard
from logging import get_logger

log = get_logger("controller.stats")


class StatsController(Controller):
    path = "/admin/stats"
    guards = [admin_guard]
    dependencies = {"session": Provide(get_session)}

    @get("/", name="stats:overview")
    async def overview(self, session: AsyncSession) -> Template:
        """Statistics overview with charts"""
        bot_repo = BotRepository(session)
        user_repo = UserRepository(session)
        media_repo = MediaRepository(session)

        # Основные метрики
        total_bots = await bot_repo.count()
        total_users = await user_repo.count()
        total_media = await media_repo.count()

        # Real-time метрики
        dashboard_stats = await metrics.get_dashboard_stats()

        # Статистика по платформам (из БД для точности)
        source_stats = await media_repo.get_stats_by_source()

        # Языки пользователей
        language_stats = await user_repo.get_language_stats()

        # Hourly data для графика
        hourly_stats = await metrics.get_hourly_stats(hours=24)

        # Daily data (последние 7 дней)
        daily_stats = await self._get_daily_stats(session, days=7)

        return Template(
            template_name="admin/stats/overview.html",
            context={
                "total_bots": total_bots,
                "total_users": total_users,
                "total_media": total_media,
                "dashboard_stats": dashboard_stats,
                "source_stats": source_stats,
                "language_stats": language_stats,
                "hourly_stats": hourly_stats,
                "daily_stats": daily_stats,
            }
        )

    @get("/downloads", name="stats:downloads")
    async def download_stats(
        self,
        session: AsyncSession,
        days: int = 30,
    ) -> Template:
        """Download statistics"""
        # По платформам
        platform_stats = {}
        for source in MediaSource:
            count = await session.execute(
                select(func.count()).select_from(Download).where(
                    Download.source == source
                )
            )
            platform_stats[source.value] = count.scalar() or 0

        # Топ медиа
        top_media = await session.execute(
            select(Media)
            .order_by(Media.download_count.desc())
            .limit(10)
        )

        # Daily downloads
        daily = await self._get_daily_downloads(session, days)

        return Template(
            template_name="admin/stats/downloads.html",
            context={
                "platform_stats": platform_stats,
                "top_media": top_media.scalars().all(),
                "daily_downloads": daily,
                "days": days,
            }
        )

    @get("/api/chart-data", name="stats:chart_data")
    async def chart_data(
        self,
        session: AsyncSession,
        metric: str = "downloads",
        period: str = "24h",
    ) -> Response:
        """API endpoint for chart data"""
        if period == "24h":
            hours = 24
        elif period == "7d":
            hours = 168
        else:
            hours = 24

        if metric == "downloads":
            data = await metrics.get_hourly_stats(hours=hours)
            return Response(content={
                "labels": [d["hour"] for d in data],
                "datasets": [{
                    "label": "Downloads",
                    "data": [d["downloads"] for d in data],
                    "borderColor": "#3b82f6",
                    "backgroundColor": "rgba(59, 130, 246, 0.1)",
                }]
            })

        elif metric == "errors":
            data = await metrics.get_hourly_stats(hours=hours)
            return Response(content={
                "labels": [d["hour"] for d in data],
                "datasets": [{
                    "label": "Errors",
                    "data": [d["errors"] for d in data],
                    "borderColor": "#ef4444",
                    "backgroundColor": "rgba(239, 68, 68, 0.1)",
                }]
            })

        elif metric == "platforms":
            stats = await metrics.get_dashboard_stats()
            return Response(content={
                "labels": list(stats["by_platform"].keys()),
                "datasets": [{
                    "data": list(stats["by_platform"].values()),
                    "backgroundColor": [
                        "#ef4444",  # YouTube - red
                        "#ec4899",  # Instagram - pink
                        "#000000",  # TikTok - black
                        "#dc2626",  # Pinterest - red
                        "#3b82f6",  # VK - blue
                    ],
                }]
            })

        return Response(content={"error": "Unknown metric"}, status_code=400)

    async def _get_daily_stats(self, session: AsyncSession, days: int) -> list[dict]:
        """Get daily aggregated stats"""
        result = []
        today = date.today()

        for i in range(days):
            day = today - timedelta(days=i)

            # Downloads
            downloads = await session.execute(
                select(func.count()).select_from(Download).where(
                    func.date(Download.created_at) == day
                )
            )

            result.append({
                "date": day.isoformat(),
                "downloads": downloads.scalar() or 0,
            })

        return list(reversed(result))

    async def _get_daily_downloads(self, session: AsyncSession, days: int) -> list[dict]:
        """Get daily downloads by platform"""
        result = []
        today = date.today()

        for i in range(days):
            day = today - timedelta(days=i)
            day_data = {"date": day.isoformat()}

            for source in MediaSource:
                count = await session.execute(
                    select(func.count()).select_from(Download).where(
                        func.date(Download.created_at) == day,
                        Download.source == source,
                    )
                )
                day_data[source.value] = count.scalar() or 0

            result.append(day_data)

        return list(reversed(result))
