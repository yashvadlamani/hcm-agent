# Capability 7 — Safety and escalation

Last reviewed: 2026-10-08

This family is a deterministic safety boundary. Its emergency and latency decisions
are never generated or overridden by the LLM. The LangGraph safety guard runs before
each care turn; the phone server also invokes the response-latency tool around every
model-backed voice turn.

| Tool | Service offered | Status | Definition / integration |
|---|---|---|---|
| `assess_emergency` | Detects configured crisis and medical-emergency phrases for fixed routing. | Active | [`domains.py`](domains.py) `assess_emergency`; [`graph.py`](../workflows/graph.py) `_safety_guard` |
| `get_911_or_988_script` | Returns fixed 911 or 988 language rather than clinical advice. | Active | [`domains.py`](domains.py) `get_911_or_988_script`; [`graph.py`](../workflows/graph.py) `_safety_guard` |
| `create_urgent_alert` | Creates an urgent human alert. | Not connected | [`domains.py`](domains.py) `create_urgent_alert` returns `not_configured` |
| `enforce_response_latency` | Applies the 8-second filler, 15-second response deadline, and repeated-failure circuit policy. | Active for ACS phone calls | [`domains.py`](domains.py) `enforce_response_latency`; [`server.py`](../telephony/server.py) `on_speech` and `_latency_control` |
| `create_clinical_review_task`, `route_member_distress`, `create_safety_follow_up` | Care-team routing and follow-up. | Not connected | [`domains.py`](domains.py) `safety_escalation` returns `not_configured` |

## Voice response-latency policy

| Condition | Clara's behavior |
|---|---|
| A response takes 8 seconds | Clara plays: “Thanks for your patience. I'm checking that now.” The original turn continues. |
| A response completes by 15 seconds | Clara delivers the normal guarded response and resets the failure count. |
| A response exceeds 15 seconds or fails | Clara discards its late reply for that turn and says: “I'm having trouble connecting right now. Please try again in a moment.” |
| Three failed or over-deadline turns | The process-local circuit opens for 60 seconds. New model turns receive the same connection fallback immediately. |

The circuit is intentionally process-local in this demo and resets on server restart. A
production multi-instance deployment needs a shared, expiry-backed circuit store and
durable safety/audit events. A request that has already reached an external model cannot
always be force-cancelled by its SDK; once it completes, its result is ignored and Clara
does not speak it. While it is still running, additional caller speech gets a short
“still checking” response rather than starting a second concurrent model turn.

`enforce_response_latency` is registered as a typed LangChain safety tool in
[`catalog.py`](catalog.py), but it is called deterministically by the telephony adapter,
not chosen by the LLM. That is intentional: a model must not be able to extend its own
deadline or close the circuit.
