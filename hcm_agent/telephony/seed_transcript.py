"""Seed one explicitly fictional completed call for testing the local /live history UI."""

from __future__ import annotations

import time

from .transcripts import transcript_store

SAMPLE_CALL_ID = "sample-transcript-demo-001"


def sample_events(now: float | None = None) -> list[dict]:
    """Build a five-turn, non-PHI transcript with every UI-supported event type."""
    started = now if now is not None else time.time() - 180
    events = []

    def add(offset: int, event_type: str, **data) -> None:
        events.append({"id": len(events) + 1, "boot": "sample", "ts": started + offset,
                       "call": SAMPLE_CALL_ID, "type": event_type, **data})

    add(0, "call_started", name="Taylor Demo (fictional)", reason="diabetes management",
        drivers=["Fictional demo: overdue routine diabetes follow-up"], sentiment=0.50)
    add(1, "clara", kind="greeting", text=(
        "Hello, this is Clara, an automated care management assistant with Blue Cross Blue Shield. "
        "Could you please tell me your full name?"))
    add(12, "patient", text="My name is Taylor Demo.", confidence=0.96)
    add(13, "identity", status="confirmed", spoke_with="Taylor Demo")
    add(14, "clara", kind="opening", latency=0.8,
        text="Thank you. For verification, could you please tell me your date of birth, "
             "including the month, day, and year?")
    add(27, "patient", text="January 2, 1990.", confidence=0.94)
    add(29, "clara", kind="opening", latency=1.1,
        text="Thank you for verifying your identity. How have you been feeling lately?")
    add(43, "patient", text="I have been doing okay, but scheduling routine visits has been difficult.",
        confidence=0.91)
    add(43, "thinking")
    add(45, "sentiment", value=0.58, change=0.08)
    add(45, "clara", kind="reply", latency=1.9,
        text="Finding time for routine visits can be difficult. "
             "Is there a day or time that tends to work best for you?")
    add(62, "patient", text="Weekday mornings are usually easier for me.", confidence=0.93)
    add(62, "thinking")
    add(64, "sentiment", value=0.68, change=0.10)
    add(64, "agent_trace", entries=[
        {"name": "invoke_agent capability_3_identity", "kind": "agent", "capability": "Capability 3 · Identity",
         "tool": "", "source": "", "duration_ms": 620, "success": True, "at": started + 29, "turn": 1},
        {"name": "execute_tool verify_full_name", "kind": "tool", "capability": "Capability 3 · Identity",
         "tool": "verify_full_name", "source": "", "duration_ms": 2, "success": True, "at": started + 14, "turn": 1},
        {"name": "execute_tool verify_dob", "kind": "tool", "capability": "Capability 3 · Identity",
         "tool": "verify_dob", "source": "", "duration_ms": 2, "success": True, "at": started + 29, "turn": 2},
        {"name": "invoke_agent capability_8_security", "kind": "agent", "capability": "Capability 8 · Security",
         "tool": "", "source": "", "duration_ms": 4, "success": True, "at": started + 64, "turn": 4},
        {"name": "invoke_agent capability_7_safety", "kind": "agent", "capability": "Capability 7 · Safety",
         "tool": "", "source": "", "duration_ms": 3, "success": True, "at": started + 64, "turn": 4},
        {"name": "invoke_agent care_model", "kind": "agent", "capability": "Care model",
         "tool": "", "source": "", "duration_ms": 480, "success": True, "at": started + 64, "turn": 4},
        {"name": "execute_tool provider_directory_search", "kind": "tool",
         "capability": "Capability 6 · Care navigation",
         "tool": "provider_directory_search", "source": "Provider directory", "duration_ms": 18, "success": True,
         "at": started + 64, "turn": 4},
    ])
    add(64, "clara", kind="closing", latency=1.6,
        text="Weekday mornings are a useful preference to note for your care team. "
             "Would you like a short feedback form by text message?")
    add(79, "patient", text="Yes, please.", confidence=0.98)
    add(79, "thinking")
    add(80, "sentiment", value=0.82, change=0.14)
    add(80, "closing", reason="Patient's needs addressed")
    add(80, "feedback", requested=True)
    add(80, "clara", kind="goodbye", latency=0.5,
        text="I've noted that you'd like the feedback form. Goodbye.")
    add(82, "call_ended", reason="Sample transcript complete")
    return events


def main() -> None:
    transcript_store.save(SAMPLE_CALL_ID, sample_events())
    print("Saved one fictional five-turn sample transcript for /live.")


if __name__ == "__main__":
    main()
