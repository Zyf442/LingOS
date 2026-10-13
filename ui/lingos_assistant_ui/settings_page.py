"""设置页（PRD 5.5、7.1）：提供商与 Key、模型、温度、工具开关、主题。"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

PROVIDERS = {
    "dashscope": ("通义千问 DashScope", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "openai": ("OpenAI", "https://api.openai.com/v1"),
    "custom": ("自定义 OpenAI 兼容端点", ""),
}
MODELS = ["qwen-plus", "qwen-max", "qwen-turbo", "gpt-4o-mini"]


class SettingsPage(Adw.Window):
    def __init__(self, transient_for, client, **kwargs) -> None:
        super().__init__(transient_for=transient_for, modal=True, **kwargs)
        self.client = client
        self.set_title("助手设置")
        self.set_default_size(520, 560)
        self.set_destroy_with_parent(True)

        header = Adw.HeaderBar()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_start=16, margin_end=16, margin_top=8, margin_bottom=16)

        group = Adw.PreferencesGroup(title="AI 服务")
        # 提供商
        self.provider_row = Adw.ComboRow(title="提供商")
        provider_model = Gtk.StringList()
        for cn, _ in PROVIDERS.values():
            provider_model.append(cn)
        self.provider_row.set_model(provider_model)
        self.provider_row.connect("notify::selected", lambda *_: self._on_provider_changed())
        group.add(self.provider_row)

        # Base URL（custom 时可编辑）
        self.base_url_row = Adw.EntryRow(title="Base URL（OpenAI 兼容）")
        group.add(self.base_url_row)

        # API Key
        self.key_row = Adw.PasswordEntryRow(title="API Key（写入系统密钥环）")
        group.add(self.key_row)

        key_btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        save_btn = Gtk.Button(label="保存 Key")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", lambda *_: self._save_key())
        test_btn = Gtk.Button(label="测试连通性")
        test_btn.connect("clicked", lambda *_: self._test_key())
        del_btn = Gtk.Button(label="删除 Key")
        del_btn.add_css_class("destructive-action")
        del_btn.connect("clicked", lambda *_: self._delete_key())
        key_btns.append(save_btn)
        key_btns.append(test_btn)
        key_btns.append(del_btn)
        group.add(Adw.ActionRow(child=key_btns, title=""))

        self.key_status = Gtk.Label(xalign=0)
        group.add(Adw.ActionRow(child=self.key_status, title="Key 状态"))

        # 模型
        self.model_row = Adw.ComboRow(title="模型")
        model_list = Gtk.StringList()
        for m in MODELS:
            model_list.append(m)
        self.model_row.set_model(model_list)
        group.add(self.model_row)

        # 温度
        self.temp_row = Adw.SpinRow(title="温度（temperature）", adjustment=Gtk.Adjustment(
            value=0.7, lower=0, upper=2, step_increment=0.1))
        group.add(self.temp_row)

        # 上下文窗口
        self.ctx_row = Adw.SpinRow(title="上下文窗口（token 估算）", adjustment=Gtk.Adjustment(
            value=30000, lower=4000, upper=200000, step_increment=1000))
        group.add(self.ctx_row)

        box.append(group)

        group2 = Adw.PreferencesGroup(title="助手行为")
        self.tools_row = Adw.ToggleRow(title="启用工具能力（shell/文件/设置）",
                                       subtitle="关闭后 AI 仅能对话")
        group2.add(self.tools_row)

        self.theme_row = Adw.ComboRow(title="界面主题")
        theme_list = Gtk.StringList()
        for t in ("跟随系统", "浅色", "深色"):
            theme_list.append(t)
        self.theme_row.set_model(theme_list)
        group2.add(self.theme_row)
        box.append(group2)

        hint = Gtk.Label(
            label="全局快捷键 Super+L 可随时唤起快捷面板（可在系统设置-键盘中改绑）。\n"
                  "对话内容将发送至你所配置的 AI 服务商。",
            xalign=0, wrap=True)
        hint.add_css_class("dim-label")
        box.append(hint)

        scrolled = Gtk.ScrolledWindow()
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(header)
        content.append(box)
        scrolled.set_child(content)
        scrolled.set_vexpand(True)
        self.set_content(scrolled)

        self._load()

    # ---------------------------------------------------------------- 载入
    def _load(self) -> None:
        try:
            s = self.client.get_settings()
        except Exception as e:  # noqa: BLE001
            self.key_status.set_text(f"读取设置失败：{e}")
            return
        provider = s.get("provider", "dashscope")
        idx = list(PROVIDERS).index(provider) if provider in PROVIDERS else 0
        self.provider_row.set_selected(idx)
        self.base_url_row.set_text(s.get("base_url", ""))
        self.base_url_row.set_editable(provider == "custom")
        model = s.get("model", "qwen-plus")
        for i, m in enumerate(MODELS):
            if m == model:
                self.model_row.set_selected(i)
        self.temp_row.set_value(float(s.get("temperature", 0.7)))
        self.ctx_row.set_value(float(s.get("context_window", 30000)))
        self.tools_row.set_active(bool(s.get("tools_enabled", 1)))
        self.theme_row.set_selected({"system": 0, "light": 1, "dark": 2}.get(s.get("theme"), 0))
        self.key_status.set_text("已配置 Key ✓" if s.get("has_key") else "未配置 Key")
        # 运行时可调项变更即保存（PRD 19）
        self.model_row.connect("notify::selected", lambda *_: self._save_runtime())
        self.temp_row.connect("notify::value", lambda *_: self._save_runtime())
        self.ctx_row.connect("notify::value", lambda *_: self._save_runtime())
        self.tools_row.connect("notify::active", lambda *_: self._save_runtime())
        self.theme_row.connect("notify::selected", lambda *_: self._save_runtime())

    def _on_provider_changed(self) -> None:
        idx = self.provider_row.get_selected()
        name = list(PROVIDERS)[idx]
        self.base_url_row.set_editable(name == "custom")
        if PROVIDERS[name][1]:
            self.base_url_row.set_text(PROVIDERS[name][1])

    # ---------------------------------------------------------------- 保存
    def _save_runtime(self) -> None:
        patch = {
            "model": MODELS[self.model_row.get_selected()],
            "temperature": self.temp_row.get_value(),
            "context_window": int(self.ctx_row.get_value()),
            "tools_enabled": self.tools_row.get_active(),
            "theme": ["system", "light", "dark"][self.theme_row.get_selected()],
        }
        provider = list(PROVIDERS)[self.provider_row.get_selected()]
        patch["provider"] = provider
        patch["base_url"] = self.base_url_row.get_text() or PROVIDERS[provider][1]
        try:
            self.client.update_settings(patch)
        except Exception as e:  # noqa: BLE001
            self.key_status.set_text(f"保存失败：{e}")

    def _save_key(self) -> None:
        key = self.key_row.get_text().strip()
        if not key:
            self.key_status.set_text("请先粘贴 API Key")
            return
        provider = list(PROVIDERS)[self.provider_row.get_selected()]
        try:
            self.client.write_api_key(provider, key)
            self.key_row.set_text("")
            self.key_status.set_text("已保存到系统密钥环 ✓")
        except Exception as e:  # noqa: BLE001
            self.key_status.set_text(f"保存失败：{e}")

    def _test_key(self) -> None:
        self.key_status.set_text("测试中…")

        def run() -> None:
            try:
                result = self.client.test_api_key()
            except Exception as e:  # noqa: BLE001
                result = {"ok": False, "error": str(e)}
            GLib.idle_add(lambda: self.key_status.set_text(
                "连通性测试通过 ✓" if result.get("ok")
                else f"测试失败：{result.get('error', '未知错误')}"))

        import threading

        threading.Thread(target=run, daemon=True).start()

    def _delete_key(self) -> None:
        try:
            self.client.delete_api_key()
            self.key_status.set_text("已删除 Key")
        except Exception as e:  # noqa: BLE001
            self.key_status.set_text(f"删除失败：{e}")
