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
from hcm_agent.workflows.graph import run_agent
from hcm_agent.workflows.graph import build_capability_agent
from hcm_agent.tools.tools import CAPABILITY_TOOLS
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


def test_capability_graph_exposes_all_eight_named_tool_nodes():
    graph = build_capability_agent(ScriptedChatModel(replies=[AIMessage(content="done")]), "test")
    node_names = set(graph.get_graph().nodes)
    assert set(CAPABILITY_TOOLS) <= node_names
    assert {"capability_8_security_guard", "capability_7_safety_guard", "care_model"} <= node_names


def invoke_catalog_tool(name, arguments, *, gateway, context, profile=None, verified=False, retrieval_llm=None):
    model = ScriptedChatModel(replies=[call(name, **arguments), AIMessage(content="done")])
    tool_set = build_tools()
    state = run_agent(model, tool_set, "test", [], max_rounds=1, tool_context={
        "gateway": gateway, "context": context, "profile": profile or {}, "verified": verified,
        "retrieval_llm": retrieval_llm,
    })
    return json.loads(next(message.content for message in state["messages"]
                           if isinstance(message, ToolMessage)))


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


def test_catalog_covers_families_and_blocks_unverified_access(tmp_path, monkeypatch):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    import hcm_agent.tools.domains as domains
    import hcm_agent.tools.scheduling as scheduling
    monkeypatch.setattr(domains, "policy_document_available", lambda: True)
    monkeypatch.setattr(domains, "retrieve_policy", lambda query, llm=None: [{
        "policy_id": "test-policy", "title": "Test policy", "page": 2, "content": "Test policy excerpt",
    }])
    gateway = build_default_gateway()
    assert set(gateway.tool_names) == {name for names in FAMILIES.values() for name in names}
    assert FAMILIES["care"] == ("get_safe_outreach_brief", "get_approved_goals")
    assert FAMILIES["guidance"] == ("search_diabetes_playbook", "lookup_policy")
    assert FAMILIES["navigation"] == ("provider_directory_search", "request_appointment")
    assert {"outreach", "communication", "identity", "safety", "security"} <= set(FAMILIES)
    context = ToolCallContext("agent", "test", "care_management", "m1", frozenset({"care_outreach"}))
    tools = {t.name: t for t in build_tools()}
    assert invoke_catalog_tool("lookup_policy", {"query": "wellness visits"}, gateway=gateway,
                               context=context)["allowed"] is False
    profile = {"local_demo_mode": True}
    policy_result = invoke_catalog_tool("lookup_policy", {"query": "wellness visits"}, gateway=gateway,
                                         context=context, profile=profile, verified=True)
    assert policy_result["allowed"] is True
    assert policy_result["data"]["status"] == "results_found"
    assert policy_result["data"]["results"][0]["page"] == 2
    assert invoke_catalog_tool("request_appointment", {}, gateway=gateway, context=context,
                               profile=profile, verified=True)["data"]["status"] == "needs_provider"
    with pytest.raises(ValidationError):
        tools["lookup_policy"].args_schema.model_validate({"query": "visit", "member_id": "someone-else"})

    directory = tmp_path / "providers.json"
    directory.write_text(json.dumps({"source_status": "active", "as_of": "2026-10-01", "providers": [{
        "provider_id": "p1", "display_name": "Demo Clinic", "specialties": ["endocrinology"],
        "city": "Austin", "state": "TX", "phone": "555-0100", "accepting_new_patients": True,
        "is_fictional_demo": True, "active": True,
    }]}))
    monkeypatch.setenv("CLARA_PROVIDER_DIRECTORY_PATH", str(directory))
    provider_result = invoke_catalog_tool("provider_directory_search",
        {"specialty": "endocrinology", "city": "Austin", "state": "TX"}, gateway=gateway,
        context=context, profile=profile, verified=True)
    assert provider_result["data"]["options"][0]["provider_id"] == "p1"
    scheduling.DEMO_APPOINTMENTS.clear()
    try:
        now = datetime.now(ZoneInfo("America/Chicago")).replace(hour=8, minute=0, second=0, microsecond=0)
        saturday_offset = (5 - now.weekday()) % 7 or 7
        saturday = now.date() + timedelta(days=saturday_offset)
        weekend = scheduling.request_demo_appointment(
            {"provider_id": "p1", "requested_date": saturday.isoformat(), "requested_time": "10:00"}, now=now,
        )
        assert weekend["status"] == "closed_weekends"
        assert weekend["appointment_options"][0] == {
            "date": (saturday + timedelta(days=2)).isoformat(), "day": "Monday",
            "time": "10:00", "timezone": "America/Chicago",
        }

        offered = invoke_catalog_tool("request_appointment", {"provider_id": "p1"}, gateway=gateway,
                                      context=context, profile=profile, verified=True)["data"]
        assert offered["status"] == "slots_offered"
        choice = offered["appointment_options"][0]
        appointment = invoke_catalog_tool("request_appointment", {"provider_id": "p1",
            "requested_date": choice["date"], "requested_time": choice["time"]}, gateway=gateway,
            context=context, profile=profile, verified=True)["data"]
        assert appointment["status"] == "demo_appointment_scheduled"
        assert appointment["real_appointment_confirmed"] is False
        duplicate = invoke_catalog_tool("request_appointment", {"provider_id": "p1",
            "requested_date": choice["date"], "requested_time": choice["time"]}, gateway=gateway,
            context=context, profile=profile, verified=True)["data"]
        assert duplicate["status"] == "slot_unavailable"
    finally:
        scheduling.DEMO_APPOINTMENTS.clear()


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


def test_phone_call_uses_native_tools_for_identity_and_policy(monkeypatch):
    import hcm_agent.tools.domains as domains
    from hcm_agent.telephony import server
    from hcm_agent.telephony.outbound import encode_call_context
    from test_server import FakeACS, RunNow

    reply = "I can't confirm that policy from an approved source right now."
    monkeypatch.setattr(domains, "policy_document_available", lambda: True)
    monkeypatch.setattr(domains, "retrieve_policy", lambda query, llm=None: [{
        # The registered policy source: passages from any other source are now dropped before the model.
        "policy_id": domains.POLICY_ID, "title": "Test policy", "page": 1,
        "content": "Test policy excerpt",
    }])
    model = ScriptedChatModel(replies=[
        call("verify_full_name", provided_name="Maria", match_type="first_name"), approved(),
        call("verify_dob", provided_dob="1990-01-02"), approved(),
        call("lookup_policy", query="annual wellness visit"),
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
        assert json.loads(model.seen[-1][-1].content)["data"]["grounded"] is True
        assert {"verify_full_name", "verify_dob", "lookup_policy"} <= model.bound_names
    finally:
        server.calls.clear()
