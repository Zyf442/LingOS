"""结构化日志 + 脱敏 filter（PRD 10.2、10.1）。

- JSON Lines：{"ts","level","logger","event","conv_id","tool_call_id","msg"}
- journald 托管（systemd user service）；开发模式输出 stderr
- 脱敏：sk-… Key → sk-***；Authorization 头不入日志
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{8,}"),  # DashScope/OpenAI 风格 Key
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}"),  # 会话 token
]


def redact(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        text = pat.sub(lambda m: ("sk-***" if m.group(0).startswith("sk-") else "Bearer ***"), text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.msg = redact(str(record.msg))
            record.args = tuple(
                redact(str(a)) if isinstance(a, str) else a
                for a in (record.args if isinstance(record.args, tuple) else (record.args,))
            )
        else:
            record.msg = redact(str(record.msg))
        return True


class JsonFormatter(logging.Formatter):
    def __init__(self, extra_fields: dict[str, Any] | None = None):
        super().__init__()
        self.extra_fields = extra_fields or {}

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": f"{record.created:.3f}",
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key in ("conv_id", "tool_call_id"):
            v = getattr(record, key, None)
            if v:
                payload[key] = v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        payload.update(self.extra_fields)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO", structured: bool = True) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(RedactingFilter())
    if structured:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
