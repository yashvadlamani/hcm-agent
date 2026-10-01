"""Call-request files: JSON uploaded to storage that asks Clara to call someone.

    {"to": "+15551234567", "name": "Yash", "risk_drivers": ["HbA1c above 7.5%"]}

Only "to" is required. Up to 5 risk drivers, each at most 100 characters.
"""

import json
from dataclasses import dataclass, field

from .outbound import MAX_DRIVER_CHARS, MAX_RISK_DRIVERS

MAX_REQUEST_BYTES = 10_000


class InvalidCallRequest(ValueError):
    """The uploaded file isn't a valid call request."""


@dataclass(frozen=True)
class CallRequest:
    to: str
    name: str = "there"
    risk_drivers: list[str] = field(default_factory=list)


def parse_call_request(raw: bytes) -> CallRequest:
    if len(raw) > MAX_REQUEST_BYTES:
        raise InvalidCallRequest(f"file is larger than {MAX_REQUEST_BYTES} bytes")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise InvalidCallRequest(f"not valid JSON: {e}") from None
    if not isinstance(data, dict):
        raise InvalidCallRequest("expected a JSON object")

    to = data.get("to")
    if not isinstance(to, str) or sum(ch.isdigit() for ch in to) < 10:
        raise InvalidCallRequest('"to" must be a phone number string, e.g. "+15551234567"')

    name = data.get("name", "there")
    if not isinstance(name, str) or not name.strip() or len(name) > 60:
        raise InvalidCallRequest('"name" must be a short non-empty string')

    drivers = data.get("risk_drivers", [])
    if (not isinstance(drivers, list) or len(drivers) > MAX_RISK_DRIVERS
            or not all(isinstance(d, str) and len(d) <= MAX_DRIVER_CHARS for d in drivers)):
        raise InvalidCallRequest(
            f'"risk_drivers" must be a list of up to {MAX_RISK_DRIVERS} strings, '
            f'each at most {MAX_DRIVER_CHARS} characters')

    return CallRequest(to=to, name=name.strip(), risk_drivers=[d.strip() for d in drivers if d.strip()])
