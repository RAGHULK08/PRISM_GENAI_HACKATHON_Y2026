"""clock.py
Injectable clock abstraction. Guarantees deterministic evaluation under the virtual harness.
Never call time.time() or datetime.now() directly — always inject Clock.
"""
from abc import ABC, abstractmethod
import asyncio
import time


class Clock(ABC):
    @abstractmethod
    def now_ms(self) -> int:
        """Returns current timestamp in milliseconds."""
        pass

    @abstractmethod
    async def sleep_ms(self, ms: int) -> None:
        """Asynchronously waits for ms milliseconds on this clock."""
        pass


class RealClock(Clock):
    """Wall-clock implementation for production use."""
    def now_ms(self) -> int:
        return int(time.monotonic() * 1000)

    async def sleep_ms(self, ms: int) -> None:
        await asyncio.sleep(ms / 1000.0)


class VirtualClock(Clock):
    """Event-driven virtual clock for deterministic replay and scoring.

    The harness drives this clock by calling advance_to(). Any coroutine
    awaiting sleep_ms() is woken up deterministically when the clock crosses
    its target, with no real wall-clock delay.
    """
    def __init__(self, start_ms: int = 0):
        self._current_ms = start_ms
        self._waiters: list[tuple[int, asyncio.Future]] = []

    def now_ms(self) -> int:
        return self._current_ms

    def advance_to(self, target_ms: int) -> None:
        """Advance the clock to target_ms, waking all due sleepers."""
        if target_ms < self._current_ms:
            return
        self._current_ms = target_ms
        ready = [w for w in self._waiters if w[0] <= self._current_ms]
        self._waiters = [w for w in self._waiters if w[0] > self._current_ms]
        for _, fut in ready:
            if not fut.done():
                fut.set_result(None)

    def advance_by(self, delta_ms: int) -> None:
        self.advance_to(self._current_ms + delta_ms)

    async def sleep_ms(self, ms: int) -> None:
        target = self._current_ms + ms
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._waiters.append((target, fut))
        self._waiters.sort(key=lambda x: x[0])
        await fut
