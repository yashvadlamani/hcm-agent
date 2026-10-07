"""Tests for the explicit policy workflow and tool gateway."""

import pytest
from langchain_core.messages import AIMessage

from hcm_agent.agent import llm as llm_module
from hcm_agent.tools import ToolCallContext, build_default_gateway
from hcm_agent.tools.catalog import FAMILIES, build_tools
from hcm_agent.workflows import CareOutreachGraph, OutreachRequest, load_demo_members, outreach_request_from_member
from test_langgraph import ScriptedChatModel, call


@pytest.fixture(autouse=True)
def offline_preflight(monkeypatch):
    def fake_llm(*args):
        return llm_module.LangChainLLM(ScriptedChatModel(replies=[
            call("authorize_outreach"), AIMessage(content='{"allowed":true}'),
        ]))
    monkeypatch.setattr(llm_module, "create_llm", fake_llm)


def valid_request(**changes):
    """Create a request that satisfies every mandatory pre-call policy rule."""
    values = {
        "member_id": "member-123", "phone": "+15555550100", "tenant_id": "tenant-a",
        "consent": True, "do_not_call": False, "local_hour": 10,
    }
    values.update(changes)
    return OutreachRequest(**values)


def test_pre_call_reaches_ready_to_dial_only_after_each_policy_check_passes():
    result = CareOutreachGraph().pre_call(valid_request())
    assert result.allowed
    assert result.terminal_node == "ready_to_dial"
    assert result.authorization
    assert result.call_setup["locale"] == "en-US"


def test_missing_consent_blocks_before_a_call_authorization_is_issued():
    result = CareOutreachGraph().pre_call(valid_request(consent=False))
    assert not result.allowed
    assert result.terminal_node == "blocked"
    assert result.authorization is None


def test_dnc_window_and_frequency_each_block_outreach():
    graph = CareOutreachGraph()
    assert not graph.pre_call(valid_request(do_not_call=True)).allowed
    assert not graph.pre_call(valid_request(local_hour=21)).allowed
    assert not graph.pre_call(valid_request(outreach_attempts_7d=3)).allowed


def test_gateway_rejects_a_cross_member_tool_call_and_records_evidence():
    gateway = build_default_gateway()
    result = gateway.invoke(
        "get_safe_outreach_brief",
        ToolCallContext("agent-1", "tenant-a", "care_management", "member-123", frozenset({"care_outreach"})),
        {"member_id": "member-999"},
    )
    assert not result.allowed
    assert "member scope" in result.reason
    assert gateway.audit_log[-1]["allowed"] is False


def test_every_registered_tool_has_a_langchain_definition():
    gateway = build_default_gateway()
    context = ToolCallContext("agent", "test", "care_management", "m1",
                              frozenset({"care_outreach", "member_verify", "safety_escalation"}))
    tools = build_tools(gateway, context, {}, families=tuple(FAMILIES), verified=True)
    assert {tool.name for tool in tools} == set(gateway.tool_names)


def test_demo_members_define_dnc_frequency_and_local_time_policy():
    members = {member["name"]: member for member in load_demo_members()}
    yashwant = outreach_request_from_member(members["Yashwant Vadlamani"], "demo-health-plan")
    assert yashwant.do_not_call is False
    record = members["Yashwant Vadlamani"]
    assert yashwant.max_outreach_attempts_7d == record["outreach"]["max_outreach_attempts_7d"]
    window = record["communication"]["calling_window"]
    assert (yashwant.window_start_hour, yashwant.window_end_hour) == (window["start_hour"], window["end_hour"])
    assert members["Elena Ramirez"]["outreach"]["do_not_call"] is True
