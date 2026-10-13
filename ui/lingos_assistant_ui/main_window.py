"""主窗口：历史侧栏 + 聊天区 + 设置三视图（PRD 7.1）。

状态机（PRD 5.3）：加载中/失败/超时/空状态/无 Key/服务未就绪。
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .audit_page import AuditPage  # noqa: E402
from .client import AssistantClient  # noqa: E402
from .confirm_dialog import ConfirmDialog  # noqa: E402
from .quick_cards import QUICK_CARDS  # noqa: E402
from .settings_page import SettingsPage  # noqa: E402

BRAND_COLOR = "#4C6EF5"


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.set_title("LingOS 助手")
        self.set_default_size(1100, 720)

        self.client: AssistantClient | None = None
        self.current_cid: str | None = None
        self._pending_requests: dict[str, dict[str, Any]] = {}

        # ---- 外层：服务错误页 / 主界面 切换 ----
        self.stack = Gtk.Stack()
        self.set_content(self.stack)

        self.error_page = self._build_error_page()
        self.stack.add_named(self.error_page, "service-error")

        self.main_box = self._build_main_ui()
        self.stack.add_named(self.main_box, "main")
        self.stack.set_visible_child_name("service-error")

    # ================================================== 错误页（服务未就绪）
    def _build_error_page(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        icon = Gtk.Image.new_from_icon_name("dialog-error-symbolic")
        icon.set_pixel_size(64)
        label = Gtk.Label(label="助手服务启动失败")
        label.add_css_class("title-2")
        hint = Gtk.Label(label="请尝试重启系统或在终端运行\nsystemctl --user status lingos-assistantd 查看详情")
        hint.set_justify(Gtk.Justification.CENTER)
        box.append(icon)
        box.append(label)
        box.append(hint)
        return box

    def show_service_error(self) -> None:
        self.stack.set_visible_child_name("service-error")

    # ================================================== 主界面
    def _build_main_ui(self) -> Gtk.Box:
        # 顶栏
        header = Adw.HeaderBar()

        # 侧栏按钮（历史）
        history_btn = Gtk.ToggleButton(label="历史")
        history_btn.connect("toggled", self._on_toggle_history)

        settings_btn = Gtk.Button(icon_name="settings-symbolic")
        settings_btn.connect("clicked", lambda *_: self._open_settings())

        audit_btn = Gtk.Button(icon_name="document-open-recent-symbolic")
        audit_btn.connect("clicked", lambda *_: self._open_audit())

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header.pack_start(history_btn)
        header.pack_end(settings_btn)
        header.pack_end(audit_btn)
        box.append(header)

        # 分栏：侧栏 + 聊天
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, position=260)
        self.paned.set_shrink_start_child(False)
        box.append(Gtk.Separator())
        box.append(self.paned)

        # 侧栏（会话列表）
        self.sidebar = self._build_sidebar()
        self.paned.set_start_child(self.sidebar)

        # 聊天区
        self.chat_page = self._build_chat_page()
        self.paned.set_end_child(self.chat_page)

        return box

    # ---- 侧栏 ----
    def _build_sidebar(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        new_btn = Gtk.Button(label="新对话")
        new_btn.add_css_class("suggested-action")
        new_btn.connect("clicked", lambda *_: self.new_conversation())
        box.append(new_btn)

        # M11：会话搜索框
        self.search_entry = Gtk.SearchEntry(placeholder_text="搜索会话…")
        self.search_entry.connect("search-changed", lambda e: self._reload_conversations())
        self.search_entry.set_margin_top(6)
        self.search_entry.set_margin_bottom(6)
        box.append(self.search_entry)

        self.conv_list = Gtk.ListBox()
        self.conv_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.conv_list.connect("row-selected", self._on_conv_selected)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(self.conv_list)
        scrolled.set_vexpand(True)
        box.append(scrolled)
        return box

    # ---- 聊天区 ----
    def _build_chat_page(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # 消息滚动区
        self.messages_list = Gtk.ListBox()
        self.messages_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.messages_list.add_css_class("background")
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(self.messages_list)
        scroll.set_vexpand(True)
        box.append(scroll)

        # 空状态快捷卡片（PRD 5.3）
        self.empty_box = self._build_quick_cards()
        overlay = Gtk.Overlay()
        overlay.set_child(scroll)
        overlay.add_overlay(self.empty_box)
        # 简化：直接放卡片层，有消息后隐藏

        # 输入区
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.input = Gtk.TextView()
        self.input.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.input.set_pixels_above_lines(4)
        self.input.set_pixels_below_lines(4)
        self.input.set_height_request(60)
        self.input.get_buffer().connect("changed", self._on_input_changed)

        scroll_in = Gtk.ScrolledWindow()
        scroll_in.set_child(self.input)
        scroll_in.set_hexpand(True)

        self.send_btn = Gtk.Button(icon_name="document-send-symbolic")
        self.send_btn.set_sensitive(False)
        self.send_btn.connect("clicked", lambda *_: self._send())

        self.stop_btn = Gtk.Button(icon_name="process-stop-symbolic")
        self.stop_btn.set_visible(False)
        self.stop_btn.connect("clicked", lambda *_: self._cancel())

        input_box.append(scroll_in)
        input_box.append(self.stop_btn)
        input_box.append(self.send_btn)
        box.append(Gtk.Separator())
        box.append(input_box)

        # 无 Key 状态横幅（PRD 5.3：无 Key 整屏引导）
        self.no_key_banner = Adw.Banner(
            title="尚未配置 API Key，点击前往设置", button_label="去配置")
        self.no_key_banner.connect("button-clicked", lambda *_: self._open_settings())
        box.prepend(self.no_key_banner)

        return box

    def _build_quick_cards(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        title = Gtk.Label(label="我能帮你做什么？")
        title.add_css_class("title-3")
        box.append(title)
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(2)
        for label, prompt in QUICK_CARDS:
            btn = Gtk.Button(label=label)
            btn.connect("clicked", lambda b, p=prompt: self._fill_input(p))
            flow.insert(btn, -1)
        box.append(flow)
        return box

    # ================================================== 服务就绪
    def on_service_ready(self, client: AssistantClient) -> None:
        self.client = client
        self.stack.set_visible_child_name("main")
        client.start_events(self._on_ws_event)
        self._refresh_status()
        self._reload_conversations()
        if not self.current_cid:
            self.new_conversation()

    def _refresh_status(self) -> None:
        assert self.client is not None
        try:
            h = self.client.healthz()
        except Exception:  # noqa: BLE001
            return
        self.no_key_banner.set_revealed(not h.get("has_key", False))

    # ================================================== 会话
    def _reload_conversations(self) -> None:
        assert self.client is not None
        self.conv_list.remove_all()
        q = None
        if hasattr(self, "search_entry"):
            q = self.search_entry.get_text().strip() or None
        try:
            data = self.client.list_conversations(q=q)
        except Exception:  # noqa: BLE001
            return
        for conv in data.get("items", []):
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=conv["title"], halign=Gtk.Align.START, margin_start=8,
                              margin_top=4, margin_bottom=4)
            row.set_child(label)
            row.cid = conv["id"]
            self.conv_list.append(row)

    def new_conversation(self) -> None:
        assert self.client is not None
        conv = self.client.create_conversation()
        self.current_cid = conv["id"]
        self._clear_messages()
        self._reload_conversations()
        self._restore_draft()

    def _on_conv_selected(self, _box, row) -> None:
        if row is None or not self.client:
            return
        self.current_cid = row.cid
        self._clear_messages()
        try:
            data = self.client.list_messages(row.cid)
        except Exception:  # noqa: BLE001
            return
        for m in data.get("items", []):
            self._append_message(m.get("role", "user"), m.get("content", ""))
        self.empty_box.set_visible(not data.get("items"))
        self._restore_draft()

    # ================================================== 发送与流式渲染
    def _on_input_changed(self, buf) -> None:
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        self.send_btn.set_sensitive(bool(text.strip()))
        self.empty_box.set_visible(False)
        if self.current_cid and self.client:
            self.client.save_draft(self.current_cid, text)

    def _fill_input(self, prompt: str) -> None:
        buf = self.input.get_buffer()
        buf.set_text(prompt)
        self.input.grab_focus()

    def _restore_draft(self) -> None:
        if self.current_cid and self.client:
            draft = self.client.load_draft(self.current_cid)
            self.input.get_buffer().set_text(draft)

    def _send(self) -> None:
        if not (self.client and self.current_cid):
            return
        buf = self.input.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        if not text:
            return
        buf.set_text("")
        self.client.save_draft(self.current_cid, "")
        self._append_message("user", text)
        self.send_btn.set_sensitive(False)
        self.stop_btn.set_visible(True)
        # 打字指示气泡（PRD 5.3 加载中）
        self._typing_row = self._append_message("assistant", "…")
        try:
            self.client.send_message(self.current_cid, text)
        except Exception as e:  # noqa: BLE001
            self._remove_row(self._typing_row)
            self._append_error(f"发送失败：{e}（输入内容已保留）")
            buf.set_text(text)

    def _cancel(self) -> None:
        if self.client and self.current_cid:
            self.client.cancel(self.current_cid)

    def _on_ws_event(self, event: dict[str, Any]) -> None:
        etype = event.get("type")
        if etype == "message.delta":
            self._on_delta(event["message_id"], event.get("content_chunk", ""))
        elif etype == "message.done":
            self._on_message_done(event.get("message_id"), event.get("tokens"))
        elif etype == "message.error":
            self._on_message_error(event.get("message_id"), event.get("message", ""))
        elif etype == "tool_call.requested":
            self._on_tool_requested(event)
        elif etype == "status.changed":
            self._refresh_status()
            if self.client:
                self._reload_conversations()

    def _on_delta(self, message_id: str, chunk: str) -> None:
        """流式渲染：打字指示气泡就地更新内容。"""
        row = getattr(self, "_typing_row", None)
        if row is not None:
            label = row.get_child().get_first_child() if row.get_child() else None
            # 直接在气泡 label 上追加
            if row._bubble_label is not None:
                row._bubble_label.set_text(row._bubble_label.get_text().rstrip("…") + chunk)

    def _on_message_done(self, message_id, tokens) -> None:
        row = getattr(self, "_typing_row", None)
        if row is not None:
            row._spinner.stop() if hasattr(row, "_spinner") else None
        self.send_btn.set_sensitive(True)
        self.stop_btn.set_visible(False)
        self._typing_row = None

    def _on_message_error(self, message_id, message) -> None:
        row = getattr(self, "_typing_row", None)
        if row is not None and row._bubble_label:
            if row._bubble_label.get_text().strip() in ("…", ""):
                self._remove_row(row)
        self._append_error(message)
        self.send_btn.set_sensitive(True)
        self.stop_btn.set_visible(False)
        self._typing_row = None

    # ================================================== 工具确认流（PRD 3.4、7.3）
    def _on_tool_requested(self, event: dict[str, Any]) -> None:
        self._pending_requests[event["tool_call_id"]] = event
        ConfirmDialog(
            transient_for=self,
            tool_call_id=event["tool_call_id"],
            tool_name=event["tool_name"],
            arguments=event.get("arguments", {}),
            risk=event.get("risk", "low"),
            preview=event.get("preview", ""),
            on_decision=self._submit_decision,
        ).present()

    def _submit_decision(self, tcid: str, decision: str, remember: bool) -> None:
        if not self.client:
            return
        scope = None
        if decision == "allow_batch" and remember and tcid in self._pending_requests:
            ev = self._pending_requests[tcid]
            path = str(ev.get("arguments", {}).get("path", ""))
            if path:
                scope = f"{ev['tool_name']}:{path.rsplit('/', 1)[0]}"
        self.client.decide_tool_call(tcid, decision, scope)
        self._pending_requests.pop(tcid, None)

    # ================================================== 消息气泡
    def _clear_messages(self) -> None:
        self.messages_list.remove_all()
        self.empty_box.set_visible(True)

    def _append_message(self, role: str, content: str):
        row = Gtk.ListBoxRow(selectable=False)
        row._bubble_label = None
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                         margin_start=12, margin_end=12, margin_top=6, margin_bottom=6)
        label = Gtk.Label(label=content, wrap=True, xalign=0)
        label.add_css_class("lingos-bubble")
        label.add_css_class(f"lingos-{role}")
        row._bubble_label = label
        bubble.append(label)
        row.set_child(bubble)
        self.messages_list.append(row)
        GLib.idle_add(self._scroll_to_bottom)
        self.empty_box.set_visible(False)
        return row

    def _append_error(self, message: str) -> None:
        row = Gtk.ListBoxRow(selectable=False)
        label = Gtk.Label(label=f"生成失败：{message}", wrap=True, xalign=0)
        label.add_css_class("lingos-error")
        row.set_child(label)
        self.messages_list.append(row)

    def _remove_row(self, row) -> None:
        if row is not None:
            self.messages_list.remove(row)

    def _scroll_to_bottom(self) -> bool:
        # 让滚动区滚到底部
        parent = self.messages_list.get_parent()
        if parent:
            vadj = parent.get_vadjustment()
            vadj.set_value(vadj.get_upper())
        return False

    # ================================================== 其他视图
    def _on_toggle_history(self, btn) -> None:
        self.sidebar.set_visible(btn.get_active())

    def _open_settings(self) -> None:
        if self.client:
            win = SettingsPage(transient_for=self, client=self.client)
            win.present()

    def _open_audit(self) -> None:
        if self.client:
            win = AuditPage(transient_for=self, client=self.client)
            win.present()
