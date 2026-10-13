"""守护进程 HTTP/WS 客户端（PRD 8：18 接口 + WS 事件流）。

- token/port 从 $XDG_RUNTIME_DIR/lingos/ 读取
- WS 事件回调分发（message.delta / tool_call.requested / status.changed …）
- 草稿按会话 id 每 5s 暂存 $XDG_STATE_HOME/lingos/drafts/（PRD 5.3）
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

import httpx


class ServiceUnavailable(RuntimeError):
    pass


class AssistantClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
        self._on_event: Callable[[dict[str, Any]], None] | None = None
        self._ws_thread = None

    # ------------------------------------------------ 连接发现
    @classmethod
    def discover(cls, token_path: str, port_path: str) -> "AssistantClient":
        try:
            token = Path(token_path).read_text(encoding="utf-8").strip()
            port = Path(port_path).read_text(encoding="utf-8").strip()
        except OSError as e:
            raise ServiceUnavailable(f"助手服务未就绪（{e}）") from e
        if not token or not port:
            raise ServiceUnavailable("助手服务未就绪")
        client = cls(f"http://127.0.0.1:{port}/api/v1", token)
        try:
            client.healthz()
        except (httpx.HTTPError, OSError) as e:
            raise ServiceUnavailable(f"助手服务未就绪（{e}）") from e
        return client

    # ------------------------------------------------ REST
    def _get(self, path: str, **params) -> Any:
        r = self._http.get(path, params=params)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict | None = None, **kw) -> httpx.Response:
        return self._http.post(path, json=body, **kw)

    def healthz(self) -> dict:
        return self._get("/healthz")

    def list_conversations(self, page: int = 1, q: str | None = None) -> dict:
        return self._get("/conversations", page=page, q=q)

    def create_conversation(self, title: str | None = None) -> dict:
        r = self._post("/conversations", {"title": title})
        r.raise_for_status()
        return r.json()

    def rename_conversation(self, cid: str, title: str) -> None:
        self._http.patch(f"/conversations/{cid}", json={"title": title}).raise_for_status()

    def delete_conversation(self, cid: str) -> None:
        self._http.delete(f"/conversations/{cid}").raise_for_status()

    def list_messages(self, cid: str, page: int = 1) -> dict:
        return self._get(f"/conversations/{cid}/messages", page=page)

    def send_message(self, cid: str, content: str,
                     attachments: list[str] | None = None) -> dict:
        r = self._post(f"/conversations/{cid}/messages",
                       {"content": content, "attachments": attachments})
        r.raise_for_status()
        return r.json()

    def cancel(self, cid: str) -> None:
        self._post(f"/conversations/{cid}/cancel").raise_for_status()

    def pending_tool_calls(self) -> list[dict]:
        return self._get("/tool-calls/pending")["items"]

    def decide_tool_call(self, tcid: str, decision: str,
                         remember_scope: str | None = None) -> None:
        r = self._post(f"/tool-calls/{tcid}/decision",
                       {"decision": decision, "remember_scope": remember_scope})
        r.raise_for_status()

    def get_settings(self) -> dict:
        return self._get("/settings")

    def update_settings(self, patch: dict) -> dict:
        r = self._http.put("/settings", json=patch)
        r.raise_for_status()
        return r.json()

    def write_api_key(self, provider: str, api_key: str) -> None:
        self._post("/settings/api-key", {"provider": provider, "api_key": api_key}).raise_for_status()

    def test_api_key(self) -> dict:
        return self._post("/settings/api-key/test").json()

    def delete_api_key(self) -> None:
        self._http.delete("/settings/api-key").raise_for_status()

    def list_audit(self, page: int = 1, action: str | None = None) -> dict:
        return self._get("/audit-logs", page=page, action=action)

    def export_audit(self, dest: Path) -> None:
        with self._http.stream("GET", "/audit-logs/export") as r:
            r.raise_for_status()
            dest.write_bytes(r.read())

    # ------------------------------------------------ WS
    def start_events(self, on_event: Callable[[dict[str, Any]], None]) -> None:
        """事件流转发到 GLib 主循环（websocket 线程 → idle_add）。"""
        import threading

        import gi

        gi.require_version("GLib", "2.0")
        from gi.repository import GLib

        self._on_event = on_event

        def pump() -> None:
            try:
                import websocket  # websocket-client（deb: python3-websocket）

                url = self.base_url.replace("http", "ws") + f"/ws?token={self.token}"
                ws = websocket.create_connection(url, timeout=60)
                ws.settimeout(60)
                while True:
                    try:
                        raw = ws.recv()
                    except Exception:  # noqa: BLE001 —— 超时后重连
                        ws.close()
                        GLib.timeout_add(1000, lambda: None)
                        ws = websocket.create_connection(url, timeout=60)
                        continue
                    if raw:
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        GLib.idle_add(self._dispatch, event)
            except Exception:  # noqa: BLE001
                pass

        t = threading.Thread(target=pump, daemon=True)
        t.start()

    def _dispatch(self, event: dict[str, Any]) -> bool:
        if self._on_event:
            self._on_event(event)
        return False  # 单次 idle 回调

    # ------------------------------------------------ 草稿（PRD 5.3）
    def save_draft(self, cid: str, text: str) -> None:
        state = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
        d = Path(state) / "lingos" / "drafts"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{cid}.txt").write_text(text, encoding="utf-8")

    def load_draft(self, cid: str) -> str:
        state = os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state"))
        p = Path(state) / "lingos" / "drafts" / f"{cid}.txt"
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            return ""

    def close(self) -> None:
        self._http.close()
