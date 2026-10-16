from hcm_agent.observability import call_trace, trace_store, traced_operation


def test_live_trace_store_captures_safe_tool_metadata_without_arguments():
    trace_store.clear()
    with call_trace("call-demo"):
        with traced_operation("execute_tool lookup_policy", kind="tool",
                              capability="Capability 5 · Knowledge & policy", tool="lookup_policy",
                              source="Policy PDF"):
            pass

    entries = trace_store.summary("call-demo")
    assert entries == [{
        "name": "execute_tool lookup_policy", "kind": "tool", "capability": "Capability 5 · Knowledge & policy",
        "tool": "lookup_policy", "source": "Policy PDF", "duration_ms": entries[0]["duration_ms"],
        "success": True, "at": entries[0]["at"], "turn": None,
    }]
