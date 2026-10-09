from hcm_agent.tools.catalog import FAMILIES
from hcm_agent.tools.response_latency import ResponseLatencyCircuit


def test_response_latency_circuit_opens_after_three_failures_and_recovers():
    circuit = ResponseLatencyCircuit(failure_threshold=3, cooldown_seconds=60)

    assert circuit.start(now=10).allowed is True
    assert circuit.fail(now=10).circuit_open is False
    assert circuit.fail(now=11).circuit_open is False
    opened = circuit.fail(now=12)
    assert opened.circuit_open is True
    assert opened.retry_after_seconds == 60
    assert circuit.start(now=71).circuit_open is True
    assert circuit.start(now=72).allowed is True


def test_latency_policy_is_registered_in_safety_family():
    assert "enforce_response_latency" in FAMILIES["safety"]
