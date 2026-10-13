"""OOBE 首次开机引导（PRD 5.1 M12、7.2）：欢迎与时区 → 配置 API Key（可跳过）→ 试用对话。"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402


class OobeWindow(Adw.ApplicationWindow):
    def __init__(self, client_factory, on_finish, **kwargs) -> None:
        super().__init__(**kwargs)
        self.client_factory = client_factory  # () -> AssistantClient | None
        self.on_finish = on_finish
        self.set_title("欢迎使用 LingOS")
        self.set_default_size(640, 480)

        self.carousel = Adw.Carousel()
        self.carousel.set_interactive(False)

        self.carousel.append(self._page_welcome())
        self.carousel.append(self._page_api_key())
        self.carousel.append(self._page_try())

        dots = Adw.CarouselIndicatorDots()
        dots.set_carousel(self.carousel)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(Gtk.Label())  # 顶部留白
        box.append(self.carousel)
        box.append(dots)
        self.set_content(box)

    # ---------------------------------------------------------------- 第 1 页
    def _page_welcome(self) -> Gtk.Box:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                       valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        title = Gtk.Label(label="欢迎使用 LingOS")
        title.add_css_class("title-1")
        subtitle = Gtk.Label(label="AI 原生的 Linux 桌面\n让助手帮你操作这台电脑",
                             justify=Gtk.Justification.CENTER)
        privacy = Gtk.Label(
            label="对话内容将发送至你配置的 AI 服务商（默认阿里云百炼）；\n"
                  "不配置 API Key 则不会有任何数据出网。审计日志仅保存在本机。",
            justify=Gtk.Justification.CENTER)
        privacy.add_css_class("dim-label")
        next_btn = Gtk.Button(label="开始配置")
        next_btn.add_css_class("suggested-action")
        next_btn.connect("clicked", lambda *_: self._goto(1))
        page.append(title)
        page.append(subtitle)
        page.append(privacy)
        page.append(next_btn)
        return page

    # ---------------------------------------------------------------- 第 2 页
    def _page_api_key(self) -> Gtk.Box:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                       valign=Gtk.Align.CENTER, margin_start=48, margin_end=48)
        title = Gtk.Label(label="配置你的 API Key")
        title.add_css_class("title-2")
        hint = Gtk.Label(label="前往 dashscope.console.aliyun.com 创建 Key（sk- 开头）",
                         xalign=0)
        self.key_entry = Adw.PasswordEntryRow(title="DashScope API Key")
        self.provider_row = Adw.ComboRow(title="提供商")
        from .settings_page import PROVIDERS
        provider_model = Gtk.StringList()
        for cn, _ in PROVIDERS.values():
            provider_model.append(cn)
        self.provider_row.set_model(provider_model)

        self.status = Gtk.Label(xalign=0)
        save_btn = Gtk.Button(label="保存并测试")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", lambda *_: self._save_and_test())
        skip_btn = Gtk.Button(label="跳过（稍后在设置中配置）")
        skip_btn.connect("clicked", lambda *_: self._goto(2))

        page.append(title)
        page.append(hint)
        page.append(self.key_entry)
        page.append(self.status)
        page.append(save_btn)
        page.append(skip_btn)
        return page

    def _save_and_test(self) -> None:
        client = self.client_factory()
        if client is None:
            self.status.set_text("助手服务未就绪，请稍后重试")
            return
        key = self.key_entry.get_text().strip()
        if not key:
            self.status.set_text("请先粘贴 API Key")
            return
        from .settings_page import PROVIDERS
        provider = list(PROVIDERS)[self.provider_row.get_selected()]
        try:
            client.write_api_key(provider, key)
            result = client.test_api_key()
        except Exception as e:  # noqa: BLE001
            result = {"ok": False, "error": str(e)}
        if result.get("ok"):
            self.status.set_text("连通性测试通过 ✓")
            self._goto(2)
        else:
            self.status.set_text(f"测试失败：{result.get('error', '未知错误')}")

    # ---------------------------------------------------------------- 第 3 页
    def _page_try(self) -> Gtk.Box:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                       valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        title = Gtk.Label(label="一切就绪！")
        title.add_css_class("title-2")
        hint = Gtk.Label(label="试试让助手"开启深色模式"，或按 Super+L 随时唤起。\n"
                              "所有危险操作都会先向你确认。", justify=Gtk.Justification.CENTER)
        from .quick_cards import QUICK_CARDS
        btn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for label, prompt in QUICK_CARDS[:2]:
            b = Gtk.Button(label=f"试一试：{label}")
            b.connect("clicked", lambda _b, p=prompt: self._try_prompt(p))
            btn_box.append(b)
        finish = Gtk.Button(label="完成")
        finish.add_css_class("suggested-action")
        finish.connect("clicked", lambda *_: self._finish())

        page.append(title)
        page.append(hint)
        page.append(btn_box)
        page.append(finish)
        return page

    def _try_prompt(self, prompt: str) -> None:
        self._finish(prompt)

    # ---------------------------------------------------------------- 工具
    def _goto(self, index: int) -> None:
        self.carousel.scroll_to(self.carousel.get_nth_page(index), animate=True)

    def _finish(self, prompt: str | None = None) -> None:
        self.close()
        if self.on_finish:
            self.on_finish(prompt)
