"""会话引擎 / 工具调度器（PRD 5.4 M4、7.3、15）。

职责：
- 会话/消息生命周期与流式生成（异步任务）
- LLM ↔ 工具调用循环（function calling），guard 决策三态：DENY / CONFIRM / AUTO_ALLOW
- 确认流：同一时刻仅 1 个 pending；UI 提交 decision 后放行
- 取消：kill LLM 流 + kill 执行中子进程组
- 守护进程重启后 pending 一律置 failed(daemon_restart)，绝不自动续执行（startup 恢复钩子）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import __version__
from ..core.circuit import AsyncCircuitBreaker
from ..core.context import ContextBuilder, estimate_tokens
from ..core.llm import DeltaEvent, DoneEvent, ErrorEvent, LLMClient, ToolCallEvent
from ..events import EventBus
from ..executor.guard import Decision, evaluate_tool_call
from ..storage import repos
from ..storage.db import Database
from ..tools.executor_tool import ToolExecutionError, ToolExecutor
from ..tools.schemas import TOOL_SCHEMAS
from ..tools.system_info import SystemInfo

log = logging.getLogger("lingos.chat")

MAX_TOOL_ROUNDS = 8
CONFIRM_TIMEOUT_SEC = 300.0
MAX_INVALID_ARGS_ROUNDS = 2
MAX_ATTACHMENT_BYTES = 256 * 1024


@dataclass
class PendingConfirm:
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    event: asyncio.Event = field(default_factory=asyncio.Event)
    decision: str = ""  # allow / deny / allow_batch
    remember_scope: str = ""


class ChatService:
    def __init__(
        self,
        db: Database,
        executor: ToolExecutor,
        bus: EventBus,
        keyring: Any,
        settings_getter: Any,  # () -> dict（settings 单例）
        llm_factory: Any = None,  # (base_url, key_getter, breaker) -> LLMClient（测试注入 FakeLLM）
        system_info: SystemInfo | None = None,
    ):
        self.db = db
        self.executor = executor
        self.bus = bus
        self.keyring = keyring
        self._settings_getter = settings_getter
        self.breaker = AsyncCircuitBreaker()
        self.system_info = system_info or SystemInfo()
        self._llm_factory = llm_factory or (
            lambda base_url, key_getter, breaker: LLMClient(base_url, key_getter, breaker)
        )
        self._llm: Any = None
        self._llm_base_url = ""
        self._generations: dict[str, asyncio.Task] = {}
        self.pending: PendingConfirm | None = None
        self._batch_allow: dict[str, list[str]] = {}  # tool -> [路径前缀]
        self._invalid_rounds = 0
        self._idempotency: dict[str, str] = {}

    # ---------------------------------------------------------------- LLM 客户端
    def get_llm(self) -> Any:
        s = self._settings_getter()
        if self._llm is None or self._llm_base_url != s["base_url"]:
            self._llm = self._llm_factory(s["base_url"], self.keyring.get_api_key, self.breaker)
            self._llm_base_url = s["base_url"]
        return self._llm

    # ---------------------------------------------------------------- 启动恢复（PRD 15）
    def recover_after_restart(self) -> int:
        n = repos.fail_stale_tool_calls(self.db.conn)
        if n:
            log.warning("服务重启，%d 个未完成工具调用已置 failed(daemon_restart)", n)
        return n

    # ---------------------------------------------------------------- 会话操作
    def create_conversation(
        self, title: str | None, model: str | None, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        if idempotency_key:
            cached = self._idempotency.get(idempotency_key)
            if cached:
                conv = repos.get_conversation(self.db.conn, cached)
                if conv:
                    return conv
        s = self._settings_getter()
        conv = repos.create_conversation(
            self.db.conn, title=title or "新对话", model=model or s["model"]
        )
        if idempotency_key:
            self._idempotency[idempotency_key] = conv["id"]
        return conv

    def send_message(
        self, conversation_id: str, content: str, attachments: list[str] | None = None
    ) -> str | None:
        """插入用户消息并启动生成任务，返回用户 message_id（202 响应体）。"""
        conv = repos.get_conversation(self.db.conn, conversation_id)
        if conv is None:
            return None
        extra = ""
        for path in (attachments or [])[:5]:
            extra += f"\n\n--- 附件 {path} ---\n" + self._read_attachment(path)
        user_msg = repos.insert_message(self.db.conn, conversation_id, "user", content + extra)
        repos.touch_conversation(self.db.conn, conversation_id)
        self.db.conn.commit()

        old = self._generations.get(conversation_id)
        if old and not old.done():
            old.cancel()
        task = asyncio.get_event_loop().create_task(self._generate(conversation_id))
        self._generations[conversation_id] = task
        return user_msg["id"]

    def cancel(self, conversation_id: str) -> bool:
        if self.pending:
            self._resolve_pending("deny")
        task = self._generations.get(conversation_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    # ---------------------------------------------------------------- 生成主循环
    async def _generate(self, conversation_id: str) -> None:
        s = self._settings_getter()
        conv = repos.get_conversation(self.db.conn, conversation_id)
        assistant_id: str | None = None
        text_buf: list[str] = []
        try:
            history = self._build_history(conversation_id)
            ctx = ContextBuilder(context_window=s["context_window"])
            llm = self.get_llm()
            messages = await ctx.build(history, self.system_info.text_summary())
            tools = TOOL_SCHEMAS if s["tools_enabled"] else None

            for _round in range(MAX_TOOL_ROUNDS):
                assistant_id = None
                text_buf = []
                tokens: int | None = None
                got_tool_calls: list[dict[str, Any]] | None = None

                async for ev in llm.stream_chat(
                    model=conv["model"],
                    messages=messages,
                    tools=tools,
                    temperature=s["temperature"],
                    max_tokens=s["max_tokens"],
                ):
                    if isinstance(ev, DeltaEvent):
                        if assistant_id is None:
                            assistant_id = self._insert_assistant(conversation_id, streaming=True)
                        text_buf.append(ev.text)
                        self.bus.publish(EventBus.delta(assistant_id, ev.text))
                    elif isinstance(ev, ToolCallEvent):
                        if assistant_id is None:
                            assistant_id = self._insert_assistant(conversation_id, streaming=True)
                        got_tool_calls = ev.tool_calls
                        break
                    elif isinstance(ev, ErrorEvent):
                        if assistant_id is None:
                            assistant_id = self._insert_assistant(conversation_id, streaming=True)
                        self._finish_assistant(assistant_id, "".join(text_buf), status="error")
                        self.bus.publish(EventBus.message_error(assistant_id, ev.code, ev.message))
                        self._touch(conversation_id)
                        return
                    elif isinstance(ev, DoneEvent):
                        tokens = ev.total_tokens

                if got_tool_calls is None:
                    # 纯文本回复收尾
                    if assistant_id is None:
                        assistant_id = self._insert_assistant(conversation_id, streaming=False)
                    self._finish_assistant(
                        assistant_id, "".join(text_buf), status="done", tokens=tokens
                    )
                    self.bus.publish(EventBus.message_done(assistant_id, tokens))
                    self._touch(conversation_id)
                    return

                # 本轮流式文本先落库，再处理工具调用
                self._finish_assistant(assistant_id, "".join(text_buf), status="done")
                messages.append(
                    {
                        "role": "assistant",
                        "content": "".join(text_buf),
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["name"],
                                    "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                                },
                            }
                            for tc in got_tool_calls
                        ],
                    }
                )
                tool_messages = await self._handle_tool_calls(
                    conversation_id, assistant_id, got_tool_calls
                )
                messages.extend(tool_messages)

            # 工具轮数耗尽
            if assistant_id:
                self._finish_assistant(
                    assistant_id, "".join(text_buf) or "（工具调用轮数已达上限）", status="done"
                )
                self.bus.publish(EventBus.message_done(assistant_id, None))
                self._touch(conversation_id)
        except asyncio.CancelledError:
            self._kill_child()
            if assistant_id:
                self._finish_assistant(assistant_id, "".join(text_buf) or "", status="cancelled")
                self.bus.publish(EventBus.message_error(assistant_id, "cancelled", "已停止生成"))
            self.db.conn.commit()
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("生成失败 conv=%s", conversation_id)
            if assistant_id:
                self._finish_assistant(assistant_id, "".join(text_buf), status="error")
                self.bus.publish(
                    EventBus.message_error(assistant_id, "internal_error", f"生成失败：{e}"[:200])
                )
            self.db.conn.commit()

    # ---------------------------------------------------------------- 工具调用处理
    async def _handle_tool_calls(
        self,
        conversation_id: str,
        assistant_message_id: str,
        tool_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """返回需要回传给 LLM 的 tool 角色消息列表。"""
        out: list[dict[str, Any]] = []
        for call in tool_calls:
            name = call.get("name", "")
            args = dict(call.get("arguments") or {})
            if args.pop("__invalid__", False):
                # PRD 6.1：参数解析失败 → 回传 invalid_arguments 自纠 ≤2 轮
                self._invalid_rounds += 1
                fatal = self._invalid_rounds > MAX_INVALID_ARGS_ROUNDS
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": json.dumps(
                            {"error": "invalid_arguments", **({"fatal": True} if fatal else {})},
                            ensure_ascii=False,
                        ),
                    }
                )
                continue

            tcid = repos.insert_tool_call(
                self.db.conn, assistant_message_id, conversation_id, name, args
            )
            g = evaluate_tool_call(name, args)

            if g.decision == Decision.DENY:
                repos.update_tool_call(self.db.conn, tcid, "denied_by_guard", {"reason": g.reason})
                repos.add_audit(
                    self.db.conn,
                    "tool_denied",
                    detail={
                        "tool": name,
                        "reason": g.reason,
                        "arguments": args,
                    },
                    tool_call_id=tcid,
                )
                self.bus.publish(
                    EventBus.tool_resolved(tcid, "denied_by_guard", {"reason": g.reason})
                )
                out.append(
                    self._tool_result_message(
                        tcid,
                        name,
                        f"该操作被系统安全策略拒绝（{g.reason}）。请换一种安全的方式，或询问用户手动操作。",
                    )
                )
                continue

            if g.decision == Decision.AUTO_ALLOW or self._batch_match(name, args):
                result = await self._execute_and_record(tcid, conversation_id, name, args)
                out.append(self._tool_result_message(tcid, name, result))
                continue

            # CONFIRM：等用户确认（同一时刻仅 1 个 pending，PRD 7.3）
            self.pending = PendingConfirm(tool_call_id=tcid, tool_name=name, arguments=args)
            self.bus.publish(EventBus.tool_requested(tcid, name, args, g.risk, g.preview))
            try:
                await asyncio.wait_for(self.pending.event.wait(), CONFIRM_TIMEOUT_SEC)
                decision = self.pending.decision
                if decision == "allow_batch":
                    scope = self.pending.remember_scope or self._infer_scope(name, args)
                    if scope:
                        self._batch_allow.setdefault(name, []).append(scope.split(":", 1)[1])
                if decision in ("allow", "allow_batch"):
                    result = await self._execute_and_record(tcid, conversation_id, name, args)
                    out.append(self._tool_result_message(tcid, name, result))
                else:
                    repos.update_tool_call(self.db.conn, tcid, "denied_by_user")
                    repos.add_audit(
                        self.db.conn,
                        "tool_denied",
                        detail={
                            "tool": name,
                            "by": "user",
                            "arguments": args,
                        },
                        tool_call_id=tcid,
                    )
                    self.bus.publish(EventBus.tool_resolved(tcid, "denied_by_user", {}))
                    out.append(
                        self._tool_result_message(
                            tcid, name, "用户拒绝了该操作。不要重复发起相同调用，请询问用户意图。"
                        )
                    )
            except asyncio.TimeoutError:
                repos.update_tool_call(self.db.conn, tcid, "timeout", {"reason": "confirm_timeout"})
                self.bus.publish(EventBus.tool_resolved(tcid, "timeout", {}))
                out.append(self._tool_result_message(tcid, name, "等待用户确认超时，操作未执行。"))
            finally:
                self.pending = None
        self.db.conn.commit()
        return out

    async def _execute_and_record(
        self, tcid: str, conversation_id: str, name: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            result = await self.executor.execute(name, args)
            repos.update_tool_call(self.db.conn, tcid, "executed", result)
            repos.add_audit(
                self.db.conn,
                "tool_executed",
                detail={
                    "tool": name,
                    "arguments": args,
                },
                tool_call_id=tcid,
            )
            summary = _summarize_result(result)
            self.bus.publish(EventBus.tool_resolved(tcid, "confirmed", summary))
            return summary
        except ToolExecutionError as e:
            failure = {"error": str(e)}
            repos.update_tool_call(self.db.conn, tcid, "failed", failure)
            repos.add_audit(
                self.db.conn,
                "tool_failed",
                detail={
                    "tool": name,
                    "error": str(e),
                },
                tool_call_id=tcid,
            )
            self.bus.publish(EventBus.tool_resolved(tcid, "failed", failure))
            return failure

    def decide(self, tool_call_id: str, decision: str, remember_scope: str = "") -> bool:
        """UI 提交确认结果（allow / deny / allow_batch）。"""
        p = self.pending
        if p is None or p.tool_call_id != tool_call_id:
            return False
        if decision == "allow_batch" and not remember_scope:
            remember_scope = self._infer_scope(p.tool_name, p.arguments)
        p.decision = decision
        p.remember_scope = remember_scope
        p.event.set()
        return True

    def _infer_scope(self, tool: str, args: dict[str, Any]) -> str:
        path = str(args.get("path", ""))
        if tool.startswith("file_") and path:
            prefix = str(path.rsplit("/", 1)[0] or "/")
            return f"{tool}:{prefix}"
        return ""

    def _batch_match(self, tool: str, args: dict[str, Any]) -> bool:
        path = str(args.get("path", ""))
        return any(path.startswith(p) for p in self._batch_allow.get(tool, []))

    # ---------------------------------------------------------------- 历史重建
    def _build_history(self, conversation_id: str) -> list[dict[str, Any]]:
        msgs = repos.iter_messages_asc(self.db.conn, conversation_id)
        tc_by_msg: dict[str, list[dict[str, Any]]] = {}
        for m in msgs:
            if m["role"] == "assistant":
                tcs = repos.tool_calls_for_message(self.db.conn, m["id"])
                if tcs:
                    tc_by_msg[m["id"]] = tcs
        history: list[dict[str, Any]] = []
        for m in msgs:
            if m["role"] == "assistant" and m["id"] in tc_by_msg:
                history.append(
                    {
                        "role": "assistant",
                        "content": m["content"],
                        "tool_calls": [
                            {
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": tc["tool_name"],
                                    "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                                },
                            }
                            for tc in tc_by_msg[m["id"]]
                        ],
                    }
                )
                for tc in tc_by_msg[m["id"]]:
                    summary = tc.get("result") or {"decision": tc["decision"]}
                    history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(summary, ensure_ascii=False)[:4000],
                        }
                    )
            else:
                history.append({"role": m["role"], "content": m["content"]})
        return history

    # ---------------------------------------------------------------- 辅助
    def _insert_assistant(self, conversation_id: str, streaming: bool) -> str:
        m = repos.insert_message(
            self.db.conn,
            conversation_id,
            "assistant",
            "",
            status="streaming" if streaming else "done",
        )
        self.db.conn.commit()
        return m["id"]

    def _finish_assistant(
        self, mid: str, content: str, status: str, tokens: int | None = None
    ) -> None:
        repos.update_message(
            self.db.conn,
            mid,
            content=content,
            status=status,
            tokens=tokens if tokens is not None else estimate_tokens(content),
        )
        self.db.conn.commit()

    def _touch(self, conversation_id: str) -> None:
        repos.touch_conversation(self.db.conn, conversation_id)
        self.db.conn.commit()

    def _read_attachment(self, path: str) -> str:
        """附件为纯文本读取（不走确认流——用户主动提供路径即视为授权，PRD 8.1）。"""
        p = Path(os.path.expanduser(path))
        try:
            if p.stat().st_size > MAX_ATTACHMENT_BYTES:
                return "（附件超过 256KB，已跳过）"
            return p.read_text(encoding="utf-8", errors="replace")[:32_000]
        except OSError as e:
            return f"（附件读取失败: {e}）"

    def _kill_child(self) -> None:
        runner = getattr(self.executor, "runner", None)
        if runner is not None:
            try:
                runner.kill_running()
            except Exception:  # noqa: BLE001
                pass

    def _tool_result_message(self, tcid: str, name: str, result: Any) -> dict[str, Any]:
        content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return {"role": "tool", "tool_call_id": tcid, "content": content[:8000]}

    # ---------------------------------------------------------------- 状态
    def status(self) -> dict[str, Any]:
        s = self._settings_getter()
        return {
            "version": __version__,
            "circuit": self.breaker.snapshot(),
            "has_key": bool(self.keyring.get_api_key()),
            "tools_enabled": bool(s["tools_enabled"]),
        }


def _summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    """给 LLM 回传的结果摘要（8KB 截断，PRD 6.1）。"""
    s = json.dumps(result, ensure_ascii=False)
    if len(s) > 8000:
        return {"truncated": True, "content": s[:8000]}
    return result
