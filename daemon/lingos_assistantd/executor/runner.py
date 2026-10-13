"""executor/runner.py —— 命令隔离执行（PRD 5.4）。

- 生产：systemd-run --user --scope -p MemoryMax=1G -p CPUQuota=100% --pty
- 开发（LINGOS_NO_SYSTEMD=1）：subprocess + 独立进程组 fallback
- 超时 kill 进程组（os.killpg）
- stdout/stderr 各截断 8KB
"""

from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass
from typing import Any

MAX_OUTPUT_BYTES = 8 * 1024
DEFAULT_TIMEOUT_SEC = 30
MAX_TIMEOUT_SEC = 120

SYSTEMD_CMD_PREFIX = [
    "systemd-run",
    "--user",
    "--scope",
    "-p",
    "MemoryMax=1G",
    "-p",
    "CPUQuota=100%",
    "--quiet",
    "--pipe",
]


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
        }


def _truncate(data: bytes) -> str:
    text = data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    if len(data) > MAX_OUTPUT_BYTES:
        text += "\n…（输出已截断至 8KB）"
    return text


class Runner:
    """命令执行器。测试中可注入 FakeRunner 替身（PRD 11.4）。"""

    def __init__(self, no_systemd: bool = False):
        self.no_systemd = no_systemd
        self._current_proc: asyncio.subprocess.Process | None = None

    async def run(
        self,
        command: str,
        workdir: str | None = None,
        timeout_sec: int | None = None,
    ) -> ExecResult:
        timeout = min(max(1, timeout_sec or DEFAULT_TIMEOUT_SEC), MAX_TIMEOUT_SEC)
        args = self._build_argv(command)
        started = asyncio.get_event_loop().time()
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=workdir or None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,  # 独立进程组，超时可整组 kill
        )
        self._current_proc = proc
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            timed_out = False
        except asyncio.TimeoutError:
            self.kill_running()
            stdout, stderr = await proc.communicate()
            timed_out = True
        finally:
            self._current_proc = None
        duration_ms = int((asyncio.get_event_loop().time() - started) * 1000)
        code = -signal.SIGKILL if timed_out else (proc.returncode or 0)
        return ExecResult(
            exit_code=code,
            stdout=_truncate(stdout or b""),
            stderr=_truncate(stderr or b"") + ("\n（超时，已终止）" if timed_out else ""),
            duration_ms=duration_ms,
            timed_out=timed_out,
        )

    def kill_running(self) -> None:
        """取消/超时流程调用：kill 当前执行中的子进程组（os.killpg，PRD 5.4）。"""
        proc = self._current_proc
        if proc is None or proc.returncode is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    def _build_argv(self, command: str) -> list[str]:
        if self.no_systemd:
            # 开发模式：bash/sh 直接执行（PRD 11.5 容器内无 systemd user session）
            shell = "bash" if _has("bash") else "sh"
            return [shell, "-c", command]
        return [*SYSTEMD_CMD_PREFIX, "bash", "-c", command]


def _has(cmd: str) -> bool:
    from shutil import which

    return which(cmd) is not None
