"""快捷面板（PRD 5.3）：Super+L 唤起的悬浮聊天面板（600×720，单会话）。"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from .main_window import MainWindow  # noqa: E402


class QuickPanel(Adw.Window):
    """悬浮面板版助手：与主窗口共用一个 client 与事件处理逻辑。"""

    def __init__(self, main: MainWindow, **kwargs) -> None:
        super().__init__(**kwargs)
        self.main = main
        self.set_title("LingOS 助手")
        self.set_default_size(600, 720)
        self.set_hide_on_close(True)  # 预热面板不销毁（PRD 9.2 UI 唤起 ≤1.5s）
        self.connect("notify::visible", self._on_visibility)

        header = Adw.HeaderBar(show_title_buttons=True)
        expand_btn = Gtk.Button(icon_name="window-new-symbolic",
                                tooltip_text="打开完整窗口")
        expand_btn.connect("clicked", lambda *_: self._open_full())
        header.pack_start(expand_btn)

        # 复用主窗口的聊天组件树（单会话：不显示侧栏）
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(header)
        box.append(Gtk.Separator())

        chat = self.main._build_chat_page()
        chat.set_vexpand(True)
        box.append(chat)
        self.set_content(box)

    def _open_full(self) -> None:
        self.main.present()
        self.set_visible(False)

    def _on_visibility(self, *_args) -> None:
        if self.get_visible() and self.main.client:
            if not self.main.current_cid:
                self.main.new_conversation()
