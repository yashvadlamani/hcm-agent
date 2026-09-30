import dataclasses
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from hcm_agent.telephony.outbound import CallNotAllowed, check_allowed, place_call, to_e164
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
    assert parse_qs(url.query) == {"name": ["Yash"], "drivers": ["HbA1c above 7.5%,Missed refills"]}


def test_place_call_refuses_before_contacting_twilio():
    twilio = FakeTwilio()
    with pytest.raises(CallNotAllowed):
        place_call(VALID, "https://clara.example.net", "+15559999999", client=twilio, wake=False)
    assert twilio.created == []
