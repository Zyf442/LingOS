"""executor/trash.py —— FreeDesktop Trash 规范回收站（PRD 5.4：永不真删）。

规范要点：
- 回收站目录：$XDG_DATA_HOME/Trash（即 ~/.local/share/Trash）
- files/ 放被删文件；info/ 放同名 .trashinfo（INI: [Trash Info] Path=… DeletionDate=…）
- 重名冲突时追加后缀 .2、.3 …
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote
from urllib.request import url2pathname


class TrashError(RuntimeError):
    pass


class Trash:
    def __init__(self, data_home: Path | None = None):
        base = data_home or _default_data_home()
        self.files_dir = base / "Trash" / "files"
        self.info_dir = base / "Trash" / "info"
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.info_dir.mkdir(parents=True, exist_ok=True)

    def trash(self, path: str | Path) -> Path:
        """把文件/目录移入回收站，返回回收站内的新路径。"""
        src = Path(os.path.expanduser(str(path))).resolve()
        if not src.exists():
            raise TrashError(f"文件不存在: {src}")
        # 禁止把回收站自身或家目录整体丢进去
        if self.files_dir == src or self.files_dir in src.parents:
            raise TrashError("不能删除回收站自身")

        dest = self._unique_target(self.files_dir / src.name)
        os.rename(src, dest)  # 同一文件系统内移动
        self._write_info(dest, src)
        return dest

    def _unique_target(self, target: Path) -> Path:
        if not target.exists():
            return target
        for i in range(2, 10000):
            cand = target.with_name(f"{target.name}.{i}")
            if not cand.exists():
                return cand
        raise TrashError("回收站重名冲突无法解决")

    def _write_info(self, dest: Path, original: Path) -> None:
        deletion_date = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S")
        info = self.info_dir / f"{dest.name}.trashinfo"
        # Path 值按规范进行百分号编码（保留 /）
        content = (
            "[Trash Info]\n"
            f"Path={quote(str(original), safe='/')}\n"
            f"DeletionDate={deletion_date}\n"
        )
        info.write_text(content, encoding="utf-8")


def _default_data_home() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".local" / "share"


def restore_path_from_info(info_file: Path) -> Path | None:
    """从 .trashinfo 读出原始路径（审计/展示用）。"""
    if not info_file.exists():
        return None
    for line in info_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("Path="):
            return Path(url2pathname(unquote(line[5:])))
    return None
