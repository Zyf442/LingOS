"""FreeDesktop Trash 测试（PRD 5.4：移入回收站，永不真删）。"""

from __future__ import annotations


from lingos_assistantd.executor.trash import Trash, TrashError, restore_path_from_info


def test_trash_moves_file(tmp_path):
    data_home = tmp_path / "local" / "share"
    src = tmp_path / "docs" / "note.txt"
    src.parent.mkdir(parents=True)
    src.write_text("hello", encoding="utf-8")

    t = Trash(data_home)
    dest = t.trash(src)
    assert not src.exists()
    assert dest.exists()
    assert dest.parent == data_home / "Trash" / "files"

    info = data_home / "Trash" / "info" / f"{dest.name}.trashinfo"
    assert info.exists()
    original = restore_path_from_info(info)
    assert original == src.resolve()


def test_trash_name_collision(tmp_path):
    data_home = tmp_path / "share"
    t = Trash(data_home)
    f1 = tmp_path / "a.txt"
    f1.write_text("1", encoding="utf-8")
    t.trash(f1)
    f2 = tmp_path / "a.txt"
    f2.write_text("2", encoding="utf-8")
    dest2 = t.trash(f2)
    assert dest2.name == "a.txt.2"


def test_trash_missing_file_raises(tmp_path):
    t = Trash(tmp_path / "share")
    try:
        t.trash(tmp_path / "nope.txt")
        raise AssertionError("应当抛 TrashError")
    except TrashError:
        pass
