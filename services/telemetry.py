"""System telemetry service — CPU, RAM, disk, network, GPU."""

import os
import time
from dataclasses import dataclass, field
from datetime import datetime

from app.logging import get_logger

log = get_logger("service.telemetry")

# Attempt to import optional GPU monitoring
try:
    import pynvml

    PYNVML_AVAILABLE = True
except ImportError:
    PYNVML_AVAILABLE = False


@dataclass
class CpuInfo:
    percent: float  # overall CPU usage %
    per_cpu: list[float]  # per-core usage %
    freq_current: float | None = None  # MHz
    freq_min: float | None = None
    freq_max: float | None = None
    load_avg_1: float | None = None
    load_avg_5: float | None = None
    load_avg_15: float | None = None
    cores_logical: int = 0
    cores_physical: int = 0


@dataclass
class MemoryInfo:
    total_gb: float
    available_gb: float
    used_gb: float
    percent: float
    swap_total_gb: float = 0.0
    swap_used_gb: float = 0.0
    swap_percent: float = 0.0


@dataclass
class DiskPartition:
    device: str
    mountpoint: str
    fstype: str
    total_gb: float
    used_gb: float
    free_gb: float
    percent: float


@dataclass
class DiskIO:
    read_bytes: int
    write_bytes: int
    read_count: int
    write_count: int
    read_rate: str = ""  # human-readable rate (updated on diff)
    write_rate: str = ""


@dataclass
class NetInterface:
    name: str
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int
    is_up: bool = True


@dataclass
class GpuInfo:
    index: int
    name: str
    memory_total_mb: int
    memory_used_mb: int
    memory_free_mb: int
    utilization_gpu: int  # %
    utilization_memory: int  # %
    temperature: int  # °C
    power_usage_w: float | None = None
    power_limit_w: float | None = None


@dataclass
class ProcessInfo:
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float
    memory_rss_mb: float
    status: str
    threads: int


@dataclass
class TelemetrySnapshot:
    timestamp: datetime
    cpu: CpuInfo
    memory: MemoryInfo
    disks: list[DiskPartition]
    disk_io: DiskIO
    network: list[NetInterface]
    gpus: list[GpuInfo]
    processes: list[ProcessInfo]
    uptime_seconds: float
    boot_time: datetime


def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _gb(n: int) -> float:
    return round(n / (1024**3), 2)


class TelemetryService:
    """Collects system telemetry using psutil (and optionally pynvml for GPU)."""

    def __init__(self) -> None:
        self._boot_time: datetime | None = None
        self._prev_disk_io: tuple[int, int, float] | None = None  # read, write, timestamp
        self._prev_disk_io_obj: DiskIO | None = None
        import psutil

        self._psutil = psutil

    # ── Public API ──────────────────────────────────────────────

    def get_snapshot(self) -> TelemetrySnapshot:
        """Take a full snapshot of current system state."""
        import psutil

        now = datetime.now()

        # Boot time (cached first call)
        if self._boot_time is None:
            self._boot_time = datetime.fromtimestamp(psutil.boot_time())
        boot_time = self._boot_time

        cpu = self._get_cpu_info()
        memory = self._get_memory_info()
        disks = self._get_disk_partitions()
        disk_io = self._get_disk_io()
        network = self._get_network()
        gpus = self._get_gpus()
        processes = self._get_top_processes()
        uptime = (now - boot_time).total_seconds()

        return TelemetrySnapshot(
            timestamp=now,
            cpu=cpu,
            memory=memory,
            disks=disks,
            disk_io=disk_io,
            network=network,
            gpus=gpus,
            processes=processes,
            uptime_seconds=uptime,
            boot_time=boot_time,
        )

    # ── Internal helpers ────────────────────────────────────────

    def _get_cpu_info(self) -> CpuInfo:
        ps = self._psutil
        info = CpuInfo(
            percent=ps.cpu_percent(interval=0.1),
            per_cpu=ps.cpu_percent(interval=0, percpu=True),
            cores_logical=ps.cpu_count(logical=True) or 0,
            cores_physical=ps.cpu_count(logical=False) or 0,
        )

        freq = ps.cpu_freq()
        if freq:
            info.freq_current = round(freq.current, 1)
            info.freq_min = round(freq.min, 1) if freq.min else None
            info.freq_max = round(freq.max, 1) if freq.max else None

        try:
            load = ps.getloadavg()
            info.load_avg_1 = round(load[0], 2)
            info.load_avg_5 = round(load[1], 2)
            info.load_avg_15 = round(load[2], 2)
        except (OSError, AttributeError):
            # Windows doesn't support getloadavg
            pass

        return info

    def _get_memory_info(self) -> MemoryInfo:
        ps = self._psutil
        vm = ps.virtual_memory()
        info = MemoryInfo(
            total_gb=_gb(vm.total),
            available_gb=_gb(vm.available),
            used_gb=_gb(vm.used),
            percent=vm.percent,
        )

        swap = ps.swap_memory()
        info.swap_total_gb = _gb(swap.total)
        info.swap_used_gb = _gb(swap.used)
        info.swap_percent = swap.percent

        return info

    def _get_disk_partitions(self) -> list[DiskPartition]:
        ps = self._psutil
        partitions: list[DiskPartition] = []
        seen = set()

        for part in ps.disk_partitions(all=False):
            if part.device in seen or not part.mountpoint:
                continue
            # Skip virtual / system partitions
            if part.fstype.lower() in ("squashfs", "tmpfs", "devtmpfs", "overlay"):
                continue
            seen.add(part.device)

            try:
                usage = ps.disk_usage(part.mountpoint)
                partitions.append(
                    DiskPartition(
                        device=part.device,
                        mountpoint=part.mountpoint,
                        fstype=part.fstype,
                        total_gb=_gb(usage.total),
                        used_gb=_gb(usage.used),
                        free_gb=_gb(usage.free),
                        percent=usage.percent,
                    )
                )
            except PermissionError:
                continue

        return partitions

    def _get_disk_io(self) -> DiskIO:
        ps = self._psutil
        now = time.time()
        counters = ps.disk_io_counters()

        if not counters:
            return DiskIO(read_bytes=0, write_bytes=0, read_count=0, write_count=0)

        read_bytes = counters.read_bytes
        write_bytes = counters.write_bytes
        read_count = counters.read_count
        write_count = counters.write_count

        io = DiskIO(
            read_bytes=read_bytes,
            write_bytes=write_bytes,
            read_count=read_count,
            write_count=write_count,
        )

        # Calculate rates if we have previous data
        if self._prev_disk_io is not None:
            prev_read, prev_write, prev_time = self._prev_disk_io
            elapsed = now - prev_time
            if elapsed > 0:
                read_rate = read_bytes - prev_read
                write_rate = write_bytes - prev_write
                io.read_rate = f"{_format_bytes(max(0, int(read_rate / elapsed)))}/s"
                io.write_rate = f"{_format_bytes(max(0, int(write_rate / elapsed)))}/s"

        self._prev_disk_io = (read_bytes, write_bytes, now)
        return io

    def _get_network(self) -> list[NetInterface]:
        ps = self._psutil
        interfaces: list[NetInterface] = []

        addrs = ps.net_if_addrs()
        stats = ps.net_if_stats()

        for name, counters in ps.net_io_counters(pernic=True).items():
            is_up = stats.get(name, None)
            interfaces.append(
                NetInterface(
                    name=name,
                    bytes_sent=counters.bytes_sent,
                    bytes_recv=counters.bytes_recv,
                    packets_sent=counters.packets_sent,
                    packets_recv=counters.packets_recv,
                    is_up=is_up.isup if is_up else False,
                )
            )

        return interfaces

    def _get_gpus(self) -> list[GpuInfo]:
        if not PYNVML_AVAILABLE:
            return []

        gpus: list[GpuInfo] = []
        try:
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            for i in range(count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)

                power_info: GpuInfo = GpuInfo(
                    index=i,
                    name=pynvml.nvmlDeviceGetName(handle),
                    memory_total_mb=mem.total // (1024 * 1024),
                    memory_used_mb=mem.used // (1024 * 1024),
                    memory_free_mb=mem.free // (1024 * 1024),
                    utilization_gpu=util.gpu,
                    utilization_memory=util.memory,
                    temperature=temp,
                )

                try:
                    power_usage = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # mW → W
                    power_limit = pynvml.nvmlDeviceGetPowerManagementLimit(handle) / 1000.0
                    power_info.power_usage_w = round(power_usage, 1)
                    power_info.power_limit_w = round(power_limit, 1)
                except pynvml.NVMLError:
                    pass

                gpus.append(power_info)
        except Exception as e:
            log.warning("Failed to get GPU info", error=str(e))

        return gpus

    def _get_top_processes(self, limit: int = 10) -> list[ProcessInfo]:
        ps = self._psutil
        processes: list[ProcessInfo] = []

        for proc in ps.process_iter(["pid", "name", "cpu_percent", "memory_percent", "memory_info", "status", "num_threads"]):
            try:
                info = proc.info
                rss_mb = info["memory_info"].rss / (1024 * 1024) if info["memory_info"] else 0
                processes.append(
                    ProcessInfo(
                        pid=info["pid"] or 0,
                        name=info["name"] or "unknown",
                        cpu_percent=info["cpu_percent"] or 0.0,
                        memory_percent=info["memory_percent"] or 0.0,
                        memory_rss_mb=round(rss_mb, 1),
                        status=info["status"] or "unknown",
                        threads=info["num_threads"] or 0,
                    )
                )
            except (ps.AccessDenied, ps.NoSuchProcess, ps.ZombieProcess):
                continue

        # Sort by CPU % descending, take top N
        processes.sort(key=lambda p: p.cpu_percent, reverse=True)
        return processes[:limit]

    @staticmethod
    def format_uptime(seconds: float) -> str:
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        return " ".join(parts)


# Singleton
telemetry = TelemetryService()
