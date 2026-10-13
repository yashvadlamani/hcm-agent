"""The seven draft security tools: gateway decisions, the audit log, rate limits and circuit breakers."""

import json

import pytest

from hcm_agent.tools import ToolCallContext, build_default_gateway, security

CONTEXT = ToolCallContext("clara", "test", "care_management", "m1", frozenset({"care_outreach"}))


@pytest.fixture(autouse=True)
def fresh_state(tmp_path):
    log = security.AuditLog(str(tmp_path / "audit.jsonl"))
    security.use_audit_log(log)
    security.reset()
    yield log
    security.use_audit_log(None)
    security.reset()


def test_access_tools_report_the_gateways_real_decisions():
    gateway = build_default_gateway()

    def run(name, **arguments):
        return gateway.invoke(name, CONTEXT, {"member_id": "m1", **arguments}).data

    assert run("authorize_tool_call", tool="lookup_policy")["authorized"] is True
    # This caller has no safety scope, a made-up tool isn't on the allow-list, and m2 is another member.
    assert run("authorize_tool_call", tool="create_urgent_alert")["reason"] == "caller lacks required scope"
    assert run("authorize_tool_call", tool="delete_everything")["reason"] == "tool is not allowlisted"
    assert run("authorize_tool_call", tool="lookup_policy", requested_member_id="m2")["authorized"] is False
    assert run("apply_tool_allowlist", tool="lookup_policy")["allowlisted"] is True
    assert run("apply_tool_allowlist", tool="delete_everything")["allowlisted"] is False
    assert run("enforce_member_scope", requested_member_id="m1")["in_scope"] is True
    assert run("enforce_member_scope", requested_member_id="m2")["in_scope"] is False


def test_tool_calls_events_and_policy_decisions_reach_the_audit_file_without_arguments(fresh_state, tmp_path):
    gateway = build_default_gateway()
    gateway.invoke("audit_event", CONTEXT, {"member_id": "m1", "event": "identity verification failed twice"})
    decision = gateway.invoke("record_policy_decision", CONTEXT, {
        "member_id": "m1", "policy": "pre_call_outreach", "outcome": "blocked", "reason": "do-not-call is active",
        "name": "Maria Lopez", "date_of_birth": "1990-01-02"}).data
    assert decision["recorded"] is True and decision["durable"] is True
    unclear = gateway.invoke("record_policy_decision", CONTEXT, {"policy": "x", "outcome": "maybe"}).data
    assert unclear["recorded"] is False
    gateway.invoke("create_urgent_alert", CONTEXT, {"member_id": "m1", "kind": "medical"})  # denied: no safety scope

    lines = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [entry["type"] for entry in lines].count("tool_call") == 4
    assert {"event", "policy_decision"} <= {entry["type"] for entry in lines}
    denied = [entry for entry in lines if entry.get("tool") == "create_urgent_alert"]
    assert denied[0]["allowed"] is False and denied[0]["member_id"] == "m1"
    assert "Maria" not in json.dumps(lines) and "1990" not in json.dumps(lines)


def test_rate_limits_and_circuit_breakers_keep_real_state(monkeypatch):
    limiter = security.RateLimiter()
    assert [limiter.hit("m1:otp", 2, 60, now=t)["allowed"] for t in (0, 1, 2)] == [True, True, False]
    assert limiter.hit("m1:otp", 2, 60, now=2)["retry_after_seconds"] == 58
    assert limiter.hit("m1:otp", 2, 60, now=61)["allowed"] is True  # the window moved on

    gateway = build_default_gateway()

    def breaker(action):
        return gateway.invoke("apply_circuit_breaker", CONTEXT, {"dependency": "pharmacy_api", "action": action}).data

    assert breaker("check")["allowed"] is True
    assert [breaker("failure")["circuit_open"] for _ in range(3)] == [False, False, True]
    assert breaker("check")["allowed"] is False and breaker("success")["allowed"] is True

    # The gateway limits ordinary tools per call, but never emergency tools.
    monkeypatch.setattr("hcm_agent.tools.gateway.TOOL_CALLS_PER_MINUTE", 2)
    limited = build_default_gateway()
    results = [limited.invoke("apply_tool_allowlist", CONTEXT, {"tool": "lookup_policy"}) for _ in range(3)]
    assert [r.allowed for r in results] == [True, True, False] and results[2].reason == "tool-call rate limit reached"
    safety_context = ToolCallContext("clara", "test", "care_management", "m1",
                                     frozenset({"care_outreach", "safety_escalation"}))
    assert limited.invoke("assess_emergency", safety_context, {"statement": "chest pain"}).allowed is True
