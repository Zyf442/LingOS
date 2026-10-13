"""工具调用确认对话框（PRD 3.4、7.3：模态、置顶、完整展示、风险标签）。"""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

RISK_STYLES = {
    "low": ("低风险", "success"),
    "medium": ("中风险", "warning"),
    "high": ("高风险", "error"),
}

TOOL_NAMES_CN = {
    "shell": "执行终端命令",
    "file_read": "读取文件",
    "file_write": "写入文件",
    "file_delete": "删除文件（移入回收站）",
    "gsettings_set": "修改系统设置",
    "system_info": "读取系统信息",
}


class ConfirmDialog(Adw.Window):
    def __init__(
        self,
        transient_for,
        tool_call_id: str,
        tool_name: str,
        arguments: dict,
        risk: str,
        preview: str,
        on_decision: Callable[[str, str, bool], None],
        **kwargs,
    ) -> None:
        super().__init__(transient_for=transient_for, modal=True, **kwargs)
        self.tcid = tool_call_id
        self.on_decision = on_decision
        self.set_title("确认操作")
        self.set_default_size(560, 420)
        self.set_destroy_with_parent(True)

        risk_label, risk_css = RISK_STYLES.get(risk, ("未知风险", "warning"))
        title = f"AI 请求{TOOL_NAMES_CN.get(tool_name, tool_name)}"

        header = Adw.HeaderBar()

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=6, margin_bottom=12, margin_start=12, margin_end=12)

        # 标题 + 风险标签
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        t = Gtk.Label(label=title)
        t.add_css_class("heading")
        badge = Gtk.Label(label=risk_label)
        badge.add_css_class("pill")
        badge.add_css_class(risk_css)
        head.append(t)
        head.append(badge)
        box.append(head)

        # 预览内容（命令原文 / diff / 路径）
        frame = Gtk.Frame()
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_min_content_height(200)
        preview_label = Gtk.Label(label=preview, wrap=True, xalign=0,
                                  margin_top=8, margin_bottom=8,
                                  margin_start=8, margin_end=8)
        preview_label.get_style_context().add_provider(
            _mono_css(), Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        preview_label.add_css_class("mono")
        scrolled.set_child(preview_label)
        frame.set_child(scrolled)
        box.append(frame)

        if tool_name == "shell":
            box.append(Gtk.Label(
                label="请仔细检查上方命令。高风险命令（删除、覆盖、安装）执行后可能无法撤销。",
                xalign=0, wrap=True))

        # "本次全部允许"复选（仅文件类工具，PRD 7.2）
        self.batch_check = Gtk.CheckButton(label="本次会话中允许该工具在此目录下的后续操作")
        self.batch_check.set_visible(tool_name.startswith("file_"))
        box.append(self.batch_check)

        # 按钮：允许（destructive 当 high）/ 拒绝
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.END)
        deny = Gtk.Button(label="拒绝")
        deny.connect("clicked", lambda *_: self._decide("deny"))

        allow = Gtk.Button(label="允许")
        if risk == "high":
            allow.add_css_class("destructive-action")
        else:
            allow.add_css_class("suggested-action")
        allow.connect("clicked", lambda *_: self._decide(
            "allow_batch" if self.batch_check.get_active() else "allow"))
        btn_box.append(deny)
        btn_box.append(allow)
        box.append(btn_box)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.append(header)
        root.append(box)
        self.set_content(root)
        self.present()

    def _decide(self, decision: str) -> None:
        remember = self.batch_check.get_active()
        self.on_decision(self.tcid, decision, remember)
        self.close()
