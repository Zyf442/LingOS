"""上下文组装与裁剪（PRD 5.4 M3、6.1）。

- token 估算：len(text)//2 粗估 + 每消息固定开销 4
- 超过 context_window 时：保留 system prompt + 最近消息，中间历史压缩为一条摘要
  （由模型异步生成，失败则直接截断）
- 注入防护：用户消息与工具返回一律作为 user/tool 角色传入，绝不拼接进 system prompt
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from .prompts import build_system_prompt

log = logging.getLogger("lingos.context")

PER_MESSAGE_OVERHEAD = 4


def estimate_tokens(text: str) -> int:
    return len(text or "") // 2 + PER_MESSAGE_OVERHEAD


class SummarizerProtocol(Protocol):
    async def summarize(self, messages: list[dict[str, Any]]) -> str: ...


class ContextBuilder:
    def __init__(self, context_window: int = 30000):
        self.context_window = context_window

    async def build(
        self,
        history: list[dict[str, Any]],
        system_info_summary: str | None,
        summarizer: SummarizerProtocol | None = None,
    ) -> list[dict[str, Any]]:
        """history: [{'role','content','tool_calls'(opt),'tool_call_id'(opt)}]，时间升序。"""
        system_msg: dict[str, Any] = {
            "role": "system",
            "content": build_system_prompt(system_info_summary),
        }
        body = list(history)
        total = estimate_tokens(system_msg["content"]) + sum(
            estimate_tokens(m.get("content") or "") for m in body
        )
        if total <= self.context_window:
            return [system_msg, *body]

        # 超窗：保留 system + 最近消息，压缩中间历史
        recent_keep = self._plan_keep(body)
        middle = body[:-recent_keep] if recent_keep else body
        recent = body[-recent_keep:] if recent_keep else []

        summary_text: str | None = None
        if summarizer is not None and middle:
            try:
                summary_text = await summarizer.summarize(middle)
            except Exception:  # noqa: BLE001 —— 摘要失败则直接截断
                log.warning("历史摘要生成失败，直接截断", exc_info=True)
        if summary_text:
            summary_msg: dict[str, Any] = {
                "role": "system",
                "content": f"（此前对话的自动摘要）\n{summary_text}",
            }
            return [system_msg, summary_msg, *recent]
        # 截断兜底
        return [system_msg, *recent]

    def _plan_keep(self, body: list[dict[str, Any]]) -> int:
        """贪心保留尽量新的消息（不超过窗口的 60%），但至少保留最新一条。"""
        if not body:
            return 0
        budget = int(self.context_window * 0.6)
        used = 0
        keep = 0
        for msg in reversed(body):
            cost = estimate_tokens(msg.get("content") or "")
            if keep > 0 and used + cost > budget:
                break
            used += cost
            keep += 1
        return keep
