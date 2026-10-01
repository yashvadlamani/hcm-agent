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


class FakeTwilio:
    def __init__(self):
        self.created = []
        self.calls = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(sid="CAfake123")


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


def test_place_call_uses_trial_safe_parameters():
    twilio = FakeTwilio()
    sid = place_call(VALID, "https://clara.example.net/", "+15555550100", "Yash",
                     ["HbA1c above 7.5%", "Missed refills"], client=twilio, wake=False)

    assert sid == "CAfake123"
    request = twilio.created[0]
    assert set(request) == {"to", "from_", "url"}  # trial accounts reject anything else
    url = urlparse(request["url"])
    assert url.netloc == "clara.example.net"
    assert url.path == f"/t/{VALID.phone_webhook_key}/voice"
    [context] = parse_qs(url.query)["ctx"]
    assert re.fullmatch(r"[A-Za-z0-9_-]+", context)  # nothing Twilio could mangle
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


def test_place_call_refuses_before_contacting_twilio():
    twilio = FakeTwilio()
    with pytest.raises(CallNotAllowed):
        place_call(VALID, "https://clara.example.net", "+15559999999", client=twilio, wake=False)
    assert twilio.created == []
