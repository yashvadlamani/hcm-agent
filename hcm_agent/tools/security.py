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
import re
import threading
import time
import unicodedata
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


# ---- Sensitive data: rule-based classification and redaction. Found values are never returned. ----

_IDENTIFIERS = {  # checked in this order, so a card number is not half-read as a phone number
    "payment_card": re.compile(r"(?<!\d)(?:\d[ -]?){12,15}\d(?!\d)"),
    "phone": re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)"),
    "ssn": re.compile(r"(?<!\d)\d{3}[- ]?\d{2}[- ]?\d{4}(?!\d)"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    "date_of_birth": re.compile(
        r"\b(?:born(?: on)?|date of birth(?: is)?|dob(?: is)?|birthday(?: is)?)\s+(?:on\s+)?"
        r"(?:[A-Za-z]+ \d{1,2}(?:st|nd|rd|th)?,? \d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})",
        re.IGNORECASE),
}
_HEALTH = re.compile(
    r"\b(diabet\w*|insulin|metformin|a1c|hba1c|blood sugar|glucose|medication\w*|medicine\w*|prescription\w*|"
    r"refill\w*|diagnos\w*|hospital\w*|emergency room|surgery|symptom\w*|dos(?:e|es|age)|pharmac\w*|doctor\w*|"
    r"endocrinolog\w*|neuropathy|blood pressure|depress\w*|anxiety|chest pain|dizz\w*)\b", re.IGNORECASE)
_FINANCIAL = re.compile(
    r"\b(co-?pay\w*|deductible\w*|premium\w*|bills?|afford\w*|insurance|bank account|credit card|\d+ dollars)\b"
    r"|\$\s?\d", re.IGNORECASE)


def redact(text: str, member_id: str = "") -> str:
    """Replace direct identifiers (card, phone, SSN, email, stated date of birth, member ID) with labels."""
    for label, pattern in _IDENTIFIERS.items():
        text = pattern.sub(f"[{label.replace('_', ' ')}]", text)
    if member_id and member_id not in ("unresolved", "unknown"):
        text = text.replace(member_id, "[member id]")
    return text


def classify(text: str, member_id: str = "") -> dict[str, Any]:
    """Label a text by the most sensitive kind of data in it, and return a copy safe to store."""
    identifiers = [label for label, pattern in _IDENTIFIERS.items() if pattern.search(text)]
    if member_id and member_id not in ("unresolved", "unknown") and member_id in text:
        identifiers.append("member_id")
    categories = identifiers + (["health"] if _HEALTH.search(text) else []) + (
        ["financial"] if _FINANCIAL.search(text) else [])
    level = ("direct_identifier" if identifiers else "health_information" if "health" in categories
             else "financial" if "financial" in categories else "none")
    return {"classification": level, "categories": categories, "identifier_count": len(identifiers),
            "redacted_text": redact(text, member_id)[:1000]}


# ---- Prompt injection: rule-based detection of attempts to take over or probe the assistant ----

_INJECTION = {
    "instruction_override": [
        r"\b(ignore|disregard|forget|override|bypass)\b.{0,30}\b(previous|prior|above|earlier|all|any|your|system|safety)\b"
        r".{0,20}\b(instructions?|rules?|prompts?|guidelines?|guardrails?|restrictions?|programming)\b",
        r"\bnew (instructions?|rules?)\s*:", r"\bfrom now on,? you (are|will|must|should)\b",
        r"\b(stop|quit) being clara\b",
    ],
    "role_hijack": [
        r"\byou are now (a|an|my|the|in|dan|free|unrestricted)\b", r"\b(pretend|imagine) (to be|you are|you're)\b",
        r"\b(act|behave|respond|roleplay|role-play) as (a |an |my |the )?"
        r"(doctor|physician|pharmacist|nurse|clinician|admin\w*|developer|system|dan|different|unrestricted)\b",
        r"\b(developer|debug|god|admin|jailbreak) mode\b", r"\bjailbreak\b", r"\bdo anything now\b",
    ],
    "prompt_exfiltration": [
        r"\b(reveal|show|print|repeat|recite|display|output|tell me|what(?:'s| is| are))\b.{0,25}"
        r"\b(system|hidden|initial|original|secret)?\s*(prompt|instructions|guidelines|rules you (were|are) given)\b",
        r"\bsystem prompt\b", r"\breveal (your |the )?secrets?\b",
    ],
    "data_exfiltration": [
        r"\b(give|tell|read|show|list|send|look up)\b.{0,25}\b(another|other|someone else'?s?|all|every)\b.{0,15}"
        r"\b(members?|patients?|people|callers?)(?:'s?)?\b.{0,20}\b(data|records?|information|details|"
        r"dates? of birth|phone numbers?|names?)\b",
    ],
    "safety_bypass": [
        r"\b(bypass|skip|disable|turn off|ignore)\b.{0,20}"
        r"\b(verification|identity check|guardrails?|safety|filters?)\b",
        r"\b(mark|treat|consider) (me|this caller|the caller) as verified\b", r"\bwithout verif\w+\b",
    ],
    "tool_abuse": [
        r"\b(call|invoke|run|execute|use) (the |a )?(tool|function|api)\b",
        r"\b[a-z]{3,}(?:_[a-z0-9]{2,}){1,}\b",  # snake_case names: people don't say these on the phone
    ],
    "markup": [
        r"<\s*/?\s*(system|assistant|instructions?)\s*>", r"\[\s*(system|inst)\s*\]",
        r"(^|\n)\s*(system|assistant|developer)\s*:", r"```", r"#{2,}\s*(system|instruction)",
    ],
}
_INJECTION_PATTERNS = {category: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
                       for category, patterns in _INJECTION.items()}
_INVISIBLE = re.compile("[\u200b-\u200f\u2060\ufeff\u00ad]")


def detect_injection(text: str) -> dict[str, Any]:
    """Look for attempts to override instructions, change Clara's role, extract her prompt or other
    members' data, bypass safety checks, or drive tools. Any match makes the text unsafe."""
    normalized = " ".join(_INVISIBLE.sub("", unicodedata.normalize("NFKC", text)).split())
    categories, sanitized = [], normalized
    for category, patterns in _INJECTION_PATTERNS.items():
        if any(pattern.search(normalized) for pattern in patterns):
            categories.append(category)
            for pattern in patterns:
                sanitized = pattern.sub("[removed]", sanitized)
    return {"safe": not categories, "injection_detected": bool(categories), "categories": categories,
            "risk": "high" if categories else "none", "sanitized_text": sanitized[:1000]}


# ---- Logs: the same redaction, applied to every log line before it is written ----

class RedactingLogFilter(logging.Filter):
    """Removes direct identifiers from log records. Attach it to handlers, so every logger is covered."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            cleaned = redact(message)
            if cleaned != message:
                record.msg, record.args = cleaned, ()
        except Exception:  # a log line must never be lost because redaction failed
            pass
        return True


# ---- Prompt context: only what the model or a tool needs, and no direct identifiers ----

PROMPT_KEYS = ("name", "risk_drivers", "call_reason", "local_demo_context")  # what the system prompt reads
IDENTIFIER_KEYS = frozenset({"date_of_birth", "dob", "ssn", "phone", "phone_number", "email", "address",
                             "member_id", "tenant_id", "call_id"})
MAX_TEXT, MAX_ITEMS, MAX_DEPTH = 2000, 10, 4


def _trimmed(value: Any, depth: int = 0) -> Any:
    """Redact and cap a value: long texts cut, long lists shortened, identifier fields dropped."""
    if isinstance(value, str):
        return redact(value)[:MAX_TEXT]
    if isinstance(value, (list, tuple)):
        return [_trimmed(item, depth + 1) for item in list(value)[:MAX_ITEMS]] if depth < MAX_DEPTH else []
    if isinstance(value, dict):
        return ({key: _trimmed(item, depth + 1) for key, item in value.items()
                 if str(key).lower() not in IDENTIFIER_KEYS} if depth < MAX_DEPTH else {})
    return value


def minimize(context: dict[str, Any], purpose: str = "tools") -> dict[str, Any]:
    """Reduce a call context to what its use needs. For "prompt": only the fields the system prompt
    reads. For "tools": everything except identifier fields. Texts are redacted and capped either way."""
    kept = ({key: context[key] for key in PROMPT_KEYS if key in context} if purpose == "prompt"
            else {key: value for key, value in context.items() if str(key).lower() not in IDENTIFIER_KEYS})
    minimized = {key: (value if key == "name" else _trimmed(value)) for key, value in kept.items()}
    return {"context": minimized, "purpose": purpose, "removed": sorted(set(context) - set(minimized))}


# ---- Untrusted content: retrieved passages and tool output are data, never instructions ----

# Not "tool_abuse" or "data_exfiltration": tool output legitimately contains field names and records.
CONTENT_CATEGORIES = ("instruction_override", "role_hijack", "prompt_exfiltration", "safety_bypass", "markup")


def sanitize(content: Any, _found: Optional[set] = None, _depth: int = 0) -> dict[str, Any]:
    """Remove instruction-like text from every string in a value (text, list or nested record)."""
    found: set = _found if _found is not None else set()

    def clean(value: Any, depth: int) -> Any:
        if isinstance(value, str):
            text = " ".join(_INVISIBLE.sub("", unicodedata.normalize("NFKC", value)).split()) \
                if _INVISIBLE.search(value) else value
            for category in CONTENT_CATEGORIES:
                for pattern in _INJECTION_PATTERNS[category]:
                    if pattern.search(text):
                        found.add(category)
                        text = pattern.sub("[removed]", text)
            return text
        if depth >= 8:
            return value
        if isinstance(value, list):
            return [clean(item, depth + 1) for item in value]
        if isinstance(value, dict):
            return {key: clean(item, depth + 1) for key, item in value.items()}
        return value

    cleaned = clean(content, _depth)
    return {"content": cleaned, "sanitized": bool(found), "categories": sorted(found)}
