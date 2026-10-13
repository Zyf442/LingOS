"""lingos-assistantd 入口（PRD 2.4、5.2、13.3）。

启动顺序：
  初始化日志 → 打开 SQLite（迁移/损坏自愈）→ 重启恢复（stale tool_calls 置 failed）
  → 生成会话 token（写入 $XDG_RUNTIME_DIR/lingos/assistant.token, 0600）
  → 端口绑定 47831，被占用 +1 递增至 47841（实际端口写 port 文件）
  → uvicorn 启动

全部端口被占用 → 退出码 78（systemd 配置 EX_CONFIG，桌面通知由 unit 的 OnFailure 触发）。
"""

from __future__ import annotations

import logging
import secrets
import socket
import sys

import uvicorn

from . import __version__
from .api.app import AppContext, create_app
from .config import DaemonSettings
from .events import EventBus
from .keyring_service import build_keyring
from .logging_setup import setup_logging
from .service.chat_service import ChatService
from .storage import repos
from .storage.db import Database
from .tools.executor_tool import ToolExecutor

log = logging.getLogger("lingos.main")

EXIT_CONFIG_ERROR = 78


def find_free_port(settings: DaemonSettings) -> int | None:
    """47831 起逐个尝试绑定，成功即占用（预绑定避免竞态）。返回 None 表示全部被占用。"""
    for port in range(settings.port, settings.port_max + 1):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((settings.host, port))
            s.close()
            return port
        except OSError:
            continue
    return None


def build_context(settings: DaemonSettings, token: str) -> AppContext:
    db = Database(settings.db_file())
    db.open()
    if getattr(db, "corrupt_backup", None):
        log.error("检测到数据库损坏并已重建，备份位于 %s", db.corrupt_backup)

    keyring = build_keyring(settings.env, settings.dev_keyring, settings.dev_api_key)
    bus = EventBus()
    executor = ToolExecutor(settings)
    chat = ChatService(
        db=db,
        executor=executor,
        bus=bus,
        keyring=keyring,
        settings_getter=lambda: repos.get_settings(db.conn),
    )
    chat.recover_after_restart()
    return AppContext(db=db, chat=chat, bus=bus, keyring=keyring, token=token)


def write_runtime_files(settings: DaemonSettings, token: str, port: int) -> None:
    rdir = settings.runtime_dir()
    rdir.mkdir(parents=True, exist_ok=True)
    token_file = settings.token_file()
    token_file.write_text(token, encoding="utf-8")
    try:

        token_file.chmod(0o600)  # Windows 上忽略
    except OSError:
        pass
    settings.port_file().write_text(str(port), encoding="utf-8")


def main() -> None:
    settings = DaemonSettings()
    setup_logging(settings.log_level, structured=True)
    log.info("lingos-assistantd v%s 启动（env=%s）", __version__, settings.env)

    token = secrets.token_urlsafe(32)  # 256bit 会话 token（PRD 3.2）

    port = find_free_port(settings)
    if port is None:
        log.error(
            "端口 %d-%d 全部被占用，退出（码 %d）",
            settings.port,
            settings.port_max,
            EXIT_CONFIG_ERROR,
        )
        sys.exit(EXIT_CONFIG_ERROR)

    ctx = build_context(settings, token)
    write_runtime_files(settings, token, port)
    log.info("监听 http://%s:%d（token 已写入 %s）", settings.host, port, settings.token_file())

    app = create_app(ctx)
    uvicorn.run(
        app,
        host=settings.host,
        port=port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
