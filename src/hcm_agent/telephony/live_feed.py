"""In-memory event feed behind the local live-call view (/live).

Events are kept only in memory: they disappear when the server restarts.
"""

import itertools
import json
import queue
import secrets
import threading
import time
from typing import Iterator

MAX_HISTORY = 500
# Lets the page tell a server restart (ids start over) from a dropped connection.
BOOT_ID = secrets.token_hex(4)

_lock = threading.Lock()
_ids = itertools.count(1)
_history: list[dict] = []
_subscribers: list[queue.Queue] = []


def publish(call_sid: str, event_type: str, **data) -> None:
    event = {"id": next(_ids), "boot": BOOT_ID, "ts": time.time(),
             "call": call_sid, "type": event_type, **data}
    with _lock:
        _history.append(event)
        del _history[:-MAX_HISTORY]
        for subscriber in _subscribers:
            subscriber.put(event)


def stream() -> Iterator[str]:
    """Server-sent events: replay the backlog, then push new events as they happen."""
    subscriber: queue.Queue = queue.Queue()
    with _lock:
        backlog = list(_history)
        _subscribers.append(subscriber)
    try:
        yield ": connected\n\n"  # flush headers now so the browser shows "Connected" right away
        for event in backlog:
            yield _format(event)
        while True:
            try:
                yield _format(subscriber.get(timeout=15))
            except queue.Empty:
                yield ": keep-alive\n\n"
    finally:
        with _lock:
            _subscribers.remove(subscriber)


def history() -> list[dict]:
    with _lock:
        return list(_history)


def clear() -> None:
    with _lock:
        _history.clear()


def _format(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"
