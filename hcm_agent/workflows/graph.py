"""The shared, native LangGraph loop: model -> tools -> model -> response."""

from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition


class AgentState(MessagesState):
    rounds: int


def build_agent(model, tools, system_prompt: str, *, required_tool: str | None = None, max_rounds: int = 3,
                model_options: dict | None = None):
    """Compile an in-memory graph. Limit tool rounds to bound latency and model usage.

    model_options go to every model request, e.g. {"response_format": {"type": "json_object"}}."""
    model_options = model_options or {}

    def respond(state: AgentState):
        rounds = state.get("rounds", 0)
        if rounds >= max_rounds:
            selected = model  # final review of the last tool output, without further tools
        else:
            choice = required_tool if rounds == 0 and required_tool else "auto"
            selected = model.bind_tools(tools, tool_choice=choice)
        reply = selected.invoke([SystemMessage(system_prompt), *state["messages"]], **model_options)
        return {"messages": [reply], "rounds": rounds + 1}

    builder = StateGraph(AgentState)
    builder.add_node("model", respond)
    builder.add_node("tools", ToolNode(tools, handle_tool_errors="Tool unavailable; do not claim success."))
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", tools_condition, {"tools": "tools", END: END})
    builder.add_edge("tools", "model")
    return builder.compile()


def run_agent(model, tools, system_prompt: str, messages, *, required_tool=None, max_rounds=3,
              model_options=None):
    graph = build_agent(model, tools, system_prompt, required_tool=required_tool, max_rounds=max_rounds,
                        model_options=model_options)
    return graph.invoke({"messages": messages, "rounds": 0}, {"recursion_limit": 2 * max_rounds + 4})
