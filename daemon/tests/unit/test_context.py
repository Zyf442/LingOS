"""上下文裁剪测试（PRD 5.4 M3）。"""

from __future__ import annotations

from lingos_assistantd.core.context import ContextBuilder, estimate_tokens
from lingos_assistantd.core.prompts import build_system_prompt


def test_estimate_tokens():
    assert estimate_tokens("abcd") == 2 + 4
    assert estimate_tokens("") == 4


def test_system_prompt_contains_rules():
    p = build_system_prompt("Ubuntu 24.04 / 内核 6.8.0")
    assert "LingOS" in p
    assert "Ubuntu 24.04" in p
    assert "~/.ssh" in p  # 系统级规则第 7 条
    assert "工具调用都会先展示给用户确认" in p


def test_system_prompt_empty_summary():
    p = build_system_prompt(None)
    assert "（获取失败）" in p


async def test_within_window_keeps_all():
    b = ContextBuilder(context_window=30000)
    history = [{"role": "user", "content": "你好"}] * 10
    out = await b.build(history, "sys summary")
    assert out[0]["role"] == "system"
    assert len(out) == 11


async def test_over_window_truncates_middle():
    b = ContextBuilder(context_window=500)
    big = "x" * 900  # 每条约 454 token
    history = [{"role": "user", "content": big + str(i)} for i in range(20)]
    out = await b.build(history, None)
    total = sum(estimate_tokens(m.get("content", "")) for m in out)
    assert total <= 500 + 600  # system prompt + 摘要开销允许小幅超出
    # 保留的是最新的消息
    assert any("19" in m.get("content", "") for m in out)
    # 最早的消息被裁掉
    assert not any(
        m.get("content", "").endswith("0") and len(m.get("content", "")) > 100 for m in out[1:]
    )


async def test_summarizer_used_when_provided():
    class Summarizer:
        async def summarize(self, messages):
            return f"共 {len(messages)} 条历史消息的摘要"

    b = ContextBuilder(context_window=500)
    history = [{"role": "user", "content": "x" * 900 + str(i)} for i in range(20)]
    out = await b.build(history, None, summarizer=Summarizer())
    assert len(out) == 3  # system + 摘要 + 最近消息（1 条）
    assert "共 19 条历史消息的摘要" in out[1]["content"]


async def test_summarizer_failure_falls_back_to_truncate():
    class BrokenSummarizer:
        async def summarize(self, messages):
            raise RuntimeError("LLM 不可用")

    b = ContextBuilder(context_window=500)
    history = [{"role": "user", "content": "x" * 900 + str(i)} for i in range(20)]
    out = await b.build(history, None, summarizer=BrokenSummarizer())
    # 无摘要消息，直接截断
    assert all("历史消息的摘要" not in m.get("content", "") for m in out)
