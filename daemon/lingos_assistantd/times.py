"""时间规约（PRD 11.1）：数据库与 API 一律 ISO8601 UTC 字符串（...Z 结尾）。"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Aware UTC 当前时间。禁止 datetime.utcnow()（3.12 已弃用）。"""
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="milliseconds").replace("+00:00", "Z")
