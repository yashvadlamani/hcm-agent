# Capability 7 — Safety and escalation

Last reviewed: 2026-10-10

This family is a deterministic safety boundary. Its emergency and latency decisions
are never generated or overridden by the LLM. The LangGraph safety guard runs before
each care turn; the phone server also invokes the response-latency tool around every
model-backed voice turn.

| Tool | Service offered | Status | Definition / integration |
|---|---|---|---|
| `assess_emergency` | Confirms an emergency and its kind. The keyword list in [`safety.py`](safety.py) decides first (the same list as the conversation's instant check); otherwise the conversation model's assessment is accepted when it names `medical` or `mental_health`. | Active | [`domains.py`](domains.py) `assess_emergency`; [`graph.py`](../workflows/graph.py) `_safety_guard`; [`conversation.py`](../agent/conversation.py) `_escalate` |
| `get_911_or_988_script` | Returns Clara's fixed 911 or 988 wording. The sentence about flagging the call for the care team is included only when an alert was recorded. | Active | [`safety.py`](safety.py) `emergency_script`; `_safety_guard`; `_escalate` |
| `create_urgent_alert` | Records an urgent alert, and posts it to a webhook when one is configured. Refused without an assessed emergency. | Active, recording only | [`domains.py`](domains.py) `create_urgent_alert`; `_escalate` |
| `enforce_response_latency` | Applies the 8-second filler, 15-second response deadline, and repeated-failure circuit policy. | Active for ACS phone calls | [`domains.py`](domains.py) `enforce_response_latency`; [`server.py`](../telephony/server.py) `on_speech` and `_latency_control` |
| `create_clinical_review_task` | Records a clinician review task: urgent and due the same business day after an emergency, routine otherwise. | Active, recording only | [`domains.py`](domains.py); `_escalate` |
| `create_safety_follow_up` | Records a follow-up check-in due the next business day (weekends skipped). | Active, recording only | [`domains.py`](domains.py); `_escalate` |
| `route_member_distress` | Chooses a care-team queue name: `nurse-triage`, `behavioral-health-crisis` or `care-management-general`. No call is transferred. | Reference | [`domains.py`](domains.py); `_escalate` |

## Emergency escalation

Whichever layer detects an emergency (the conversation's keyword check, the graph's
`capability_7_safety_guard`, the model's assessment, or Azure's content filter), the turn ends in
`HCMVoiceAgent._emergency_turn`, which calls `_escalate`. That runs the tools through the gateway in a
fixed order, in code rather than by the model's choice: `assess_emergency`, `route_member_distress`,
`create_urgent_alert`, `create_clinical_review_task`, `create_safety_follow_up`, then
`get_911_or_988_script`.

- Recording can never block or delay the 911 or 988 message. If the alert cannot be saved, Clara gives
  the message without saying the call was flagged.
- When the model calls these tools itself through `capability_7_safety`, the kind and reason come from
  a prior `assess_emergency` result in graph state. The model cannot supply them.
- Records hold the kind, a short reason, source, member ID, tenant ID, call ID, queue, priority and due
  date. No names, dates of birth, phone numbers or transcripts.

The escalation log (`EscalationStore` in [`safety.py`](safety.py)) is always in memory and in the server
log (`ESCALATION ESC-…`), and appears on the live dashboard. Set `ESCALATION_LOG_PATH` to also append to
a JSON-lines file, and `ESCALATION_WEBHOOK_URL` to post urgent alerts to a Teams or Slack channel.

**Recorded, not dispatched.** No paging, case-management or care-team system is connected, nobody is
called or transferred, and nothing tracks whether a record was acted on. Without the file setting,
records are lost when the server restarts.

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
