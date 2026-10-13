"""熔断器状态机（PRD 5.4 M3）。

closed --连续 5 次失败--> open --60s--> half_open --1 个探测成功--> closed
                                                    └--探测失败--> open
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """熔断 OPEN 期间所有请求立即失败（不发真实请求）。"""

    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"llm circuit open, retry after {retry_after:.0f}s")


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        open_seconds: float = 60.0,
        clock: Any = time.monotonic,
    ):
        self.failure_threshold = failure_threshold
        self.open_seconds = open_seconds
        self._clock = clock
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self._opened_at = 0.0
        self._probe_inflight = False

    @property
    def is_call_permitted(self) -> bool:
        """是否允许发起真实请求（half_open 只放 1 个探测）。"""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if self._clock() - self._opened_at >= self.open_seconds:
                self.state = CircuitState.HALF_OPEN
                self._probe_inflight = False
                return True
            return False
        # HALF_OPEN：仅允许一个在途探测
        if self._probe_inflight:
            return False
        return True

    def before_call(self) -> None:
        if self.state == CircuitState.HALF_OPEN:
            self._probe_inflight = True

    def record_success(self) -> None:
        self.failure_count = 0
        self._probe_inflight = False
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        if self.state == CircuitState.HALF_OPEN:
            self._trip()
            return
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self._trip()

    def _trip(self) -> None:
        self.state = CircuitState.OPEN
        self._opened_at = self._clock()
        self._probe_inflight = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "retry_after": (
                max(0.0, self.open_seconds - (self._clock() - self._opened_at))
                if self.state != CircuitState.CLOSED
                else 0.0
            ),
        }


class AsyncCircuitBreaker(CircuitBreaker):
    """带 asyncio 锁的线程安全包装（half_open 单探测在并发下也要正确）。"""

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self._lock:
            return self.is_call_permitted and (self.before_call() or True)

    async def success(self) -> None:
        async with self._lock:
            self.record_success()

    async def failure(self) -> None:
        async with self._lock:
            self.record_failure()
