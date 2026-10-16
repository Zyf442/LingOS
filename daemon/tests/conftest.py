"""测试基座（PRD 11.4：必须在写第一个测试文件之前完成）。

隔离方案：
- SQLite：每用例 tmp_path 独立库文件（autouse fixture 建库+迁移）
- keyring：EnvKeyring 内存后端
- 子进程：FakeExecutor（集成测试仅跑白名单安全命令）
- 环境变量：monkeypatch 每用例恢复
- LLM：永远 mock（FakeLLM 脚本驱动）
- 端口：不绑定（TestClient / ASGITransport）
"""

from __future__ import annotations

from typing import Any

import pytest

from lingos_assistantd.api.app import AppContext, create_app
from lingos_assistantd.config import DaemonSettings
from lingos_assistantd.core.llm import DeltaEvent, DoneEvent, ErrorEvent, ToolCallEvent
from lingos_assistantd.events import EventBus
from lingos_assistantd.keyring_service import EnvKeyring
from lingos_assistantd.service.chat_service import ChatService
from lingos_assistantd.storage import repos
from lingos_assistantd.storage.db import Database

TEST_TOKEN = "test-token-0123456789abcdef"


# ---------------------------------------------------------------- db


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "assistant.db")
    d.open()
    yield d
    d.close()


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    return DaemonSettings(
        env="dev",
        db_path=str(tmp_path / "data" / "assistant.db"),
        no_systemd=True,
        dev_keyring="",
    )


# ---------------------------------------------------------------- LLM 替身


class FakeLLM:
    """脚本驱动：script 是 (kind, payload) 列表；以 done/error 为一轮的终止符。
    每次 stream_chat 消费完整一轮（即使调用方在 tool 事件处提前 break，本轮也视为已消费）。"""

    def __init__(self):
        self.script: list[tuple[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self._round_index = 0

    def _rounds(self) -> list[list[tuple[str, Any]]]:
        rounds: list[list[tuple[str, Any]]] = []
        cur: list[tuple[str, Any]] = []
        for item in self.script:
            cur.append(item)
            if item[0] in ("done", "error"):
                rounds.append(cur)
                cur = []
        if cur:
            rounds.append(cur)
        return rounds

    async def stream_chat(self, model, messages, tools=None, temperature=0.7, max_tokens=4096):
        self.calls.append(
            {
                "model": model,
                "messages": [dict(m) for m in messages],
                "tools": tools,
                "temperature": temperature,
            }
        )
        rounds = self._rounds()
        if self._round_index >= len(rounds):
            yield DoneEvent(finish_reason="stop", total_tokens=1)
            return
        idx = self._round_index
        self._round_index += 1
        for kind, payload in rounds[idx]:
            if kind == "delta":
                yield DeltaEvent(payload)
            elif kind == "tool":
                yield ToolCallEvent(payload)
            elif kind == "done":
                yield DoneEvent(finish_reason="stop", total_tokens=payload)
            elif kind == "error":
                yield ErrorEvent(payload[0], payload[1])

    async def test_connectivity(self, model):
        return {"ok": True, "model": model}


# ---------------------------------------------------------------- Executor 替身


class FakeExecutor:
    def __init__(self):
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.results: dict[str, dict[str, Any]] = {
            "system_info": {"os": "Ubuntu 24.04 LTS", "kernel": "6.8.0"},
            "shell": {"exit_code": 0, "stdout": "fake-stdout", "stderr": "", "duration_ms": 5},
        }

    async def execute(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        self.executed.append((tool, dict(args)))
        if tool in self.results:
            return self.results[tool]
        return {"ok": True, "tool": tool, "args": args}


# ---------------------------------------------------------------- 应用装配


class Harness:
    def __init__(self, app, ctx, chat, fake_llm, fake_executor, bus, db, keyring):
        self.app = app
        self.ctx = ctx
        self.chat = chat
        self.llm = fake_llm
        self.executor = fake_executor
        self.bus = bus
        self.db = db
        self.keyring = keyring


@pytest.fixture
def harness(db, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    keyring = EnvKeyring("testkey-not-a-real-secret-000")
    bus = EventBus()
    fake_llm = FakeLLM()
    fake_executor = FakeExecutor()
    chat = ChatService(
        db=db,
        executor=fake_executor,
        bus=bus,
        keyring=keyring,
        settings_getter=lambda: repos.get_settings(db.conn),
        llm_factory=lambda base_url, key_getter, breaker: fake_llm,
    )
    ctx = AppContext(db=db, chat=chat, bus=bus, keyring=keyring, token=TEST_TOKEN)
    app = create_app(ctx)
    return Harness(app, ctx, chat, fake_llm, fake_executor, bus, db, keyring)


@pytest.fixture
def client(harness):
    from fastapi.testclient import TestClient

    with TestClient(harness.app) as c:
        yield c


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {TEST_TOKEN}"}
