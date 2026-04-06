from litestar import Controller, get, post
from litestar.response import Template, Redirect
from litestar.di import Provide

from services.queue_monitor import queue_monitor, JobState
from services.metrics import metrics
from app.middleware.auth import admin_guard
from app.logging import get_logger

log = get_logger("controller.queues")


class QueueController(Controller):
    path = "/admin/queues"
    guards = [admin_guard]

    @get("/", name="queues:dashboard")
    async def dashboard(self) -> Template:
        """Queue Dashboard"""
        # Статистика
        stats = await queue_monitor.get_queue_stats()

        # Последние jobs
        recent_jobs = await queue_monitor.get_recent_jobs(limit=20)

        # Failed jobs
        failed_jobs = await queue_monitor.get_failed_jobs(limit=10)

        # Workers
        workers = await queue_monitor.get_workers_status()

        # Active broadcasts
        broadcasts = await queue_monitor.get_active_broadcasts()

        return Template(
            template_name="admin/queues/dashboard.html",
            context={
                "stats": stats,
                "recent_jobs": recent_jobs,
                "failed_jobs": failed_jobs,
                "workers": workers,
                "broadcasts": broadcasts,
                "JobState": JobState,
            }
        )

    @get("/jobs", name="queues:jobs")
    async def jobs_list(
        self,
        status: str = "all",
        page: int = 1,
        per_page: int = 20,
    ) -> Template:
        """Список jobs"""
        offset = (page - 1) * per_page

        if status == "pending":
            jobs = await queue_monitor.get_pending_jobs(limit=per_page)
        elif status == "running":
            jobs = await queue_monitor.get_running_jobs()
        elif status == "failed":
            jobs = await queue_monitor.get_failed_jobs(limit=per_page)
        else:
            jobs = await queue_monitor.get_recent_jobs(limit=per_page)

        return Template(
            template_name="admin/queues/jobs.html",
            context={
                "jobs": jobs,
                "status_filter": status,
                "page": page,
                "per_page": per_page,
                "JobState": JobState,
            }
        )

    @get("/jobs/{job_id:str}", name="queues:job_detail")
    async def job_detail(self, job_id: str) -> Template:
        """Детали job"""
        job = await queue_monitor.get_job_info(job_id)

        return Template(
            template_name="admin/queues/job_detail.html",
            context={"job": job, "JobState": JobState}
        )

    @post("/jobs/{job_id:str}/retry", name="queues:retry_job")
    async def retry_job(self, job_id: str) -> Redirect:
        """Retry job"""
        success = await queue_monitor.retry_job(job_id)

        if success:
            return Redirect(path="/admin/queues?message=Job retried")
        else:
            return Redirect(path=f"/admin/queues?error=Failed to retry job")

    @post("/jobs/{job_id:str}/delete", name="queues:delete_job")
    async def delete_job(self, job_id: str) -> Redirect:
        """Delete job"""
        success = await queue_monitor.delete_job(job_id)

        if success:
            return Redirect(path="/admin/queues?message=Job deleted")
        else:
            return Redirect(path=f"/admin/queues?error=Failed to delete job")

    @post("/retry-all-failed", name="queues:retry_all_failed")
    async def retry_all_failed(self) -> Redirect:
        """Retry all failed jobs"""
        count = await queue_monitor.retry_all_failed()
        return Redirect(path=f"/admin/queues?message=Retried {count} jobs")

    @post("/clear-failed", name="queues:clear_failed")
    async def clear_failed(self) -> Redirect:
        """Clear all failed jobs"""
        count = await queue_monitor.clear_failed()
        return Redirect(path=f"/admin/queues?message=Cleared {count} jobs")

    @get("/broadcasts", name="queues:broadcasts")
    async def broadcasts(self) -> Template:
        """Active broadcasts"""
        broadcasts = await queue_monitor.get_active_broadcasts()

        return Template(
            template_name="admin/queues/broadcasts.html",
            context={"broadcasts": broadcasts}
        )
