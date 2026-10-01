import dataclasses
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from hcm_agent.telephony.outbound import (
    CallNotAllowed,
    check_allowed,
    decode_call_context,
    encode_call_context,
    place_call,
    to_e164,
)
from test_config import VALID


class FakeACS:
    def __init__(self):
        self.created = []

    def create_call(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(call_connection_id="call-fake-123")


@pytest.mark.parametrize("raw, expected", [
    ("704-430-5315", "+17044305315"),
    ("+1 (704) 430-5315", "+17044305315"),
    ("17044305315", "+17044305315"),
])
def test_to_e164(raw, expected):
    assert to_e164(raw) == expected


def test_allow_list_blocks_other_numbers():
    with pytest.raises(CallNotAllowed):
        check_allowed(VALID, "+15559999999")
    check_allowed(VALID, "(555) 555-0100")  # formatting differences still match


def test_empty_allow_list_allows_any_number():
    check_allowed(dataclasses.replace(VALID, allowed_call_numbers=()), "+15559999999")


def test_place_call_asks_acs_to_dial_with_a_callback_to_clara():
    acs = FakeACS()
    call_id = place_call(VALID, "https://clara.example.net/", "(555) 555-0100", "Yash",
                         ["HbA1c above 7.5%", "Missed refills"], client=acs, wake=False)

    assert call_id == "call-fake-123"
    request = acs.created[0]
    assert request["target_participant"].properties["value"] == "+15555550100"
    assert request["source_caller_id_number"].properties["value"] == VALID.acs_phone_number
    assert request["cognitive_services_endpoint"] == VALID.acs_cognitive_services_endpoint
    url = urlparse(request["callback_url"])
    assert url.scheme == "https" and url.netloc == "clara.example.net"
    assert url.path == f"/acs/{VALID.phone_webhook_key}/events"
    [context] = parse_qs(url.query)["ctx"]
    assert re.fullmatch(r"[A-Za-z0-9_-]+", context)  # URL-safe, nothing to escape
    assert decode_call_context(context) == ("Yash", ["HbA1c above 7.5%", "Missed refills"])


def test_call_context_round_trips_free_text():
    drivers = ["HbA1c above 7.5% at last check", "Refills: missed, twice & late", "Ünïcode \"quotes\""]
    assert decode_call_context(encode_call_context("José O'Neil", drivers)) == ("José O'Neil", drivers)


def test_call_context_caps_drivers():
    name, drivers = decode_call_context(encode_call_context("Yash", ["x" * 500] * 9))
    assert len(drivers) == 5 and all(len(d) == 100 for d in drivers)


@pytest.mark.parametrize("value", ["", "not-base64!", "e30", "WyJhIl0"])  # "", junk, {}, ["a"]
def test_malformed_call_context_falls_back(value):
    assert decode_call_context(value) == ("there", [])


def test_place_call_refuses_before_contacting_acs():
    acs = FakeACS()
    with pytest.raises(CallNotAllowed):
        place_call(VALID, "https://clara.example.net", "+15559999999", client=acs, wake=False)
    assert acs.created == []
