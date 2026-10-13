"""lingos-assistant-ui —— GTK4 + libadwaita 桌面应用（PRD 5.3、7.1）。

运行环境：Ubuntu 24.04（python3-gi + gir1.2-gtk-4.0 + gir1.2-adw-1，系统包，禁止 pip 装 PyGObject）。
启动：python -m lingos_assistant_ui.app
"""

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib  # noqa: E402

from .main_window import MainWindow  # noqa: E402
from .client import AssistantClient, ServiceUnavailable  # noqa: E402

APP_ID = "com.lingos.assistant"
RUNTIME_DIR = GLib.get_user_runtime_dir()
TOKEN_PATH = f"{RUNTIME_DIR}/lingos/assistant.token"
PORT_PATH = f"{RUNTIME_DIR}/lingos/port"
CONNECT_TIMEOUT_MS = 10_000  # 服务未就绪重试 500ms × 20 次（PRD 2.4）
RETRY_INTERVAL_MS = 500


class LingOSApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.client: AssistantClient | None = None
        self.window: MainWindow | None = None

    def do_activate(self) -> None:  # noqa: N802
        if self.window is None:
            self.window = MainWindow(application=self)
        self.window.present()
        self._connect_with_retry()

    def _connect_with_retry(self, attempts: int = 0) -> None:
        """UI → assistantd 就绪重试：每 500ms 一次，最多 10s 后错误页（PRD 2.4）。"""
        try:
            self.client = AssistantClient.discover(TOKEN_PATH, PORT_PATH)
            if self.window is not None:
                self.window.on_service_ready(self.client)
        except ServiceUnavailable:
            if attempts * RETRY_INTERVAL_MS >= CONNECT_TIMEOUT_MS:
                if self.window is not None:
                    self.window.show_service_error()
                return
            GLib.timeout_add(RETRY_INTERVAL_MS, self._connect_with_retry, attempts + 1)


def main() -> int:
    app = LingOSApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
