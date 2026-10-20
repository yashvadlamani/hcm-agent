"""Process-local response-latency circuit breaker for phone calls.

This is deliberately deterministic: callers cannot ask the model to waive a
deadline.  A production deployment should replace this in-memory state with a
shared, bounded store if it runs more than one server process.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class LatencyDecision:
    allowed: bool
    circuit_open: bool
    failure_count: int
    retry_after_seconds: int


class ResponseLatencyCircuit:
    """Open briefly after repeated failed or over-deadline model turns."""

    def __init__(self, *, failure_threshold: int = 3, cooldown_seconds: int = 60) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures = 0
        self._open_until = 0.0
        self._lock = threading.Lock()

    def start(self, now: float | None = None) -> LatencyDecision:
        current = time.monotonic() if now is None else now
        with self._lock:
            if current >= self._open_until:
                self._open_until = 0.0
            remaining = max(0, int(self._open_until - current))
            return LatencyDecision(not bool(remaining), bool(remaining), self._failures, remaining)

    def succeed(self) -> LatencyDecision:
        with self._lock:
            self._failures = 0
            self._open_until = 0.0
            return LatencyDecision(True, False, 0, 0)

    def fail(self, now: float | None = None) -> LatencyDecision:
        current = time.monotonic() if now is None else now
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._open_until = current + self.cooldown_seconds
            remaining = max(0, int(self._open_until - current))
            return LatencyDecision(not bool(remaining), bool(remaining), self._failures, remaining)


# The call server and safety tool share this one process-local policy state.
response_latency_circuit = ResponseLatencyCircuit()
