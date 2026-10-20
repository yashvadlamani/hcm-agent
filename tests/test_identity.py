"""Name/DOB tool use, model review, record loading and terminal regression tests."""

import json

import pytest

from hcm_agent.agent.conversation import HCMVoiceAgent
from hcm_agent.agent.llm import LangChainLLM
from hcm_agent.cli.chat_demo import MockVoiceInterface
from hcm_agent.tools.identity import verify_dob, verify_full_name
from hcm_agent.workflows.member_data import identity_record_for_name, identity_record_for_phone
from test_config import VALID
from test_conversation import ScriptedLLM

RECORD = {"member_id": "m1", "tenant_id": "test", "name": "Himanshu Gupta", "date_of_birth": "1990-01-02"}


class InterpretingLLM(ScriptedLLM):
    def __init__(self, arguments, review=True):
        super().__init__()
        self.arguments, self.review = arguments, review
        self.payloads = []

    def call_and_review_tool(self, system_prompt, payload, tool, execute):
        self.payloads.append(payload)
        self.result = execute(self.arguments)
        return self.review


@pytest.mark.parametrize("spoken,parsed,mode", [
    ("Himanshu Gupta", "Himanshu Gupta", "exact"),
    ("Himanshu", "Himanshu", "first_name"),
    ("My name is Himanshoo Gupta", "Himanshoo Gupta", "phonetic"),
])
def test_gpt_interpretation_then_tool_then_review(spoken, parsed, mode):
    model = InterpretingLLM({"provided_name": parsed, "match_type": mode})
    agent = HCMVoiceAgent(settings=VALID, llm=model)
    agent.initialize_call({}, identity_record=RECORD)
    turn = agent.take_turn(spoken)
    assert turn.phase == "verify_dob" and turn.used_model
    assert model.result["verified"] is True
    assert agent.identity is None  # name alone never verifies the member


@pytest.mark.parametrize("arguments,review", [
    ({"provided_name": "Michael Smith", "match_type": "phonetic"}, True),
    ({"provided_name": "Himanshu Gupta", "match_type": "exact"}, True),  # invented name
    ({"provided_name": "Himanshu", "match_type": "first_name"}, False),  # reviewer rejects
    ({"provided_name": "Himanshu", "match_type": "first_name", "expected_name": "Himanshu"}, True),
])
def test_model_cannot_override_a_failed_tool_or_inject_expected_values(arguments, review):
    model = InterpretingLLM(arguments, review)
    agent = HCMVoiceAgent(settings=VALID, llm=model)
    agent.initialize_call({}, identity_record=RECORD)
    assert agent.take_turn("Himanshu").action == "hang_up"


def test_model_normalizes_spoken_dob_without_seeing_expected_dob():
    model = InterpretingLLM({"provided_dob": "1990-01-02"})
    agent = HCMVoiceAgent(settings=VALID, llm=model)
    agent.initialize_call({}, identity_record=RECORD)
    agent.phase = "verify_dob"
    turn = agent.take_turn("January second nineteen ninety")
    assert turn.identity == "confirmed"
    assert model.payloads == [{"answer": "January second nineteen ninety"}]
    assert "ninety" not in agent.get_conversation_transcript()


def test_model_approval_does_not_override_wrong_dob():
    model = InterpretingLLM({"provided_dob": "1990-01-03"}, review=True)
    agent = HCMVoiceAgent(settings=VALID, llm=model)
    agent.initialize_call({}, identity_record=RECORD)
    agent.phase = "verify_dob"
    assert agent.take_turn("January third nineteen ninety").action == "hang_up"


@pytest.mark.parametrize("answer", ["1990-01-02", "January 2nd, 1990", "1/2/1990"])
def test_dob_formats(answer):
    assert verify_dob({"provided_dob": answer, "expected_dob": "1990-01-02"})["verified"]


def test_missing_values_never_match():
    assert not verify_dob({})["verified"]
    assert not verify_full_name({})["verified"]


def test_terminal_loads_expected_identity_before_call(monkeypatch):
    from hcm_agent.cli import chat_demo
    monkeypatch.setattr(chat_demo, "identity_record_for_name", lambda name: RECORD)
    agent = HCMVoiceAgent(settings=VALID, llm=ScriptedLLM())
    voice = MockVoiceInterface(agent)
    voice.start_call({"name": "Himanshu Gupta"})
    assert voice.send_message("Himanshu Gupta").phase == "verify_dob"
    assert voice.send_message("January 2, 1990").identity == "confirmed"


def test_record_lookup_matches_existing_demo_name():
    record = identity_record_for_name("Himanshu Gupta")
    assert record["name"] == "Himanshu Gupta" and record["date_of_birth"]


def test_missing_or_duplicate_records_fail_closed(tmp_path, monkeypatch):
    path = tmp_path / "members.json"
    monkeypatch.setenv("MEMBER_DATA_PATH", str(path))
    assert identity_record_for_phone("+15555550100") == {}
    member = {**RECORD, "phone": "+15555550100"}
    path.write_text(json.dumps({"tenant_id": "test", "members": [member]}))
    assert identity_record_for_phone("5555550100")["member_id"] == "m1"
    path.write_text(json.dumps({"tenant_id": "test", "members": [member, member]}))
    assert identity_record_for_phone("+15555550100") == {}


def test_langchain_executes_tool_and_reviews_actual_result():
    from langchain_core.messages import ToolMessage

    from test_langgraph import ScriptedChatModel, approved, call
    model = ScriptedChatModel(replies=[
        call("verify_full_name", provided_name="Himanshu", match_type="first_name"), approved(),
    ])
    agent = HCMVoiceAgent(settings=VALID, llm=LangChainLLM(model))
    agent.initialize_call({}, identity_record=RECORD)
    assert agent.take_turn("Himanshu").phase == "verify_dob"
    assert isinstance(model.seen[-1][-1], ToolMessage)
    assert json.loads(model.seen[-1][-1].content)["verified"] is True


def test_model_service_failure_ends_call():
    model = InterpretingLLM({})
    def unavailable(*args):
        raise RuntimeError("unavailable")
    model.call_and_review_tool = unavailable
    agent = HCMVoiceAgent(settings=VALID, llm=model)
    agent.initialize_call({}, identity_record=RECORD)
    turn = agent.take_turn("Himanshu")
    assert turn.action == "hang_up" and turn.end_reason == "Identity verification unavailable"
    assert turn.developer_error == "RuntimeError"
    assert agent.identity_gateway.audit_log[-1]["tool"] == "record_verification_failure"


def test_server_package_contains_member_records_and_identity_tools(tmp_path):
    from zipfile import ZipFile

    from hcm_agent.deploy.package import build, server_files
    archive = tmp_path / "server.zip"
    build(server_files(), str(archive))
    with ZipFile(archive) as package:
        names = package.namelist()
        assert "data/demo_members.json" in names
        assert "hcm_agent/agent/identity.py" in names
        assert "hcm_agent/tools/identity.py" in names
