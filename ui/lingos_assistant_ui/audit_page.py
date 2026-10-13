"""审计日志页（PRD 5.8：时间倒序、类型筛选、只读、导出 JSON）。"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

ACTION_FILTERS = ["全部", "tool_executed", "tool_denied", "tool_failed",
                  "key_written", "key_deleted", "settings_changed"]


class AuditPage(Adw.Window):
    def __init__(self, transient_for, client, **kwargs) -> None:
        super().__init__(transient_for=transient_for, modal=True, **kwargs)
        self.client = client
        self.set_title("审计日志")
        self.set_default_size(760, 560)
        self.set_destroy_with_parent(True)

        header = Adw.HeaderBar()

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          margin_start=12, margin_end=12, margin_top=8)
        dropdown = Gtk.DropDown.new_from_strings(ACTION_FILTERS)
        dropdown.connect("notify::selected", lambda *_: self._reload())
        toolbar.append(Gtk.Label(label="类型："))
        toolbar.append(dropdown)
        self.filter = dropdown

        export_btn = Gtk.Button(label="导出 JSON")
        export_btn.connect("clicked", lambda *_: self._export())
        toolbar.append(export_btn)
        toolbar.set_halign(Gtk.Align.END)
        toolbar.set_hexpand(True)

        # 列表
        self.store = Gtk.StringList()
        self.list = Gtk.ListView.new(Gtk.NoSelection.new(
            Gtk.SingleSelection.new(self.store)),
            Gtk.SignalListItemFactory.new())
        self.list.get_factory().connect("setup", self._on_setup)
        self.list.get_factory().connect("bind", self._on_bind)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(self.list)
        scrolled.set_vexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(header)
        box.append(toolbar)
        box.append(scrolled)
        self.set_content(box)
        self._reload()

    def _reload(self) -> None:
        while self.store.get_n_items():
            self.store.remove(0)
        action = ACTION_FILTERS[self.filter.get_selected()]
        try:
            data = self.client.list_audit(action=None if action == "全部" else action)
        except Exception as e:  # noqa: BLE001
            self.store.append(f"加载失败：{e}")
            return
        for item in data.get("items", []):
            self.store.append(f"{item.get('ts', '')}  [{item.get('action', '')}]  "
                              f"{item.get('detail_json') or ''}")

    def _on_setup(self, _factory, list_item) -> None:
        label = Gtk.Label(xalign=0, wrap=True, margin_top=4, margin_bottom=4)
        list_item.set_child(label)

    def _on_bind(self, _factory, list_item) -> None:
        label = list_item.get_child()
        obj = list_item.get_item()
        label.set_text(obj.get_string() if obj else "")

    def _export(self) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_initial_name("lingos-audit-logs.json")

        def on_response(_d, result) -> None:
            try:
                file = dialog.save_finish(result)
                if file:
                    self.client.export_audit(file.get_path())
            except Exception:  # noqa: BLE001 —— 用户取消
                pass

        dialog.save(self, None, on_response)
