from asyncio import to_thread
from litestar import Controller, get
from litestar.response import Template, Response

from services.telemetry import telemetry
from app.middleware.auth import admin_guard
from app.logging import get_logger

log = get_logger("controller.telemetry")


class TelemetryController(Controller):
    path = "/admin/telemetry"
    guards = [admin_guard]

    @get("/", name="telemetry:overview")
    async def overview(self) -> Template:
        """System telemetry page"""
        snapshot = await to_thread(telemetry.get_snapshot)
        return Template(
            template_name="admin/telemetry.html",
            context={
                "snapshot": snapshot,
                "uptime_str": telemetry.format_uptime(snapshot.uptime_seconds),
                "format_bytes": lambda n: _format_bytes(n),
                "pynvml_available": snapshot.gpus and len(snapshot.gpus) > 0,
            },
        )

    @get("/api/snapshot", name="telemetry:api_snapshot")
    async def api_snapshot(self) -> Response:
        """API: return current telemetry snapshot as JSON"""
        snap = await to_thread(telemetry.get_snapshot)
        data = {
            "timestamp": snap.timestamp.isoformat(),
            "uptime": telemetry.format_uptime(snap.uptime_seconds),
            "cpu": {
                "percent": snap.cpu.percent,
                "per_cpu": snap.cpu.per_cpu,
                "freq_current": snap.cpu.freq_current,
                "freq_max": snap.cpu.freq_max,
                "load_avg_1": snap.cpu.load_avg_1,
                "load_avg_5": snap.cpu.load_avg_5,
                "load_avg_15": snap.cpu.load_avg_15,
                "cores_logical": snap.cpu.cores_logical,
                "cores_physical": snap.cpu.cores_physical,
            },
            "memory": {
                "total_gb": snap.memory.total_gb,
                "available_gb": snap.memory.available_gb,
                "used_gb": snap.memory.used_gb,
                "percent": snap.memory.percent,
                "swap_total_gb": snap.memory.swap_total_gb,
                "swap_used_gb": snap.memory.swap_used_gb,
                "swap_percent": snap.memory.swap_percent,
            },
            "disks": [
                {
                    "device": d.device,
                    "mountpoint": d.mountpoint,
                    "fstype": d.fstype,
                    "total_gb": d.total_gb,
                    "used_gb": d.used_gb,
                    "free_gb": d.free_gb,
                    "percent": d.percent,
                }
                for d in snap.disks
            ],
            "disk_io": {
                "read_rate": snap.disk_io.read_rate,
                "write_rate": snap.disk_io.write_rate,
                "read_count": snap.disk_io.read_count,
                "write_count": snap.disk_io.write_count,
            },
            "network": [
                {
                    "name": n.name,
                    "bytes_sent": n.bytes_sent,
                    "bytes_recv": n.bytes_recv,
                    "packets_sent": n.packets_sent,
                    "packets_recv": n.packets_recv,
                    "is_up": n.is_up,
                }
                for n in snap.network
            ],
            "gpus": [
                {
                    "index": g.index,
                    "name": g.name,
                    "memory_total_mb": g.memory_total_mb,
                    "memory_used_mb": g.memory_used_mb,
                    "memory_free_mb": g.memory_free_mb,
                    "utilization_gpu": g.utilization_gpu,
                    "utilization_memory": g.utilization_memory,
                    "temperature": g.temperature,
                    "power_usage_w": g.power_usage_w,
                    "power_limit_w": g.power_limit_w,
                }
                for g in snap.gpus
            ],
            "top_processes": [
                {
                    "pid": p.pid,
                    "name": p.name,
                    "cpu_percent": p.cpu_percent,
                    "memory_percent": p.memory_percent,
                    "memory_rss_mb": p.memory_rss_mb,
                    "status": p.status,
                    "threads": p.threads,
                }
                for p in snap.processes
            ],
        }
        return Response(content=data)


def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
