"""工具执行器：guard 决策通过后真正执行 5+1 个工具（PRD 5.4）。

- shell：Runner（systemd-run 隔离 / dev 直跑）
- file_read：≤256KB 文本
- file_write：自动备份到 ~/.local/share/lingos/backups/（保留最近 50 个）
- file_delete：Trash（FreeDesktop，永不真删）
- system_info：SystemInfo 缓存
- gsettings_set：子进程 gsettings set（键已在 guard 白名单校验）
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..config import DaemonSettings
from ..executor.runner import Runner
from ..executor.trash import Trash, TrashError
from .system_info import SystemInfo

MAX_READ_BYTES = 256 * 1024
MAX_BACKUPS = 50


class ToolExecutionError(RuntimeError):
    pass


class ToolExecutor:
    def __init__(
        self,
        settings: DaemonSettings,
        runner: Runner | None = None,
        trash: Trash | None = None,
        system_info: SystemInfo | None = None,
    ):
        self.settings = settings
        self.runner = runner or Runner(no_systemd=settings.no_systemd)
        self.trash = trash or Trash(settings.data_dir())
        self.system_info = system_info or SystemInfo()

    async def execute(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool == "shell":
            r = await self.runner.run(
                args["command"],
                workdir=args.get("workdir"),
                timeout_sec=args.get("timeout_sec"),
            )
            return r.to_dict()
        if tool == "file_read":
            return self._file_read(args["path"])
        if tool == "file_write":
            return self._file_write(args["path"], args["content"])
        if tool == "file_delete":
            return self._file_delete(args["path"])
        if tool == "system_info":
            return self.system_info.summary()
        if tool == "gsettings_set":
            return self._gsettings_set(args["schema"], args["key"], args["value"])
        raise ToolExecutionError(f"unknown tool: {tool}")

    # ------------------------------------------------ file_read
    def _file_read(self, path: str) -> dict[str, Any]:
        p = Path(os.path.expanduser(path))
        if not p.is_file():
            raise ToolExecutionError(f"文件不存在或不是普通文件: {p}")
        size = p.stat().st_size
        if size > MAX_READ_BYTES:
            raise ToolExecutionError(f"文件超过 256KB 上限（{size} 字节）: {p}")
        try:
            text = p.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError as e:
            raise ToolExecutionError(f"非 UTF-8 文本文件: {p}") from e
        return {"path": str(p), "size": size, "content": text}

    # ------------------------------------------------ file_write（自动备份）
    def _file_write(self, path: str, content: str) -> dict[str, Any]:
        p = Path(os.path.expanduser(path))
        p.parent.mkdir(parents=True, exist_ok=True)
        backup_path: str | None = None
        if p.exists():
            backup_path = str(self._backup(p))
        p.write_text(content, encoding="utf-8")
        return {"path": str(p), "bytes": len(content.encode("utf-8")), "backup": backup_path}

    def _backup(self, p: Path) -> Path:
        bdir = self.settings.backups_dir()
        bdir.mkdir(parents=True, exist_ok=True)
        ts = __import__("time").strftime("%Y%m%d-%H%M%S")
        dest = bdir / f"{p.name}.{ts}.bak"
        i = 1
        while dest.exists():
            dest = bdir / f"{p.name}.{ts}.{i}.bak"
            i += 1
        shutil.copy2(p, dest)
        self._prune_backups(bdir)
        return dest

    def _prune_backups(self, bdir: Path) -> None:
        backups = sorted(bdir.glob("*.bak"), key=lambda f: f.stat().st_mtime, reverse=True)
        for old in backups[MAX_BACKUPS:]:
            old.unlink(missing_ok=True)

    # ------------------------------------------------ file_delete（回收站）
    def _file_delete(self, path: str) -> dict[str, Any]:
        try:
            dest = self.trash.trash(path)
        except TrashError as e:
            raise ToolExecutionError(str(e)) from e
        return {"path": path, "trashed_to": str(dest), "really_deleted": False}

    # ------------------------------------------------ gsettings_set
    def _gsettings_set(self, schema: str, key: str, value: str) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                ["gsettings", "set", schema, key, value],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except FileNotFoundError as e:
            raise ToolExecutionError("gsettings 命令不可用（非 GNOME 环境？）") from e
        if proc.returncode != 0:
            raise ToolExecutionError(f"gsettings 失败: {proc.stderr.strip()}")
        return {"schema": schema, "key": key, "value": value}
