"""Load demo member policy data and translate it into pre-call graph input."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..tools.identity import normalize_name
from .outreach import OutreachRequest

DEMO_MEMBERS_PATH = Path(__file__).resolve().parents[2] / "data" / "demo_members.json"


def identity_record_for_phone(phone: str) -> dict[str, Any]:
    """Look up the expected phone participant, independent of any spoken identity claim."""
    return _identity_record(phone=phone)


def identity_record_for_name(name: str) -> dict[str, Any]:
    """Select a terminal demo record BEFORE the simulated call begins."""
    return _identity_record(name=name)


def demo_call_context_for_name(name: str) -> dict[str, Any]:
    """Return explicitly fictional demo scenario data for local interactive simulations only."""
    context = identity_record_for_name(name).get("demo_call_context", {})
    return context if context.get("data_status") == "fictional_demo_only" else {}


def _identity_record(phone: str = "", name: str = "") -> dict[str, Any]:
    """Resolve one expected identity from a server-owned record, never a spoken claim.

    MEMBER_DATA_PATH can point to a separately provisioned member file using the
    demo dataset schema. Missing, invalid, or ambiguous records fail closed.
    """
    def digits(value: str) -> str:
        number = "".join(c for c in value if c.isdigit())
        return "1" + number if len(number) == 10 else number

    try:
        dataset = json.loads(Path(os.environ.get("MEMBER_DATA_PATH", str(DEMO_MEMBERS_PATH))).read_text())
        normalized_name = normalize_name(name)
        matches = [member for member in dataset["members"] if
                   (bool(phone) and digits(member["phone"]) == digits(phone)) or
                   (bool(name) and (
                       normalize_name(member["name"]) == normalized_name or
                       (" " not in normalized_name and
                        normalize_name(member["name"]).split(" ", 1)[0] == normalized_name)
                   ))]
        if len(matches) != 1 or not dataset.get("tenant_id"):
            return {}
        member = matches[0]
        if not all(isinstance(member.get(key), str) and member[key] for key in
                   ("member_id", "name", "date_of_birth")):
            return {}
        return {**member, "tenant_id": dataset["tenant_id"]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def load_demo_members(path: Path = DEMO_MEMBERS_PATH) -> list[dict[str, Any]]:
    """Load the versioned demo dataset; it is not a production member-record source."""
    return json.loads(path.read_text(encoding="utf-8"))["members"]


def outreach_request_from_member(member: dict[str, Any], tenant_id: str,
                                 now: datetime | None = None) -> OutreachRequest:
    """Build a pre-call request using the member's IANA time zone and outreach policy."""
    communication = member["communication"]
    outreach = member["outreach"]
    current = now or datetime.now(timezone.utc)
    local_hour = current.astimezone(ZoneInfo(communication["local_timezone"])).hour
    return OutreachRequest(
        member_id=member["member_id"],
        phone=member["phone"],
        tenant_id=tenant_id,
        consent=outreach["consent"],
        do_not_call=outreach["do_not_call"],
        local_hour=local_hour,
        outreach_attempts_7d=outreach["outreach_attempts_7d"],
        max_outreach_attempts_7d=outreach["max_outreach_attempts_7d"],
        member_active=outreach["member_active"],
        language=communication["language"],
        window_start_hour=communication["calling_window"]["start_hour"],
        window_end_hour=communication["calling_window"]["end_hour"],
    )
