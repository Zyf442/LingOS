"""熔断器状态机测试（PRD 5.4 M3）。"""

from __future__ import annotations

from lingos_assistantd.core.circuit import AsyncCircuitBreaker, CircuitState


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_closed_allows_all():
    cb = AsyncCircuitBreaker(clock=FakeClock())
    assert cb.is_call_permitted is True


async def test_opens_after_consecutive_failures():
    cb = AsyncCircuitBreaker(failure_threshold=5, open_seconds=60)
    for _ in range(4):
        assert await cb.acquire()
        await cb.failure()
        assert cb.state == CircuitState.CLOSED
    assert await cb.acquire()
    await cb.failure()
    assert cb.state == CircuitState.OPEN
    assert not cb.is_call_permitted


async def test_success_resets_counter():
    cb = AsyncCircuitBreaker(failure_threshold=5)
    for _ in range(4):
        await cb.acquire()
        await cb.failure()
    await cb.acquire()
    await cb.success()
    assert cb.failure_count == 0
    for _ in range(4):
        await cb.acquire()
        await cb.failure()
    assert cb.state == CircuitState.CLOSED  # 5 次阈值未连续达到


async def test_half_open_single_probe():
    clock = FakeClock()
    cb = AsyncCircuitBreaker(failure_threshold=1, open_seconds=60, clock=clock)
    await cb.acquire()
    await cb.failure()
    assert cb.state == CircuitState.OPEN
    clock.t = 61.0
    # 进入 half_open，放 1 个探测
    assert await cb.acquire()
    assert cb.state == CircuitState.HALF_OPEN
    assert not cb.is_call_permitted  # 第二个请求被挡（探测在途）
    await cb.success()
    assert cb.state == CircuitState.CLOSED
    assert cb.is_call_permitted


async def test_half_open_probe_failure_reopens():
    clock = FakeClock()
    cb = AsyncCircuitBreaker(failure_threshold=1, open_seconds=60, clock=clock)
    await cb.acquire()
    await cb.failure()
    clock.t = 100.0
    assert await cb.acquire()  # 探测
    await cb.failure()
    assert cb.state == CircuitState.OPEN
    assert not cb.is_call_permitted  # 100→110 不足 60s
    clock.t = 161.0
    assert await cb.acquire()  # opened_at=100，161>160 再次 half_open 探测


def test_snapshot():
    cb = AsyncCircuitBreaker(clock=FakeClock())
    snap = cb.snapshot()
    assert snap["state"] == "closed"
