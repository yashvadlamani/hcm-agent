"""Draft security controls: a durable audit log, a rate limiter and circuit breakers.

These back the seven security tools that can be real without an outside system:
authorize_tool_call, enforce_member_scope, apply_tool_allowlist (they report the tool gateway's
own decisions), audit_event, record_policy_decision (they write to the audit log),
apply_rate_limit and apply_circuit_breaker.

Everything here is process-local. The audit log is kept in memory and, when AUDIT_LOG_PATH is
set, appended to a JSON-lines file. Rate-limit and circuit state are lost on restart and are not
shared between server processes. Audit entries hold names of tools, policies and outcomes and
the member ID: never tool arguments, names, dates of birth, phone numbers or transcripts.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_hex
from typing import Any, Optional

logger = logging.getLogger(__name__)

MAX_AUDIT_ENTRIES_IN_MEMORY = 5000


class AuditLog:
    """An append-only record of tool calls, policy decisions and security events."""

    def __init__(self, log_path: str = ""):
        self.log_path = Path(log_path) if log_path else None
        self.entries: deque[dict[str, Any]] = deque(maxlen=MAX_AUDIT_ENTRIES_IN_MEMORY)
        self._lock = threading.Lock()

    @property
    def durable(self) -> bool:
        return self.log_path is not None

    def record(self, entry_type: str, **fields: Any) -> dict[str, Any]:
        entry = {"id": f"AUD-{token_hex(6).upper()}", "type": entry_type,
                 "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 **{key: value for key, value in fields.items() if value not in (None, "")}}
        with self._lock:
            if self.log_path:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as log:
                    log.write(json.dumps(entry, default=str) + "\n")
            self.entries.append(entry)
        return entry


_audit: Optional[AuditLog] = None


def audit_log() -> AuditLog:
    """The process-wide audit log, configured from the environment on first use."""
    global _audit
    if _audit is None:
        _audit = AuditLog(os.environ.get("AUDIT_LOG_PATH", "").strip())
    return _audit


def use_audit_log(replacement: Optional[AuditLog]) -> None:
    """Swap the audit log (tests), or pass None to re-read the environment on next use."""
    global _audit
    _audit = replacement


class RateLimiter:
    """A sliding-window limit per key: at most `limit` events in any `window_seconds`."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: float = 60, now: Optional[float] = None) -> dict[str, Any]:
        """Count one event for `key` if it is within the limit, and say whether it was allowed."""
        current = time.monotonic() if now is None else now
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and current - events[0] >= window_seconds:
                events.popleft()
            allowed = len(events) < limit
            if allowed:
                events.append(current)
            retry_after = 0 if allowed or not events else max(1, int(window_seconds - (current - events[0]) + 0.999))
            return {"allowed": allowed, "count": len(events), "limit": limit,
                    "window_seconds": window_seconds, "retry_after_seconds": retry_after}


class CircuitBreaker:
    """Stops calling a failing dependency for a while: opens after repeated failures, then retries."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 60) -> None:
        self.failure_threshold, self.cooldown_seconds = failure_threshold, cooldown_seconds
        self._failures, self._open_until = 0, 0.0
        self._lock = threading.Lock()

    def _state(self, current: float) -> dict[str, Any]:
        remaining = max(0, int(self._open_until - current + 0.999)) if current < self._open_until else 0
        return {"allowed": remaining == 0, "circuit_open": remaining > 0, "failure_count": self._failures,
                "retry_after_seconds": remaining}

    def check(self, now: Optional[float] = None) -> dict[str, Any]:
        with self._lock:
            return self._state(time.monotonic() if now is None else now)

    def success(self, now: Optional[float] = None) -> dict[str, Any]:
        with self._lock:
            self._failures, self._open_until = 0, 0.0
            return self._state(time.monotonic() if now is None else now)

    def failure(self, now: Optional[float] = None) -> dict[str, Any]:
        current = time.monotonic() if now is None else now
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._open_until = current + self.cooldown_seconds
            return self._state(current)


_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()
rate_limiter = RateLimiter()  # process-wide, for limits that span calls


def breaker(dependency: str, failure_threshold: int = 3, cooldown_seconds: float = 60) -> CircuitBreaker:
    """The circuit breaker for one named dependency, created on first use."""
    with _breakers_lock:
        if dependency not in _breakers:
            _breakers[dependency] = CircuitBreaker(failure_threshold, cooldown_seconds)
        return _breakers[dependency]


def reset() -> None:
    """Forget all rate-limit and circuit state (tests)."""
    global rate_limiter
    with _breakers_lock:
        _breakers.clear()
    rate_limiter = RateLimiter()
