"""UI 冒烟测试：仅在有 GTK4 的 Ubuntu 24.04/devcontainer 环境运行。"""

import pytest

gi = pytest.importorskip("gi", reason="需要 PyGObject（仅 Ubuntu 24.04/devcontainer）")


def _has_gtk() -> bool:
    try:
        gi.require_version("Gtk", "4.0")
        return True
    except Exception:  # noqa: BLE001
        return False


gtk_available = pytest.mark.skipif(not _has_gtk(), reason="GTK4 运行时不可用")


@gtk_available
def test_import_app_module():
    """应用模块可导入且 APP_ID 正确（语法/依赖级冒烟）。"""
    from lingos_assistant_ui.app import APP_ID

    assert APP_ID == "com.lingos.assistant"


def test_quick_cards_defined():
    from lingos_assistant_ui.quick_cards import QUICK_CARDS

    assert len(QUICK_CARDS) == 4
    for label, prompt in QUICK_CARDS:
        assert label and prompt
