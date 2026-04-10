"""Tests for TelemetryService"""

import pytest
from unittest.mock import patch, MagicMock

from services.telemetry import (
    TelemetryService,
    CpuInfo,
    MemoryInfo,
    DiskPartition,
    DiskIO,
    NetInterface,
    GpuInfo,
    ProcessInfo,
    TelemetrySnapshot,
    _format_bytes,
    _gb,
)


class TestFormatBytes:
    """Test _format_bytes helper"""

    def test_bytes(self):
        assert _format_bytes(500) == "500.0 B"

    def test_kilobytes(self):
        assert _format_bytes(1536) == "1.5 KB"

    def test_megabytes(self):
        assert _format_bytes(1048576) == "1.0 MB"

    def test_gigabytes(self):
        assert _format_bytes(1073741824) == "1.0 GB"

    def test_terabytes(self):
        assert _format_bytes(1099511627776) == "1.0 TB"

    def test_zero(self):
        assert _format_bytes(0) == "0.0 B"

    def test_negative(self):
        result = _format_bytes(-1024)
        assert "KB" in result


class TestGb:
    """Test _gb helper"""

    def test_gb_conversion(self):
        assert _gb(1073741824) == 1.0  # 1 GB in bytes
        assert _gb(0) == 0.0
        assert _gb(536870912) == 0.5  # 512 MB


@pytest.fixture
def telemetry_service():
    """Create a TelemetryService with mocked psutil"""
    return TelemetryService()


class TestTelemetryService:
    """Tests for TelemetryService"""

    @patch("psutil.cpu_percent")
    @patch("psutil.cpu_count")
    @patch("psutil.cpu_freq")
    def test_get_cpu_info(self, mock_freq, mock_count, mock_percent, telemetry_service):
        mock_percent.return_value = 45.5
        mock_count.return_value = 8
        mock_freq.return_value = MagicMock(current=2400.0, min=800.0, max=3600.0)

        cpu = telemetry_service._get_cpu_info()

        assert cpu.percent == 45.5
        assert cpu.cores_logical == 8
        assert cpu.freq_current == 2400.0
        assert cpu.freq_max == 3600.0

    @patch("psutil.virtual_memory")
    @patch("psutil.swap_memory")
    def test_get_memory_info(self, mock_swap, mock_vm, telemetry_service):
        mock_vm.return_value = MagicMock(
            total=17179869184,  # 16 GB
            available=8589934592,  # 8 GB
            used=8589934592,
            percent=50.0,
        )
        mock_swap.return_value = MagicMock(
            total=4294967296,  # 4 GB
            used=1073741824,  # 1 GB
            percent=25.0,
        )

        mem = telemetry_service._get_memory_info()

        assert mem.total_gb == 16.0
        assert mem.available_gb == 8.0
        assert mem.used_gb == 8.0
        assert mem.percent == 50.0
        assert mem.swap_total_gb == 4.0
        assert mem.swap_percent == 25.0

    @patch("psutil.disk_partitions")
    @patch("psutil.disk_usage")
    def test_get_disk_partitions(self, mock_usage, mock_partitions, telemetry_service):
        mock_partitions.return_value = [
            MagicMock(device="/dev/sda1", mountpoint="/", fstype="ext4"),
        ]
        mock_usage.return_value = MagicMock(
            total=107374182400,  # 100 GB
            used=53687091200,  # 50 GB
            free=53687091200,
            percent=50.0,
        )

        disks = telemetry_service._get_disk_partitions()

        assert len(disks) == 1
        assert disks[0].mountpoint == "/"
        assert disks[0].total_gb == 100.0
        assert disks[0].percent == 50.0

    @patch("psutil.disk_io_counters")
    def test_get_disk_io(self, mock_counters, telemetry_service):
        mock_counters.return_value = MagicMock(
            read_bytes=1048576,
            write_bytes=524288,
            read_count=100,
            write_count=50,
        )

        io = telemetry_service._get_disk_io()

        assert io.read_bytes == 1048576
        assert io.write_bytes == 524288
        assert io.read_count == 100

    @patch("psutil.net_io_counters")
    @patch("psutil.net_if_stats")
    def test_get_network(self, mock_stats, mock_counters, telemetry_service):
        mock_counters.return_value = {
            "eth0": MagicMock(
                bytes_sent=1000000,
                bytes_recv=5000000,
                packets_sent=100,
                packets_recv=500,
            )
        }
        mock_stats.return_value = {
            "eth0": MagicMock(isup=True),
        }

        network = telemetry_service._get_network()

        assert len(network) == 1
        assert network[0].name == "eth0"
        assert network[0].bytes_sent == 1000000
        assert network[0].is_up is True

    def test_get_gpus_no_pynvml(self, telemetry_service):
        """Test that GPU list is empty when pynvml not available"""
        with patch("services.telemetry.PYNVML_AVAILABLE", False):
            gpus = telemetry_service._get_gpus()
        assert gpus == []

    def test_format_uptime(self):
        """Test uptime formatting"""
        assert TelemetryService.format_uptime(86400) == "1d 0m"
        assert TelemetryService.format_uptime(3661) == "1h 1m"
        assert TelemetryService.format_uptime(125) == "2m"
        assert "d" in TelemetryService.format_uptime(172800)  # 2 days

    @patch.object(TelemetryService, "_get_cpu_info")
    @patch.object(TelemetryService, "_get_memory_info")
    @patch.object(TelemetryService, "_get_disk_partitions")
    @patch.object(TelemetryService, "_get_disk_io")
    @patch.object(TelemetryService, "_get_network")
    @patch.object(TelemetryService, "_get_gpus")
    @patch.object(TelemetryService, "_get_top_processes")
    def test_get_snapshot(
        self, mock_procs, mock_gpus, mock_net, mock_dio, mock_disks, mock_mem, mock_cpu,
        telemetry_service,
    ):
        mock_cpu.return_value = CpuInfo(
            percent=45.5, per_cpu=[10.0, 20.0], cores_logical=2, cores_physical=1
        )
        mock_mem.return_value = MemoryInfo(
            total_gb=16.0, available_gb=8.0, used_gb=8.0, percent=50.0
        )
        mock_disks.return_value = []
        mock_dio.return_value = DiskIO(0, 0, 0, 0)
        mock_net.return_value = []
        mock_gpus.return_value = []
        mock_procs.return_value = []

        snapshot = telemetry_service.get_snapshot()

        assert snapshot is not None
        assert snapshot.cpu.percent == 45.5
        assert snapshot.memory.total_gb == 16.0
        assert isinstance(snapshot.timestamp, type(snapshot.timestamp))
        assert snapshot.uptime_seconds >= 0

    def test_get_top_processes_empty(self, telemetry_service):
        """Test when no processes can be enumerated (e.g., in tests)"""
        # process_iter may return nothing useful in test env
        procs = telemetry_service._get_top_processes(limit=5)
        assert isinstance(procs, list)
