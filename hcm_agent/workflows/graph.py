"""LangGraph orchestration for Clara's explicit capability agents.

Each capability owns a named ``ToolNode`` and a declared tool list in
``tools/tools.py``. Safety and security also run before every model turn.
"""

import json
from typing import Annotated, Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from ..observability import traced_operation
from ..tools.tools import CAPABILITY_STAGES, CAPABILITY_TOOLS, build_capability_tools


def _merge_tool_results(current: dict | None, update: dict | None) -> dict:
    return {**(current or {}), **(update or {})}


class AgentState(MessagesState):
    """Shared state available to every Clara capability node."""

    rounds: int
    tool_context: dict[str, Any]
    tool_results: Annotated[dict[str, dict], _merge_tool_results]
    blocked: bool
    safety_checked: bool


def _latest_caller_statement(state: AgentState) -> str:
    """Read caller content only; tool/model output is never treated as instructions."""
    for message in reversed(state["messages"]):
        role = message.get("role") if isinstance(message, dict) else getattr(message, "type", "")
        if role in {"user", "human"}:
            content = message.get("content", "") if isinstance(message, dict) else message.content
            return content if isinstance(content, str) else ""
    return ""


def _blocked_response(reply: str, *, emergency=False, kind="none") -> AIMessage:
    return AIMessage(content=json.dumps({
        "reply": reply,
        "emergency": {"detected": emergency, "type": kind if emergency else "none",
                      "reason": reply if emergency else ""},
        "sentiment": 0.1 if emergency else 0.5,
        "conversation_state": "patient_done" if emergency else "ongoing",
    }))


def _security_guard(state: AgentState) -> dict:
    """Capability 8: check every caller message for prompt injection."""
    with traced_operation("invoke_agent capability_8_security", kind="agent", capability="Capability 8 · Security"):
        tool_context = state.get("tool_context", {})
        gateway, context = tool_context.get("gateway"), tool_context.get("context")
        if gateway is None or context is None:
            return {"blocked": False}
        result = gateway.invoke("detect_prompt_injection", context, {
            "text": _latest_caller_statement(state), "member_id": context.member_id,
        })
        if result.allowed and result.data.get("safe") is False:
            return {"blocked": True, "messages": [_blocked_response(
                "I can't process that request. Please ask about your care-management support.",
            )]}
        return {"blocked": False}


SAFETY_CLASSIFIER_PROMPT = """You are Clara's Capability 7 Safety agent. Classify the caller's latest
statement for an urgent crisis. Return only JSON:
{"emergency": boolean, "kind": "medical" or "mental_health", "reason": "short reason"}.
Set emergency true for severe physical symptoms, a stated panic attack, or immediate self-harm risk.
A panic attack is an emergency for this prototype and uses kind medical. Do not provide advice or a
member-facing reply. When uncertain about potentially severe symptoms, choose emergency true."""


def _safety_assessment(model, statement: str) -> dict:
    """Use the configured LLM to make the safety decision before normal conversation routing."""
    response = model.invoke([SystemMessage(SAFETY_CLASSIFIER_PROMPT), HumanMessage(content=statement)])
    content = getattr(response, "text", None) or getattr(response, "content", "")
    try:
        result = json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return {"emergency": False, "kind": None, "reason": "Safety classification unavailable"}
    emergency = result.get("emergency") is True
    kind = result.get("kind") if result.get("kind") in {"medical", "mental_health"} else "medical"
    return {"emergency": emergency, "kind": kind if emergency else None,
            "reason": str(result.get("reason", ""))[:240]}


def _safety_guard(model, state: AgentState) -> dict:
    """Capability 7: LLM classification followed by a fixed, server-owned emergency response."""
    with traced_operation("invoke_agent capability_7_safety", kind="agent", capability="Capability 7 · Safety"):
        # The patient statement is unchanged after a tool result, so one LLM safety assessment per
        # conversation turn is sufficient. The node still remains on the graph's return path.
        if state.get("safety_checked"):
            return {"blocked": False}
        tool_context = state.get("tool_context", {})
        gateway, context = tool_context.get("gateway"), tool_context.get("context")
        if gateway is None or context is None:
            return {"blocked": False, "safety_checked": True}
        llm_assessment = _safety_assessment(model, _latest_caller_statement(state))
        assessment = gateway.invoke("assess_emergency", context, {
            "llm_emergency": llm_assessment["emergency"], "llm_kind": llm_assessment["kind"],
            "member_id": context.member_id,
        })
        if not assessment.allowed or assessment.data.get("emergency") is not True:
            return {"blocked": False, "safety_checked": True}
        script = gateway.invoke("get_911_or_988_script", context, {
            "kind": assessment.data.get("kind"), "member_id": context.member_id,
        })
        return {"blocked": True, "safety_checked": True, "messages": [_blocked_response(
            script.data.get("script", "Please call 911 now."), emergency=True,
            kind=assessment.data.get("kind") or "medical",
        )]}


def _after_security(state: AgentState) -> Literal["safety", "end"]:
    return "end" if state.get("blocked") else "safety"


def _after_safety(state: AgentState) -> Literal["model", "end"]:
    return "end" if state.get("blocked") else "model"


def build_capability_agent(model, system_prompt: str, *, max_rounds: int = 3):
    """Build the main conversation graph with one explicit tool node per capability.

    The model chooses one capability family at a time. Its matching node executes
    the requested server-bound tool and then routes through the safety/security
    guards before the model reviews the result.
    """
    capability_tools = build_capability_tools()
    tool_to_capability = {
        tool_name: capability for capability, tool_names in CAPABILITY_TOOLS.items()
        for tool_name in tool_names
    }
    def care_model(state: AgentState):
        with traced_operation("invoke_agent care_model", kind="agent", capability="Care model"):
            rounds = state.get("rounds", 0)
            stage = state.get("tool_context", {}).get("capability_stage", "care")
            enabled = CAPABILITY_STAGES.get(stage, CAPABILITY_STAGES["care"])
            stage_tools = [tool for capability in enabled for tool in capability_tools[capability]]
            selected = model if rounds >= max_rounds else model.bind_tools(stage_tools)
            reply = selected.invoke([
                SystemMessage(system_prompt + "\nUse tools from one capability family at a time."),
                *state["messages"],
            ])
            return {"messages": [reply], "rounds": rounds + 1}

    def route_capability_tool(state: AgentState) -> str:
        last = state["messages"][-1]
        calls = getattr(last, "tool_calls", [])
        if not calls:
            return "end"
        return tool_to_capability.get(calls[0]["name"], "end")

    graph = StateGraph(AgentState)
    graph.add_node("capability_8_security_guard", _security_guard)
    graph.add_node("capability_7_safety_guard", lambda state: _safety_guard(model, state))
    graph.add_node("care_model", care_model)
    for capability, tools in capability_tools.items():
        graph.add_node(capability, ToolNode(tools, handle_tool_errors="Tool unavailable; do not claim success."))

    graph.add_edge(START, "capability_8_security_guard")
    graph.add_conditional_edges("capability_8_security_guard", _after_security, {
        "safety": "capability_7_safety_guard", "end": END,
    })
    graph.add_conditional_edges("capability_7_safety_guard", _after_safety, {
        "model": "care_model", "end": END,
    })
    graph.add_conditional_edges("care_model", route_capability_tool, {
        "capability_1_outreach": "capability_1_outreach",
        "capability_2_communication": "capability_2_communication",
        "capability_3_identity": "capability_3_identity",
        "capability_4_care_context": "capability_4_care_context",
        "capability_5_knowledge_policy": "capability_5_knowledge_policy",
        "capability_6_navigation": "capability_6_navigation",
        "capability_7_safety": "capability_7_safety",
        "capability_8_security": "capability_8_security",
        "end": END,
    })
    for capability in capability_tools:
        graph.add_edge(capability, "capability_8_security_guard")
    return graph.compile()


def run_capability_agent(model, system_prompt: str, messages, *, max_rounds=3, tool_context=None,
                         capability_stage="care"):
    """Run Clara's main capability graph for one verified care turn."""
    with traced_operation("invoke_workflow clara_capability_graph", kind="workflow", capability="Clara capability graph"):
        graph = build_capability_agent(model, system_prompt, max_rounds=max_rounds)
        context = {**(tool_context or {}), "capability_stage": capability_stage}
        return graph.invoke({"messages": messages, "rounds": 0, "tool_context": context,
                             "tool_results": {}, "blocked": False, "safety_checked": False},
                            {"recursion_limit": 3 * max_rounds + 8})


def build_agent(model, tools, system_prompt: str, *, required_tool: str | None = None, max_rounds: int = 3):
    """Compile the narrow graph used by mandatory identity/pre-call workflow steps."""
    def respond(state: AgentState):
        rounds = state.get("rounds", 0)
        if rounds >= max_rounds:
            selected = model
        else:
            choice = required_tool if rounds == 0 and required_tool else "auto"
            selected = model.bind_tools(tools, tool_choice=choice)
        reply = selected.invoke([SystemMessage(system_prompt), *state["messages"]])
        return {"messages": [reply], "rounds": rounds + 1}

    builder = StateGraph(AgentState)
    builder.add_node("model", respond)
    builder.add_node("tools", ToolNode(tools, handle_tool_errors="Tool unavailable; do not claim success."))
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", tools_condition, {"tools": "tools", END: END})
    builder.add_edge("tools", "model")
    return builder.compile()


def run_agent(model, tools, system_prompt: str, messages, *, required_tool=None, max_rounds=3,
              tool_context=None):
    """Run a narrow graph for one mandatory, single-purpose workflow step."""
    graph = build_agent(model, tools, system_prompt, required_tool=required_tool, max_rounds=max_rounds)
    return graph.invoke({"messages": messages, "rounds": 0, "tool_context": tool_context or {},
                         "tool_results": {}, "blocked": False}, {"recursion_limit": 2 * max_rounds + 4})
