"""Local, durable transcript history for Clara's demo phone server.

The store intentionally lives on the server filesystem, not in the event feed. It
is for local/demo review only and must be replaced with an approved, encrypted
record system before handling real member conversations.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "transcripts" / "clara_calls.sqlite3"
MAX_TRANSCRIPTS = 50


class TranscriptStore:
    """Store complete ended-call event streams and retain only the newest local records."""

    def __init__(self, path: Path | None = None, *, max_records: int = MAX_TRANSCRIPTS) -> None:
        self.path = path or Path(os.environ.get("CLARA_TRANSCRIPT_DB", str(DEFAULT_DB)))
        self.max_records = max_records
        self._lock = threading.Lock()

    def save(self, call_id: str, events: list[dict[str, Any]]) -> None:
        """Upsert one completed call after its `call_ended` event has been published."""
        if not events:
            return
        started = next((event for event in events if event.get("type") == "call_started"), {})
        ended = next((event for event in reversed(events) if event.get("type") == "call_ended"), {})
        name = str(started.get("name", "Unknown caller"))[:200]
        status = "emergency" if any(event.get("type") == "emergency" for event in events) else "ended"
        ended_at = float(ended.get("ts", events[-1].get("ts", 0)))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path) as connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS call_transcripts (
                        call_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        status TEXT NOT NULL,
                        ended_at REAL NOT NULL,
                        events_json TEXT NOT NULL
                    )
                """)
                connection.execute("""
                    INSERT INTO call_transcripts (call_id, name, status, ended_at, events_json)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(call_id) DO UPDATE SET
                      name=excluded.name, status=excluded.status, ended_at=excluded.ended_at,
                      events_json=excluded.events_json
                """, (call_id, name, status, ended_at, json.dumps(events, separators=(",", ":"))))
                connection.execute("""
                    DELETE FROM call_transcripts WHERE call_id IN (
                        SELECT call_id FROM call_transcripts ORDER BY ended_at DESC LIMIT -1 OFFSET ?
                    )
                """, (self.max_records,))

    def recent(self, *, limit: int = MAX_TRANSCRIPTS) -> list[dict[str, Any]]:
        """Return newest completed calls, with malformed local records safely skipped."""
        if not self.path.is_file():
            return []
        with self._lock:
            with sqlite3.connect(self.path) as connection:
                rows = connection.execute("""
                    SELECT call_id, name, status, ended_at, events_json FROM call_transcripts
                    ORDER BY ended_at DESC LIMIT ?
                """, (min(max(1, limit), self.max_records),)).fetchall()
        records = []
        for call_id, name, status, ended_at, raw_events in rows:
            try:
                events = json.loads(raw_events)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(events, list):
                records.append({"call": call_id, "name": name, "status": status,
                                "ended_at": ended_at, "events": events})
        return records


transcript_store = TranscriptStore()
