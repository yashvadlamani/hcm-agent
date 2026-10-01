"""Tests for the call-request Azure Function's logic, using a fake storage container."""

import datetime
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("azure.functions")
import function_app  # noqa: E402
from test_config import VALID  # noqa: E402


class FakeContainer:
    def __init__(self, processed_last_hour=0):
        now = datetime.datetime.now(datetime.timezone.utc)
        self.blobs = [SimpleNamespace(name=f"processed/{i}.json", last_modified=now)
                      for i in range(processed_last_hour)]
        self.uploaded = {}

    def list_blobs(self, name_starts_with):
        return [b for b in self.blobs if b.name.startswith(name_starts_with)]

    def upload_blob(self, name, data, overwrite):
        self.uploaded[name] = json.loads(data)


class FakeIncoming:
    blob_name = "incoming/yash-test.json"

    def __init__(self):
        self.deleted_with = None

    def delete_blob(self, lease):
        self.deleted_with = lease


@pytest.fixture
def placed(monkeypatch):
    calls = []
    monkeypatch.setattr(function_app.config, "load", lambda: VALID)

    def fake_place_call(settings, base_url, to, name, drivers):
        calls.append({"base_url": base_url, "to": to, "name": name, "drivers": drivers})
        return "CAfake123"

    monkeypatch.setattr(function_app, "place_call", fake_place_call)
    return calls


def request(**fields) -> bytes:
    return json.dumps({"to": "+15555550100", "name": "Yash", **fields}).encode()


def test_valid_request_places_one_call(placed):
    outcome, result = function_app._handle(request(), FakeContainer())
    assert (outcome, result) == ("processed", {"call_sid": "CAfake123"})
    assert placed == [{"base_url": VALID.clara_base_url, "to": "+15555550100", "name": "Yash", "drivers": []}]


def test_invalid_request_fails_without_calling(placed):
    outcome, result = function_app._handle(b'{"name": "no number"}', FakeContainer())
    assert outcome == "failed" and "invalid request" in result["error"]
    assert placed == []


def test_rate_limit_stops_calls(placed):
    outcome, result = function_app._handle(request(), FakeContainer(processed_last_hour=VALID.max_calls_per_hour))
    assert outcome == "failed" and "rate limit" in result["error"]
    assert placed == []


def test_unconfigured_function_refuses(placed, monkeypatch):
    monkeypatch.setattr(function_app.config, "load", lambda: SimpleNamespace(**{
        **VALID.__dict__, "allowed_call_numbers": ()}))
    outcome, result = function_app._handle(request(), FakeContainer())
    assert outcome == "failed" and result["error"] == "function is not configured"
    assert placed == []


def test_result_is_filed_and_incoming_deleted():
    container, incoming = FakeContainer(), FakeIncoming()
    function_app._file_result(container, incoming, "lease-1", request(), "processed", {"call_sid": "CA1"})

    [(name, record)] = container.uploaded.items()
    assert name.startswith("processed/") and name.endswith("-yash-test.json")
    assert record["result"] == {"call_sid": "CA1"} and record["request"]["to"] == "+15555550100"
    assert incoming.deleted_with == "lease-1"


@pytest.mark.parametrize("path, expected", [
    ("incoming/yash-test.json", True),
    ("incoming/YASH.JSON", True),
    ("incoming/README.txt", False),
    ("incoming/nested/request.json", False),
    ("processed/request.json", False),
])
def test_only_json_files_in_incoming_are_requests(path, expected):
    assert function_app.is_call_request(path) is expected


class PlaceholderContainer:
    def __init__(self, exists=False, broken=False):
        self.exists, self.broken, self.uploads = exists, broken, []

    def upload_blob(self, name, data, overwrite):
        if self.broken:
            raise RuntimeError("storage unavailable")
        if self.exists and not overwrite:
            raise function_app.ResourceExistsError("exists")
        self.uploads.append((name, data))


def test_missing_placeholder_is_restored():
    container = PlaceholderContainer()
    function_app._ensure_placeholder(container)
    [(name, data)] = container.uploads
    assert name == "incoming/README.txt" and b"Upload call requests" in data


def test_existing_placeholder_is_left_alone():
    container = PlaceholderContainer(exists=True)
    function_app._ensure_placeholder(container)
    assert container.uploads == []


def test_placeholder_problems_never_fail_the_request():
    function_app._ensure_placeholder(PlaceholderContainer(broken=True))  # must not raise
