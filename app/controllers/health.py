from litestar import Controller, get
from litestar.response import Response

from src.database.connection import db
from src.services import cache


class HealthController(Controller):
    path = "/health"

    @get("/", name="health:check")
    async def health_check(self) -> Response:
        """Health check endpoint"""
        status = {
            "status": "healthy",
            "database": False,
            "cache": False,
        }

        try:
            async with db.session() as session:
                await session.execute("SELECT 1")
                status["database"] = True
        except:
            status["status"] = "unhealthy"

        try:
            await cache.redis.ping()
            status["cache"] = True
        except:
            status["status"] = "unhealthy"

        status_code = 200 if status["status"] == "healthy" else 503

        return Response(content=status, status_code=status_code)

    @get("/ready", name="health:ready")
    async def readiness_check(self) -> Response:
        """Readiness check"""
        return Response(content={"ready": True}, status_code=200)

    @get("/live", name="health:live")
    async def liveness_check(self) -> Response:
        """Liveness check"""
        return Response(content={"live": True}, status_code=200)
