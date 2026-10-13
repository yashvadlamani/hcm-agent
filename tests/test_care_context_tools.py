"""Offline tests for server-bound outreach context tools in the LangGraph care loop."""

import json

from langchain_core.messages import AIMessage, ToolMessage

from hcm_agent.agent.conversation import HCMVoiceAgent
from hcm_agent.agent.llm import LangChainLLM
from hcm_agent.tools import ToolCallContext, build_default_gateway
from hcm_agent.tools.catalog import build_tools
from test_config import VALID
from test_langgraph import ScriptedChatModel, call, invoke_catalog_tool

DEMO_CONTEXT = {
    "data_status": "fictional_demo_only",
    "for": "diabetes management",
    "risk_drivers": ["Overdue annual diabetic eye exam"],
    "care_team_record": "Fictional demo note about routine diabetes follow-up.",
    "goals_on_file": ["Discuss routine follow-up with the care team."],
    "follow_up_plan": ["Ask about scheduling routine follow-up."],
}


def test_care_graph_calls_both_context_tools_and_reviews_member_bound_results():
    model = ScriptedChatModel(replies=[
        AIMessage(content=json.dumps({"emergency": False, "kind": "medical", "reason": ""})),
        call("get_safe_outreach_brief"),
        call("get_approved_goals"),
        AIMessage(content=json.dumps({
            "reply": "I can share the goals in this demo context, though they are not approved care-plan goals.",
            "emergency": {"detected": False, "type": "none", "reason": ""},
            "sentiment": 0.5,
            "conversation_state": "ongoing",
        })),
    ])
    agent = HCMVoiceAgent(settings=VALID, llm=LangChainLLM(model))
    agent.initialize_call(
        {"name": "Himanshu Gupta", "call_reason": "diabetes management",
         "risk_drivers": DEMO_CONTEXT["risk_drivers"], "local_demo_context": True},
        identity_record={"member_id": "demo-himanshu-gupta", "tenant_id": "demo-health-plan",
                         "demo_call_context": DEMO_CONTEXT},
    )
    agent.identity, agent.phase = "confirmed", "conversation"

    turn = agent.take_turn("What goals are recorded?")

    assert turn.reply.startswith("I can share the goals")
    assert {"get_safe_outreach_brief", "get_approved_goals"} <= model.bound_names
    tool_results = [message.content for message in model.seen[-1] if isinstance(message, ToolMessage)]
    assert any('"purpose": "diabetes management"' in result for result in tool_results)
    assert any('"care_team_record": "Fictional demo note' in result for result in tool_results)
    assert any('"follow_up_plan":' in result for result in tool_results)
    assert any('"goals": ["Discuss routine follow-up with the care team."]' in result
               for result in tool_results)
    assert any('"data_status": "fictional_demo_only"' in result for result in tool_results)
    assert any('"approved": false' in result for result in tool_results)
    assert all(event["member_id"] == "demo-himanshu-gupta" for event in agent.identity_gateway.audit_log)


def test_why_was_i_contacted_routes_through_the_safe_outreach_brief_tool():
    model = ScriptedChatModel(replies=[
        AIMessage(content=json.dumps({"emergency": False, "kind": "medical", "reason": ""})),
        call("get_safe_outreach_brief"),
        AIMessage(content=json.dumps({
            "reply": "This call is a diabetes-management check-in based on your care team's outreach plan.",
            "emergency": {"detected": False, "type": "none", "reason": ""},
            "sentiment": 0.5, "conversation_state": "ongoing",
        })),
    ])
    agent = HCMVoiceAgent(settings=VALID, llm=LangChainLLM(model))
    agent.initialize_call(
        {"name": "Himanshu Gupta", "call_reason": "diabetes management", "local_demo_context": True},
        identity_record={"member_id": "demo-himanshu-gupta", "tenant_id": "demo-health-plan",
                         "demo_call_context": DEMO_CONTEXT},
    )
    agent.identity, agent.phase = "confirmed", "conversation"

    turn = agent.take_turn("What made you contact me?")

    assert turn.reply.startswith("This call is a diabetes-management check-in")
    assert "get_safe_outreach_brief" in model.bound_names
    assert any('"purpose": "diabetes management"' in message.content
               for message in model.seen[-1] if isinstance(message, ToolMessage))


def test_context_tool_ignores_model_supplied_member_facts():
    context = ToolCallContext("agent", "tenant", "care_management", "member-1",
                              frozenset({"care_outreach"}))
    result = invoke_catalog_tool("get_approved_goals", {}, gateway=build_default_gateway(), context=context,
                                 profile={"care_goals": ["server-bound goal"],
                                          "goals_data_status": "fictional_demo_only"}, verified=True)

    assert result["data"]["goals"] == ["server-bound goal"]
    assert result["data"]["approved"] is False


def test_non_demo_call_does_not_load_fictional_record_context():
    agent = HCMVoiceAgent(settings=VALID, llm=LangChainLLM(ScriptedChatModel(replies=[])))
    agent.initialize_call({"call_reason": "diabetes management"}, identity_record={
        "demo_call_context": DEMO_CONTEXT,
    })

    profile = agent._care_tool_profile()

    assert profile["outreach_risk_drivers"] == []
    assert profile["care_goals"] == []
    assert profile["goals_data_status"] == "not_configured"
