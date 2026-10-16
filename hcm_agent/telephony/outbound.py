"""Placing outbound calls through Azure Communication Services (ACS) Call Automation.

Shared by clara-call and the call-request Azure Function. ACS dials the patient and sends call
events (connected, speech recognized, disconnected, ...) to the Clara server's callback URL.
"""

import base64
import json
import time
import urllib.error
import urllib.request
from typing import Optional, Sequence
from urllib.parse import urlencode

from azure.communication.callautomation import CallAutomationClient, PhoneNumberIdentifier

from ..call_reasons import MAX_REASON_CHARS
from ..config import Settings
from ..workflows import CareOutreachGraph, OutreachResult, outreach_request_from_member
from ..workflows.member_data import identity_record_for_phone

WAKE_TIMEOUT_SECONDS = 120
MAX_RISK_DRIVERS = 5
MAX_DRIVER_CHARS = 100


class CallNotAllowed(ValueError):
    """The number isn't on ALLOWED_CALL_NUMBERS."""


class CallNotAuthorized(ValueError):
    """The pre-call policy graph did not issue an authorization for this dial attempt."""


def place_member_call(settings: Settings, base_url: str, to: str, name: str = "there",
                      risk_drivers=None, *, reason="", on_wait=None, llm=None, client=None) -> str:
    """CLI/Function entry point: authorize the stored member, then let GPT invoke the ACS tool."""
    from threading import Lock

    from langchain_core.tools import tool

    from ..agent.llm import create_llm
    from ..workflows.graph import run_agent

    check_allowed(settings, to)
    member = identity_record_for_phone(to)
    if not member:
        raise CallNotAllowed("No unique member record exists for this phone number")
    llm = llm or create_llm(settings)
    policy = CareOutreachGraph(llm=llm).pre_call(outreach_request_from_member(member, member["tenant_id"]))
    if not policy.allowed:
        raise CallNotAllowed(policy.reason)
    call_id = None
    lock = Lock()

    @tool
    def start_outbound_call() -> dict:
        """Dial the authorized member once using ACS. No other destination may be supplied."""
        nonlocal call_id
        with lock:
            if call_id is None:
                call_id = place_policy_authorized_call(settings, base_url, to, policy, name, risk_drivers,
                                                       client=client, on_wait=on_wait, reason=reason)
        return {"started": True, "call_connection_id": call_id}

    try:
        run_agent(llm.model, [start_outbound_call],
                  "Invoke start_outbound_call for this authorized request, then report its actual result.",
                  [{"role": "user", "content": "Start the authorized outreach call."}],
                  required_tool="start_outbound_call", max_rounds=1)
    except Exception:
        if call_id is None:
            raise
        # A failed model review must not retry a call that ACS already accepted.
    if call_id is None:
        raise CallNotAllowed("The call tool did not complete")
    return call_id


def encode_call_context(name: str, risk_drivers: Sequence[str] = (), reason: str = "") -> str:
    """Pack the patient's name, risk drivers and the reason for the call into one URL-safe value
    (letters, digits, '-' and '_').

    Free text such as "HbA1c above 7.5%" is fragile in ordinary query parameters on a callback
    URL that the phone service calls back, so it travels as base64url-encoded JSON instead."""
    context = {"name": name, "drivers": [d[:MAX_DRIVER_CHARS] for d in risk_drivers][:MAX_RISK_DRIVERS]}
    if reason:
        context["for"] = reason[:MAX_REASON_CHARS]
    return base64.urlsafe_b64encode(json.dumps(context, separators=(",", ":")).encode()).decode().rstrip("=")


def decode_call_context(value: str) -> tuple[str, list[str], str]:
    """Inverse of encode_call_context: (name, risk drivers, reason). Returns ("there", [], "") for
    anything malformed. An empty reason means the default one."""
    try:
        context = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        name = context.get("name")
        drivers = context.get("drivers", [])
        reason = context.get("for", "")
        if not isinstance(name, str) or not isinstance(drivers, list) or not isinstance(reason, str):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        return "there", [], ""
    drivers = [d.strip()[:MAX_DRIVER_CHARS] for d in drivers if isinstance(d, str) and d.strip()]
    return (name.strip()[:60] or "there"), drivers[:MAX_RISK_DRIVERS], reason.strip()[:MAX_REASON_CHARS]


def to_e164(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 10:
        digits = "1" + digits
    return "+" + digits


def check_allowed(settings: Settings, to: str) -> None:
    """Refuse numbers outside ALLOWED_CALL_NUMBERS. An empty list allows any number (clara-call only;
    the Azure Function refuses to start without a list)."""
    if not settings.allowed_call_numbers:
        return
    allowed = {to_e164(n) for n in settings.allowed_call_numbers}
    if to_e164(to) not in allowed:
        raise CallNotAllowed(f"{to_e164(to)} is not in ALLOWED_CALL_NUMBERS")


def wake_server(base_url: str, timeout_seconds: int = WAKE_TIMEOUT_SECONDS, on_wait=None) -> None:
    """Wait until the server answers, so a sleeping host (e.g. Azure Free tier) is awake
    before the first call event arrives."""
    deadline = time.monotonic() + timeout_seconds
    announced = False
    while True:
        try:
            with urllib.request.urlopen(base_url + "/", timeout=15) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        if time.monotonic() > deadline:
            raise TimeoutError(f"{base_url} didn't respond within {timeout_seconds}s. Is the server running?")
        if on_wait and not announced:
            on_wait()
            announced = True
        time.sleep(3)


def callback_url(settings: Settings, base_url: str, name: str, risk_drivers: Sequence[str] = (),
                 reason: str = "") -> str:
    """Where ACS sends this call's events. The secret key authorizes them; ctx carries the patient."""
    context = encode_call_context(name, risk_drivers, reason)
    return f"{base_url.rstrip('/')}/acs/{settings.phone_webhook_key}/events?{urlencode({'ctx': context})}"


def place_call(settings: Settings, base_url: str, to: str, name: str = "there",
               risk_drivers: Optional[Sequence[str]] = None, client: Optional[CallAutomationClient] = None,
               wake: bool = True, on_wait=None, reason: str = "") -> str:
    """Ask ACS to call `to` and connect them to Clara. Returns the ACS call connection ID."""
    check_allowed(settings, to)
    base_url = base_url.rstrip("/")
    if wake:
        wake_server(base_url, on_wait=on_wait)

    client = client or CallAutomationClient.from_connection_string(settings.acs_connection_string)
    call = client.create_call(
        target_participant=PhoneNumberIdentifier(to_e164(to)),
        callback_url=callback_url(settings, base_url, name, risk_drivers or [], reason),
        source_caller_id_number=PhoneNumberIdentifier(to_e164(settings.acs_phone_number)),
        # The Azure AI Services resource ACS uses for text-to-speech and speech recognition.
        cognitive_services_endpoint=settings.acs_cognitive_services_endpoint,
    )
    return call.call_connection_id


def place_policy_authorized_call(settings: Settings, base_url: str, to: str, policy: OutreachResult,
                                 name: str = "there", risk_drivers: Optional[Sequence[str]] = None,
                                 client: Optional[CallAutomationClient] = None, wake: bool = True,
                                 on_wait=None, reason: str = "") -> str:
    """Place a dial only when ``CareOutreachGraph`` reached ``ready_to_dial``.

    This is the intended production boundary between policy orchestration and
    ACS.  The caller receives the graph result from an authoritative workflow;
    the adapter refuses blocked results before it wakes the server or contacts
    ACS.  A production replacement should additionally validate the token at a
    centralized authorization service.
    """
    if not policy.allowed or policy.terminal_node != "ready_to_dial" or not policy.authorization:
        raise CallNotAuthorized("outbound dial requires a current pre-call authorization")
    return place_call(settings, base_url, to, name, risk_drivers, client, wake, on_wait, reason)
