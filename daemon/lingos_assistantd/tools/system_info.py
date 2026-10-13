"""system_info 工具（PRD 5.4：只读，自动放行；结果缓存 TTL 600s，PRD 9.3）。"""

from __future__ import annotations

import platform
import shutil
import time
from pathlib import Path
from typing import Any

CACHE_TTL = 600.0


class SystemInfo:
    def __init__(self) -> None:
        self._cache: dict[str, Any] | None = None
        self._cached_at: float = 0.0

    def summary(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._cache is not None and now - self._cached_at < CACHE_TTL:
            return self._cache
        info = {
            "os": _os_release_name(),
            "kernel": platform.release(),
            "arch": platform.machine(),
            "python": platform.python_version(),
            "cpu": _cpu_info(),
            "memory": _memory_info(),
            "disk": _disk_info(Path.home()),
            "hostname": platform.node(),
        }
        self._cache = info
        self._cached_at = now
        return info

    def text_summary(self) -> str:
        i = self.summary()
        mem = i.get("memory") or {}
        disk = i.get("disk") or {}
        return (
            f"{i.get('os', 'Linux')} / 内核 {i.get('kernel')} / {i.get('arch')}；"
            f"CPU: {i.get('cpu', {}).get('model', '未知')}；"
            f"内存: 可用 {mem.get('available_gb', '?')}G / 共 {mem.get('total_gb', '?')}G；"
            f"家目录磁盘: 可用 {disk.get('free_gb', '?')}G / 共 {disk.get('total_gb', '?')}G"
        )


def _os_release_name() -> str:
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip('"')
    except OSError:
        pass
    return f"{platform.system()} {platform.release()}"


def _cpu_info() -> dict[str, Any]:
    info: dict[str, Any] = {"model": platform.processor() or "未知", "cores": os_cpu_count()}
    try:
        lines = Path("/proc/cpuinfo").read_text().splitlines()
        for line in lines:
            if line.startswith("model name"):
                info["model"] = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return info


def os_cpu_count() -> int:
    return __import__("os").cpu_count() or 1


def _memory_info() -> dict[str, Any]:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                total_gb = round(int(line.split()[1]) / 1024 / 1024, 1)
            if line.startswith("MemAvailable:"):
                avail_gb = round(int(line.split()[1]) / 1024 / 1024, 1)
        return {"total_gb": total_gb, "available_gb": avail_gb}
    except (OSError, UnboundLocalError):
        return {}


def _disk_info(path: Path) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
        return {
            "total_gb": round(usage.total / 1024**3, 1),
            "free_gb": round(usage.free / 1024**3, 1),
        }
    except OSError:
        return {}
