"""mock 流式端到端测试（PRD 12.1）：
纯文本流 / 单工具调用流（确认-允许）/ 黑名单拒绝 / 用户拒绝 / 自动放行(system_info)
/ 参数非法自纠 / 取消
"""

from __future__ import annotations

import asyncio

from lingos_assistantd.storage import repos


async def _wait_generation(harness, cid, timeout=5.0):
    task = harness.chat._generations.get(cid)
    assert task is not None
    await asyncio.wait_for(task, timeout=timeout)


async def _new_conv(harness) -> str:
    return harness.chat.create_conversation("e2e", None)["id"]


async def test_plain_text_stream(harness):
    cid = await _new_conv(harness)
    harness.llm.script = [
        ("delta", "你好，"),
        ("delta", "我是 LingOS 助手。"),
        ("done", 12),
    ]
    mid = harness.chat.send_message(cid, "打个招呼")
    assert mid
    await _wait_generation(harness, cid)

    msgs = repos.iter_messages_asc(harness.db.conn, cid)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == "你好，我是 LingOS 助手。"
    assert msgs[1]["status"] == "done"


async def test_system_info_auto_allow_flow(harness):
    cid = await _new_conv(harness)
    harness.llm.script = [
        ("tool", [{"id": "call-1", "name": "system_info", "arguments": {}}]),
        ("done", None),
        ("delta", "你的系统是 Ubuntu 24.04。"),
        ("done", 20),
    ]
    harness.chat.send_message(cid, "系统信息？")
    await _wait_generation(harness, cid)

    # system_info 自动放行并执行
    assert harness.executor.executed[0][0] == "system_info"
    msgs = repos.iter_messages_asc(harness.db.conn, cid)
    final = msgs[-1]
    assert final["content"] == "你的系统是 Ubuntu 24.04。"
    # 工具调用结果已回传 LLM（第二轮 messages 包含 tool 消息）
    second_call = harness.llm.calls[1]
    tool_msgs = [m for m in second_call["messages"] if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert "Ubuntu" in tool_msgs[0]["content"]


async def test_shell_tool_confirm_allow_flow(harness):
    cid = await _new_conv(harness)
    harness.llm.script = [
        (
            "tool",
            [
                {
                    "id": "call-2",
                    "name": "shell",
                    "arguments": {"command": "echo hello", "timeout_sec": 10},
                }
            ],
        ),
        ("done", None),
        ("delta", "已执行。"),
        ("done", 8),
    ]
    harness.chat.send_message(cid, "执行 echo hello")
    # 等待 pending 出现
    for _ in range(100):
        if harness.chat.pending is not None:
            break
        await asyncio.sleep(0.02)
    assert harness.chat.pending is not None
    assert harness.chat.pending.tool_name == "shell"
    tcid = harness.chat.pending.tool_call_id

    # 模拟用户点击允许
    assert harness.chat.decide(tcid, "allow")
    await _wait_generation(harness, cid)

    assert harness.executor.executed[0] == ("shell", {"command": "echo hello", "timeout_sec": 10})
    tc = repos.get_tool_call(harness.db.conn, tcid)
    assert tc["decision"] == "executed"
    # 审计有记录
    logs = repos.list_audit(harness.db.conn, action="tool_")
    assert logs["total"] >= 1


async def test_blacklisted_tool_denied_by_guard(harness):
    cid = await _new_conv(harness)
    harness.llm.script = [
        ("tool", [{"id": "call-3", "name": "shell", "arguments": {"command": "rm -rf /"}}]),
        ("done", None),
        ("delta", "抱歉，该命令被安全策略拒绝。"),
        ("done", 8),
    ]
    harness.chat.send_message(cid, "删掉整个系统")
    await _wait_generation(harness, cid)

    # 未执行任何工具；tool_call 状态 denied_by_guard
    assert harness.executor.executed == []
    rows = harness.db.conn.execute("SELECT decision FROM tool_calls").fetchall()
    assert rows and rows[0][0] == "denied_by_guard"
    # LLM 收到拒绝原因
    second_call = harness.llm.calls[1]
    tool_msgs = [m for m in second_call["messages"] if m["role"] == "tool"]
    assert "安全策略拒绝" in tool_msgs[0]["content"]


async def test_user_denies_tool(harness):
    cid = await _new_conv(harness)
    harness.llm.script = [
        (
            "tool",
            [
                {
                    "id": "call-4",
                    "name": "file_write",
                    "arguments": {"path": "/tmp/lingos-e2e.txt", "content": "hi"},
                }
            ],
        ),
        ("done", None),
        ("delta", "好的，我不写了。"),
        ("done", 8),
    ]
    harness.chat.send_message(cid, "写个文件")
    for _ in range(100):
        if harness.chat.pending is not None:
            break
        await asyncio.sleep(0.02)
    assert harness.chat.decide(harness.chat.pending.tool_call_id, "deny")
    await _wait_generation(harness, cid)
    assert harness.executor.executed == []
    rows = harness.db.conn.execute("SELECT decision FROM tool_calls").fetchall()
    assert rows[0][0] == "denied_by_user"


async def test_allow_batch_scope(harness):
    cid = await _new_conv(harness)
    harness.llm.script = [
        (
            "tool",
            [
                {
                    "id": "call-5",
                    "name": "file_delete",
                    "arguments": {"path": "/tmp/lingos-batch/a.txt"},
                }
            ],
        ),
        ("done", None),
        (
            "tool",
            [
                {
                    "id": "call-6",
                    "name": "file_delete",
                    "arguments": {"path": "/tmp/lingos-batch/b.txt"},
                }
            ],
        ),
        ("done", None),
        ("delta", "两个文件都已处理。"),
        ("done", 8),
    ]
    harness.chat.send_message(cid, "删两个文件")
    for _ in range(100):
        if harness.chat.pending is not None:
            break
        await asyncio.sleep(0.02)
    # allow_batch + 记住前缀
    assert harness.chat.decide(
        harness.chat.pending.tool_call_id,
        "allow_batch",
        remember_scope="file_delete:/tmp/lingos-batch",
    )
    await _wait_generation(harness, cid)
    # 第二个删除不再确认，直接执行
    assert len(harness.executor.executed) == 2
    assert harness.executor.executed[1][1]["path"] == "/tmp/lingos-batch/b.txt"


async def test_invalid_arguments_self_correction(harness):
    cid = await _new_conv(harness)
    harness.llm.script = [
        (
            "tool",
            [
                {
                    "id": "call-7",
                    "name": "shell",
                    "arguments": {"__invalid__": True, "__raw__": "{broken json"},
                }
            ],
        ),
        ("done", None),
        ("tool", [{"id": "call-8", "name": "system_info", "arguments": {}}]),
        ("done", None),
        ("delta", "已改用 system_info。"),
        ("done", 8),
    ]
    harness.chat.send_message(cid, "看看系统")
    await _wait_generation(harness, cid)
    # 第一轮收到 invalid_arguments，模型自纠后 system_info 成功
    tool_msgs_round1 = [m for m in harness.llm.calls[1]["messages"] if m["role"] == "tool"]
    assert "invalid_arguments" in tool_msgs_round1[-1]["content"]
    assert any(t[0] == "system_info" for t in harness.executor.executed)


async def test_cancel_generation(harness):
    cid = await _new_conv(harness)

    class SlowLLM:
        async def stream_chat(self, *a, **kw):
            import lingos_assistantd.core.llm as llm_mod

            yield llm_mod.DeltaEvent("第一个字")
            await asyncio.sleep(30)  # 永不完成
            yield llm_mod.DoneEvent(finish_reason="stop", total_tokens=1)

    harness.llm.script = []
    orig_factory = harness.chat._llm_factory
    harness.chat._llm_factory = lambda *a, **kw: SlowLLM()
    harness.chat._llm = None
    harness.chat.send_message(cid, "慢慢说")
    await asyncio.sleep(0.2)
    assert harness.chat.cancel(cid) is True
    await asyncio.sleep(0.2)
    msgs = repos.iter_messages_asc(harness.db.conn, cid)
    assert msgs[-1]["status"] == "cancelled"
    harness.chat._llm_factory = orig_factory
    harness.chat._llm = None


async def test_error_event_flow(harness):
    cid = await _new_conv(harness)
    harness.llm.script = [
        ("error", ("llm_circuit_open", "AI 服务暂不可用，请稍后再试")),
    ]
    harness.chat.send_message(cid, "你好")
    await _wait_generation(harness, cid)
    msgs = repos.iter_messages_asc(harness.db.conn, cid)
    assert msgs[-1]["status"] == "error"
