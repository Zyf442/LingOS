"""UUIDv7 生成器（时间有序，PRD 11.1：主键一律 UUIDv7 字符串，TEXT 存储）。"""

from __future__ import annotations

import os
import time
import uuid

_last_ms = 0
_seq = 0


def uuid7() -> str:
    """生成 UUIDv7 并返回规范字符串形式。

    布局：unix_ts_ms(48bit) | ver(4)=0x7 | rand_a(12bit) | var(2)=0b10 | rand_b(62bit)
    单调性：同一毫秒内 rand_a 自增（12bit 计数器），保证主键字符串时间有序。
    """
    global _last_ms, _seq
    ts_ms = time.time_ns() // 1_000_000
    if ts_ms == _last_ms:
        _seq = (_seq + 1) & 0xFFF
    else:
        _last_ms = ts_ms
        _seq = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big")

    b = bytearray(16)
    b[0:6] = ts_ms.to_bytes(6, "big")
    b[6] = 0x70 | (_seq >> 8) & 0x0F
    b[7] = _seq & 0xFF
    b[8] = 0x80 | ((rand_b >> 56) & 0x3F)
    b[9:] = (rand_b & ((1 << 56) - 1)).to_bytes(7, "big")
    return str(uuid.UUID(bytes=bytes(b)))
