"""数据访问层：conversations / messages / tool_calls / settings / audit_logs。

约定（PRD 11.3）：
- 拓扑序 conversations → messages → tool_calls；级联删除靠 ON DELETE CASCADE
- audit_logs.tool_call_id SET NULL（审计留痕不随会话删除而消失）
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..ids import uuid7
from ..times import utc_now_iso

# ---------------------------------------------------------------- conversations


def create_conversation(
    db: sqlite3.Connection, title: str = "新对话", model: str = "qwen-plus"
) -> dict[str, Any]:
    cid, now = uuid7(), utc_now_iso()
    db.execute(
        "INSERT INTO conversations(id,title,model,created_at,updated_at) VALUES(?,?,?,?,?)",
        (cid, title, model, now, now),
    )
    db.commit()
    return get_conversation(db, cid)


def get_conversation(db: sqlite3.Connection, cid: str) -> dict[str, Any] | None:
    row = db.execute("SELECT * FROM conversations WHERE id=? AND deleted=0", (cid,)).fetchone()
    return dict(row) if row else None


def list_conversations(
    db: sqlite3.Connection, page: int = 1, page_size: int = 50, q: str | None = None
) -> dict[str, Any]:
    """会话列表（M11 搜索：匹配标题或会话内消息内容）。"""
    off = max(page - 1, 0) * page_size
    where, params = "deleted=0", []
    if q:
        like = f"%{q.strip()}%"
        where = (
            "deleted=0 AND (title LIKE ? OR id IN ("
            "  SELECT conversation_id FROM messages WHERE content LIKE ?))"
        )
        params = [like, like]
    rows = db.execute(
        f"SELECT * FROM conversations WHERE {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        params + [page_size, off],
    ).fetchall()
    total = db.execute(f"SELECT COUNT(*) FROM conversations WHERE {where}", params).fetchone()[0]
    return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}


def rename_conversation(db: sqlite3.Connection, cid: str, title: str) -> bool:
    cur = db.execute(
        "UPDATE conversations SET title=?, updated_at=? WHERE id=? AND deleted=0",
        (title, utc_now_iso(), cid),
    )
    db.commit()
    return cur.rowcount > 0


def soft_delete_conversation(db: sqlite3.Connection, cid: str) -> bool:
    cur = db.execute(
        "UPDATE conversations SET deleted=1, updated_at=? WHERE id=? AND deleted=0",
        (utc_now_iso(), cid),
    )
    db.commit()
    return cur.rowcount > 0


def touch_conversation(db: sqlite3.Connection, cid: str) -> None:
    db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (utc_now_iso(), cid))


# ---------------------------------------------------------------- messages


def insert_message(
    db: sqlite3.Connection,
    conversation_id: str,
    role: str,
    content: str,
    status: str = "done",
    tokens: int | None = None,
) -> dict[str, Any]:
    mid = uuid7()
    db.execute(
        "INSERT INTO messages(id,conversation_id,role,content,tokens,created_at,status)"
        " VALUES(?,?,?,?,?,?,?)",
        (mid, conversation_id, role, content, tokens, utc_now_iso(), status),
    )
    return {
        "id": mid,
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "status": status,
        "tokens": tokens,
        "created_at": utc_now_iso(),
    }


def update_message(
    db: sqlite3.Connection,
    mid: str,
    content: str | None = None,
    status: str | None = None,
    tokens: int | None = None,
) -> None:
    sets, params = [], []
    if content is not None:
        sets.append("content=?")
        params.append(content)
    if status is not None:
        sets.append("status=?")
        params.append(status)
    if tokens is not None:
        sets.append("tokens=?")
        params.append(tokens)
    if not sets:
        return
    params.append(mid)
    db.execute(f"UPDATE messages SET {', '.join(sets)} WHERE id=?", params)


def list_messages(
    db: sqlite3.Connection, cid: str, page: int = 1, page_size: int = 50
) -> dict[str, Any]:
    off = max(page - 1, 0) * page_size
    rows = db.execute(
        "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at LIMIT ? OFFSET ?",
        (cid, page_size, off),
    ).fetchall()
    total = db.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=?", (cid,)).fetchone()[
        0
    ]
    return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}


def iter_messages_asc(db: sqlite3.Connection, cid: str) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at", (cid,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- tool_calls

TOOL_CALL_DECISIONS = (
    "pending",
    "confirmed",
    "denied_by_user",
    "denied_by_guard",
    "executed",
    "failed",
    "timeout",
)


def insert_tool_call(
    db: sqlite3.Connection,
    message_id: str,
    conversation_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    decision: str = "pending",
) -> str:
    tcid = uuid7()
    db.execute(
        "INSERT INTO tool_calls(id,message_id,conversation_id,tool_name,arguments_json,decision,created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (
            tcid,
            message_id,
            conversation_id,
            tool_name,
            json.dumps(arguments, ensure_ascii=False),
            decision,
            utc_now_iso(),
        ),
    )
    return tcid


def update_tool_call(
    db: sqlite3.Connection,
    tcid: str,
    decision: str,
    result: dict[str, Any] | None = None,
) -> None:
    db.execute(
        "UPDATE tool_calls SET decision=?, result_json=?, executed_at=? WHERE id=?",
        (
            decision,
            json.dumps(result, ensure_ascii=False) if result is not None else None,
            utc_now_iso(),
            tcid,
        ),
    )


def get_tool_call(db: sqlite3.Connection, tcid: str) -> dict[str, Any] | None:
    row = db.execute("SELECT * FROM tool_calls WHERE id=?", (tcid,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["arguments"] = json.loads(d.pop("arguments_json"))
    if d.get("result_json"):
        d["result"] = json.loads(d.pop("result_json"))
    else:
        d.pop("result_json", None)
        d["result"] = None
    return d


def tool_calls_for_message(db: sqlite3.Connection, message_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT * FROM tool_calls WHERE message_id=? ORDER BY created_at", (message_id,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["arguments"] = json.loads(d.pop("arguments_json"))
        if d.get("result_json"):
            d["result"] = json.loads(d.pop("result_json"))
        else:
            d["result"] = None
        out.append(d)
    return out


def fail_stale_tool_calls(db: sqlite3.Connection) -> int:
    """PRD 15：守护进程重启后，pending/confirmed 未执行的一律置 failed(daemon_restart)，绝不自动续执行。"""
    cur = db.execute(
        "UPDATE tool_calls SET decision='failed', result_json=json_object('reason','daemon_restart'),"
        " executed_at=? WHERE decision IN ('pending','confirmed')",
        (utc_now_iso(),),
    )
    db.commit()
    return cur.rowcount


# ---------------------------------------------------------------- settings（单例 id=1）

SETTINGS_FIELDS = (
    "provider",
    "base_url",
    "model",
    "temperature",
    "max_tokens",
    "context_window",
    "tools_enabled",
    "theme",
)


def get_settings(db: sqlite3.Connection) -> dict[str, Any]:
    row = db.execute("SELECT * FROM settings WHERE id=1").fetchone()
    if row is None:
        now = utc_now_iso()
        db.execute("INSERT INTO settings(id,updated_at) VALUES(1,?)", (now,))
        db.commit()
        row = db.execute("SELECT * FROM settings WHERE id=1").fetchone()
    return dict(row)


def update_settings(db: sqlite3.Connection, patch: dict[str, Any]) -> dict[str, Any]:
    get_settings(db)  # 确保单例存在
    sets, params = [], []
    for k, v in patch.items():
        if k in SETTINGS_FIELDS:
            sets.append(f"{k}=?")
            params.append(int(v) if k == "tools_enabled" else v)
    if sets:
        sets.append("updated_at=?")
        params.append(utc_now_iso())
        db.execute(f"UPDATE settings SET {', '.join(sets)} WHERE id=1", params)
        db.commit()
    return get_settings(db)


# ---------------------------------------------------------------- audit_logs


def add_audit(
    db: sqlite3.Connection,
    action: str,
    actor: str = "assistant",
    detail: dict[str, Any] | None = None,
    tool_call_id: str | None = None,
) -> str:
    aid = uuid7()
    db.execute(
        "INSERT INTO audit_logs(id,ts,actor,action,detail_json,tool_call_id) VALUES(?,?,?,?,?,?)",
        (
            aid,
            utc_now_iso(),
            actor,
            action,
            json.dumps(detail, ensure_ascii=False) if detail else None,
            tool_call_id,
        ),
    )
    db.commit()
    return aid


def list_audit(
    db: sqlite3.Connection,
    page: int = 1,
    page_size: int = 50,
    action: str | None = None,
) -> dict[str, Any]:
    where, params = "1=1", []
    if action:
        where = "action LIKE ?"
        params.append(f"{action}%")
    total = db.execute(f"SELECT COUNT(*) FROM audit_logs WHERE {where}", params).fetchone()[0]
    off = max(page - 1, 0) * page_size
    rows = db.execute(
        f"SELECT * FROM audit_logs WHERE {where} ORDER BY ts DESC LIMIT ? OFFSET ?",
        params + [page_size, off],
    ).fetchall()
    return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size}
