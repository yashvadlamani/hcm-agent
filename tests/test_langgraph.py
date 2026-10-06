"""Five offline priority checks for the LangChain/LangGraph migration. No API calls."""

import json

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field, ValidationError

from hcm_agent.agent.conversation import HCMVoiceAgent
from hcm_agent.agent.llm import LangChainLLM
from hcm_agent.tools import ToolCallContext, build_default_gateway
from hcm_agent.tools.catalog import FAMILIES, build_tools
from test_config import VALID

RECORD = {"member_id": "m1", "tenant_id": "test", "name": "Maria Lopez", "date_of_birth": "1990-01-02",
          "profile": {"benefit": "Annual wellness visits are listed in this demo plan."}}


class ScriptedChatModel(BaseChatModel):
    replies: list[AIMessage]
    seen: list = Field(default_factory=list)
    bound_names: set[str] = Field(default_factory=set)

    @property
    def _llm_type(self):
        return "offline-scripted-chat"

    def bind_tools(self, tools, **kwargs):
        self.bound_names.update(tool.name for tool in tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self.replies.pop(0))])


def call(name, **arguments):
    return AIMessage(content="", tool_calls=[{"name": name, "args": arguments, "id": "t1", "type": "tool_call"}])


def approved():
    return AIMessage(content='{"verified": true}')


def test_identity_tools_are_reviewed_before_care():
    model = ScriptedChatModel(replies=[
        call("verify_full_name", provided_name="Maria", match_type="first_name"), approved(),
        call("verify_dob", provided_dob="1990-01-02"), approved(),
    ])
    agent = HCMVoiceAgent(settings=VALID, llm=LangChainLLM(model))
    agent.initialize_call({}, identity_record=RECORD)
    assert agent.take_turn("Maria").phase == "verify_dob"
    assert agent.identity is None
    assert agent.take_turn("January second nineteen ninety").identity == "confirmed"
    assert isinstance(model.seen[1][-1], ToolMessage)
    assert isinstance(model.seen[3][-1], ToolMessage)
    assert "1990" not in agent.get_conversation_transcript()


def test_wrong_dob_cannot_be_overridden_by_model():
    model = ScriptedChatModel(replies=[call("verify_dob", provided_dob="1990-01-03"), approved()])
    agent = HCMVoiceAgent(settings=VALID, llm=LangChainLLM(model))
    agent.initialize_call({}, identity_record=RECORD)
    agent.phase = "verify_dob"
    turn = agent.take_turn("January 3, 1990")
    assert turn.action == "hang_up" and turn.identity == "failed"
    assert json.loads(model.seen[-1][-1].content)["verified"] is False


def test_catalog_covers_families_and_blocks_unverified_access():
    gateway = build_default_gateway()
    assert set(gateway.tool_names) == {name for names in FAMILIES.values() for name in names}
    context = ToolCallContext("agent", "test", "care_management", "m1", frozenset({"care_outreach"}))
    locked = {t.name: t for t in build_tools(gateway, context, RECORD["profile"])}
    assert locked["lookup_benefit"].invoke({"query": "wellness visits"})["allowed"] is False
    tools = {t.name: t for t in build_tools(gateway, context, RECORD["profile"], verified=True)}
    assert tools["lookup_benefit"].invoke({"query": "wellness visits"})["data"]["found"] is True
    assert tools["request_appointment"].invoke({"query": "Book a visit"})["data"]["created"] is False
    with pytest.raises(ValidationError):
        tools["lookup_benefit"].invoke({"query": "visit", "member_id": "someone-else"})


def test_preflight_blocks_dial_despite_model_approval(monkeypatch):
    from hcm_agent.telephony import outbound

    record = {**RECORD, "phone": "+15555550100",
              "communication": {"language": "en-US", "local_timezone": "UTC",
                                "calling_window": {"start_hour": 0, "end_hour": 24}},
              "outreach": {"consent": False, "do_not_call": False, "member_active": True,
                           "outreach_attempts_7d": 0, "max_outreach_attempts_7d": 1}}
    monkeypatch.setattr(outbound, "identity_record_for_phone", lambda phone: record)
    monkeypatch.setattr(outbound, "check_allowed", lambda *args: None)
    def forbidden_dial(*args, **kwargs):
        pytest.fail("ACS must not be called after failed consent")
    monkeypatch.setattr(outbound, "place_policy_authorized_call", forbidden_dial)
    model = ScriptedChatModel(replies=[call("authorize_outreach"), AIMessage(content='{"allowed":true}')])
    with pytest.raises(outbound.CallNotAllowed, match="consent"):
        outbound.place_member_call(VALID, "https://example.test", record["phone"], llm=LangChainLLM(model))


def test_phone_call_uses_native_tools_for_identity_and_benefits(monkeypatch):
    from hcm_agent.telephony import server
    from hcm_agent.telephony.outbound import encode_call_context
    from test_server import FakeACS, RunNow

    reply = "This demo plan lists annual wellness visits. Coverage still depends on your plan."
    model = ScriptedChatModel(replies=[
        call("verify_full_name", provided_name="Maria", match_type="first_name"), approved(),
        call("verify_dob", provided_dob="1990-01-02"), approved(),
        call("lookup_benefit", query="annual wellness visit"),
        AIMessage(content=json.dumps({"reply": reply, "sentiment": 0.5, "conversation_state": "ongoing"})),
    ])
    llm, acs = LangChainLLM(model), FakeACS()
    monkeypatch.setattr(server, "identity_record_for_phone", lambda phone: RECORD)
    monkeypatch.setattr(server, "shared_llm", lambda: llm)
    monkeypatch.setattr(server, "warm_up_model", lambda: None)
    monkeypatch.setattr(server, "executor", RunNow())
    monkeypatch.setattr(server, "acs", lambda: acs)
    monkeypatch.setattr(server, "settings", VALID)
    monkeypatch.setattr(server, "HCMVoiceAgent", lambda **kwargs: HCMVoiceAgent(settings=VALID, llm=llm))
    server.calls.clear()
    try:
        server.on_connected("test", encode_call_context("Maria Lopez"))
        for answer in ("Maria", "January 2, 1990", "Does my plan cover annual wellness visits?"):
            server.on_speech("test", {"speechResult": {"speech": answer}})
        assert acs.last()[1] == reply
        assert json.loads(model.seen[-1][-1].content)["data"]["found"] is True
        assert {"verify_full_name", "verify_dob", "lookup_benefit"} <= model.bound_names
    finally:
        server.calls.clear()
