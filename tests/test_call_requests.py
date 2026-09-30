import json

import pytest

from hcm_agent.telephony.call_requests import CallRequest, InvalidCallRequest, parse_call_request


def raw(obj) -> bytes:
    return json.dumps(obj).encode()


def test_minimal_request():
    assert parse_call_request(raw({"to": "+17044305315"})) == CallRequest(to="+17044305315")


def test_full_request_and_bom_tolerance():
    body = "﻿" + json.dumps({"to": "704-430-5315", "name": " Yash ", "risk_drivers": ["HbA1c above 7.5%", " "]})
    request = parse_call_request(body.encode("utf-8"))
    assert request == CallRequest(to="704-430-5315", name="Yash", risk_drivers=["HbA1c above 7.5%"])


@pytest.mark.parametrize("body", [
    b"not json",
    raw(["+17044305315"]),
    raw({}),
    raw({"to": 7044305315}),
    raw({"to": "12345"}),
    raw({"to": "+17044305315", "name": ""}),
    raw({"to": "+17044305315", "risk_drivers": "HbA1c"}),
    raw({"to": "+17044305315", "risk_drivers": ["a", "b", "c", "d", "e", "f"]}),
    b"x" * 20_000,
])
def test_invalid_requests_are_rejected(body):
    with pytest.raises(InvalidCallRequest):
        parse_call_request(body)
