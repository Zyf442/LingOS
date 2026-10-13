"""存储层测试：迁移、CRUD、级联、审计松耦合、损坏自愈（PRD 4、5.2、11.3）。"""

from __future__ import annotations


from lingos_assistantd.ids import uuid7
from lingos_assistantd.storage import repos
from lingos_assistantd.storage.db import Database


def test_migrations_apply_and_versioned(db):
    versions = [r[0] for r in db.conn.execute("SELECT version FROM schema_version")]
    assert 1 in versions


def test_uuid7_monotonic_and_parseable():
    a, b = uuid7(), uuid7()
    assert a != b
    assert a < b  # 时间有序（字符串形式前 48bit 即时间戳）


def test_conversation_crud(db):
    conv = repos.create_conversation(db.conn, title="测试", model="qwen-plus")
    assert conv["title"] == "测试"
    assert repos.get_conversation(db.conn, conv["id"])["model"] == "qwen-plus"
    assert repos.rename_conversation(db.conn, conv["id"], "改名")
    assert not repos.rename_conversation(db.conn, uuid7(), "x")  # 404
    assert repos.soft_delete_conversation(db.conn, conv["id"])
    assert repos.get_conversation(db.conn, conv["id"]) is None  # 软删后不可见
    assert repos.list_conversations(db.conn)["total"] == 0


def test_conversation_search_m11(db):
    """M11：按标题或消息内容搜索会话。"""
    c1 = repos.create_conversation(db.conn, title="磁盘清理")
    c2 = repos.create_conversation(db.conn, title="随便聊聊")
    repos.insert_message(db.conn, c2["id"], "user", "帮我看下 df -h 的输出")
    db.conn.commit()

    # 标题搜索
    out = repos.list_conversations(db.conn, q="磁盘")
    assert out["total"] == 1 and out["items"][0]["id"] == c1["id"]
    # 消息内容搜索
    out = repos.list_conversations(db.conn, q="df -h")
    assert out["total"] == 1 and out["items"][0]["id"] == c2["id"]
    # 无命中
    assert repos.list_conversations(db.conn, q="不存在的关键词")["total"] == 0
    # 空白关键词 = 不过滤
    assert repos.list_conversations(db.conn, q="  ")["total"] == 2


def test_messages_and_tool_calls_cascade(db):
    conv = repos.create_conversation(db.conn)
    m = repos.insert_message(db.conn, conv["id"], "user", "帮我看看磁盘")
    tc = repos.insert_tool_call(db.conn, m["id"], conv["id"], "shell", {"command": "df -h"})
    repos.update_tool_call(db.conn, tc, "executed", {"exit_code": 0})
    got = repos.get_tool_call(db.conn, tc)
    assert got["decision"] == "executed"
    assert got["result"]["exit_code"] == 0

    # audit 松耦合：删会话（物理删除 CASCADE 消息/工具）后审计仍在
    repos.add_audit(db.conn, "tool_executed", detail={"t": 1}, tool_call_id=tc)
    db.conn.execute("DELETE FROM conversations WHERE id=?", (conv["id"],))
    db.conn.commit()
    rows = db.conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
    assert rows == 1
    # tool_call_id 已 SET NULL
    assert db.conn.execute("SELECT tool_call_id FROM audit_logs").fetchone()[0] is None


def test_settings_singleton(db):
    s = repos.get_settings(db.conn)
    assert s["id"] == 1 and s["model"] == "qwen-plus"
    s2 = repos.update_settings(db.conn, {"temperature": 0.2, "theme": "dark"})
    assert s2["temperature"] == 0.2 and s2["theme"] == "dark"


def test_fail_stale_tool_calls(db):
    conv = repos.create_conversation(db.conn)
    m = repos.insert_message(db.conn, conv["id"], "user", "x")
    tc1 = repos.insert_tool_call(db.conn, m["id"], conv["id"], "shell", {"command": "ls"})
    tc2 = repos.insert_tool_call(db.conn, m["id"], conv["id"], "shell", {"command": "df"})
    repos.update_tool_call(db.conn, tc2, "executed", {})  # 已执行的不动
    n = repos.fail_stale_tool_calls(db.conn)
    assert n == 1
    assert repos.get_tool_call(db.conn, tc1)["decision"] == "failed"
    assert repos.get_tool_call(db.conn, tc1)["result"]["reason"] == "daemon_restart"
    assert repos.get_tool_call(db.conn, tc2)["decision"] == "executed"


def test_corrupt_db_quarantine_and_rebuild(tmp_path):
    bad = tmp_path / "assistant.db"
    bad.write_bytes(b"this is definitely not a sqlite database" * 100)
    d = Database(bad)
    d.open()
    # 重建后是可用空库
    assert d.conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] >= 1
    assert d.corrupt_backup.exists()
    d.close()


def test_audit_list_filter(db):
    repos.add_audit(db.conn, "tool_executed", detail={"a": 1})
    repos.add_audit(db.conn, "tool_denied", detail={"a": 2})
    out = repos.list_audit(db.conn, action="tool_")
    assert out["total"] == 2
    out2 = repos.list_audit(db.conn, action="tool_denied")
    assert out2["total"] == 1
