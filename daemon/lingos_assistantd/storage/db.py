"""SQLite 连接/WAL/迁移执行器（PRD 4.1、5.2、14.1）。

- WAL 模式 + foreign_keys=ON
- 内置 schema_version 表 + 启动时顺序执行 migrations/NNN_*.sql
- 损坏（integrity_check 失败）→ 改名 .corrupt-<ts> 备份、新建空库
"""

from __future__ import annotations

import logging
import sqlite3
from importlib import resources
from pathlib import Path

from ..times import utc_now_iso

log = logging.getLogger("lingos.db")


class DatabaseCorruptError(RuntimeError):
    pass


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.conn: sqlite3.Connection | None = None

    # ---------- 生命周期 ----------
    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._open_conn()
            self._integrity_check()
        except sqlite3.DatabaseError as e:
            # 损坏（含"file is not a database"等打开期错误）→ 隔离重建（PRD 5.2）
            if self.conn is not None:
                try:
                    self.conn.close()
                except sqlite3.Error:
                    pass
                self.conn = None
            self._quarantine_and_rebuild(e)
        self._run_migrations()

    def _open_conn(self) -> None:
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=10.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA synchronous=NORMAL")

    def _integrity_check(self) -> None:
        assert self.conn is not None
        row = self.conn.execute("PRAGMA integrity_check").fetchone()
        if row is None or row[0] != "ok":
            raise sqlite3.DatabaseError(f"integrity_check: {row[0] if row else 'unknown'}")

    def _quarantine_and_rebuild(self, cause: Exception | None = None) -> None:
        """PRD 5.2：坏库改名 .corrupt-<ts> 备份、新建空库、通知用户（由上层负责通知）。"""
        backup = self.path.with_name(f"{self.path.name}.corrupt-{utc_now_iso().replace(':', '')}")
        self.path.rename(backup)
        # WAL/SHM 侧车文件一并移走
        for suffix in ("-wal", "-shm"):
            side = self.path.with_name(self.path.name + suffix)
            if side.exists():
                side.rename(backup.with_name(backup.name + suffix))
        log.error("数据库损坏（%s），已备份到 %s 并重建空库", cause, backup)
        self._open_conn()
        self.corrupt_backup = backup

    def _run_migrations(self) -> None:
        assert self.conn is not None
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            " version INTEGER PRIMARY KEY,"
            " applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
        )
        applied = {r[0] for r in self.conn.execute("SELECT version FROM schema_version")}
        for name, sql in _load_migrations():
            version = int(name.split("_", 1)[0])
            if version in applied:
                continue
            with self.conn:
                self.conn.executescript(sql)
                self.conn.execute("INSERT INTO schema_version(version) VALUES (?)", (version,))
            log.info("已应用迁移 %s", name)

    # ---------- 便捷方法 ----------
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        assert self.conn is not None
        return self.conn.execute(sql, params)

    def commit(self) -> None:
        assert self.conn is not None
        self.conn.commit()

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None


def _load_migrations() -> list[tuple[str, str]]:
    """按文件名顺序加载打包内的 migrations/NNN_*.sql。"""
    out: list[tuple[str, str]] = []
    files = resources.files("lingos_assistantd.storage").joinpath("migrations").iterdir()
    for f in sorted(files, key=lambda f: f.name):
        if f.name.endswith(".sql"):
            out.append((f.name, f.read_text(encoding="utf-8")))
    return out
