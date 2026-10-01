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

from ..config import Settings

WAKE_TIMEOUT_SECONDS = 120
MAX_RISK_DRIVERS = 5
MAX_DRIVER_CHARS = 100


class CallNotAllowed(ValueError):
    """The number isn't on ALLOWED_CALL_NUMBERS."""


def encode_call_context(name: str, risk_drivers: Sequence[str] = ()) -> str:
    """Pack the patient's name and risk drivers into one URL-safe value (letters, digits, '-' and '_').

    Free text such as "HbA1c above 7.5%" is fragile in ordinary query parameters on a callback
    URL that the phone service calls back, so it travels as base64url-encoded JSON instead."""
    context = {"name": name, "drivers": [d[:MAX_DRIVER_CHARS] for d in risk_drivers][:MAX_RISK_DRIVERS]}
    return base64.urlsafe_b64encode(json.dumps(context, separators=(",", ":")).encode()).decode().rstrip("=")


def decode_call_context(value: str) -> tuple[str, list[str]]:
    """Inverse of encode_call_context. Returns ("there", []) for anything malformed."""
    try:
        context = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        name = context.get("name")
        drivers = context.get("drivers", [])
        if not isinstance(name, str) or not isinstance(drivers, list):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        return "there", []
    drivers = [d.strip()[:MAX_DRIVER_CHARS] for d in drivers if isinstance(d, str) and d.strip()]
    return (name.strip()[:60] or "there"), drivers[:MAX_RISK_DRIVERS]


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


def callback_url(settings: Settings, base_url: str, name: str, risk_drivers: Sequence[str] = ()) -> str:
    """Where ACS sends this call's events. The secret key authorizes them; ctx carries the patient."""
    context = encode_call_context(name, risk_drivers)
    return f"{base_url.rstrip('/')}/acs/{settings.phone_webhook_key}/events?{urlencode({'ctx': context})}"


def place_call(settings: Settings, base_url: str, to: str, name: str = "there",
               risk_drivers: Optional[Sequence[str]] = None, client: Optional[CallAutomationClient] = None,
               wake: bool = True, on_wait=None) -> str:
    """Ask ACS to call `to` and connect them to Clara. Returns the ACS call connection ID."""
    check_allowed(settings, to)
    base_url = base_url.rstrip("/")
    if wake:
        wake_server(base_url, on_wait=on_wait)

    client = client or CallAutomationClient.from_connection_string(settings.acs_connection_string)
    call = client.create_call(
        target_participant=PhoneNumberIdentifier(to_e164(to)),
        callback_url=callback_url(settings, base_url, name, risk_drivers or []),
        source_caller_id_number=PhoneNumberIdentifier(to_e164(settings.acs_phone_number)),
        # The Azure AI Services resource ACS uses for text-to-speech and speech recognition.
        cognitive_services_endpoint=settings.acs_cognitive_services_endpoint,
    )
    return call.call_connection_id
