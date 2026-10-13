# Tool-family implementation status

Last reviewed: 2026-10-08

This is the implementation-status source for the tool catalog in `catalog.py`, the
capability ownership list in `tools.py`, and handlers in `domains.py`. Update this file
whenever a tool is added, removed, wired into a workflow, or connected to a real service.
A callable tool is not necessarily a live integration.

## Status key

- **Integrated** — used by the current application flow and backed by a configured source or service.
- **Reference** — callable, deterministic demo behavior; no production source or persistence is connected.
- **Not connected** — explicitly returns `not_configured`, denies use, or has no real service adapter.
- **Partial** — some enforcement or local behavior exists, but the advertised capability is not complete.

## Interactive CLI readiness

`clara-chat interactive --member Himanshu` supports the local, fictional demo path.
Capabilities 1–2 run only before a real outbound call, capability 3 gates care access, and
capabilities 4–8 are available after verification. Within capabilities 4–6, only the six
selected tools below are registered; other candidate tools were removed from the callable catalog.

| Capability | Tools | Interactive CLI status | What may block or limit the conversation |
|---|---|---|---|
| 1. Outreach | `check_outreach_eligibility`, `check_consent_dnc`, `check_calling_window`, `validate_contact`, `issue_call_authorization`, `record_call_attempt` | Not used by local interactive chat | It runs before an ACS call. Consent, DNC, calling-window, contact, frequency, or eligibility failures block dialing. The authorization and audit are in-process only. |
| 2. Communication / accessibility | `get_language_preference`, `get_accessibility_preferences`, `get_contact_preference`, `configure_voice_and_asr`, `request_interpreter_or_relay`, `start_outbound_call` | Not used by local interactive chat | Voice/locale behavior is reference-only. Interpreter/relay is `not_configured`; catalog dialing is denied and the authorized ACS adapter is separate. |
| 3. Identity | `confirm_member`, `verify_full_name`, `verify_dob`, `issue_and_verify_otp`, `handle_low_asr_confidence`, `verify_authorized_representative`, `record_verification_failure` | Active | Full name and DOB are required. A mismatch, an ambiguous/missing member record, or an identity-model/service failure ends the call. OTP and representative verification are not connected. |
| [4. Care-management context](cap4_care_management_context.md) | `get_safe_outreach_brief`, `get_approved_goals` | Active for demo members | Results are bounded to the selected member's fictional demo context. No live care-management or approved-goals source is connected. |
| [5. Approved knowledge & policy](cap5_approved_knowledge_policy.md) | `search_diabetes_playbook`, `lookup_policy` | Active | Playbook content is draft education only and never medication advice. Policy lookup searches only the supplied 2025 PDF; a missing passage cannot confirm coverage. |
| [6. Care navigation & fulfilment](cap6_care_navigation_fulfilment.md) | `provider_directory_search`, `request_appointment` | Active as a local demo | Providers are fictional. Scheduling is enabled only in local demo mode, stores a fictional in-memory booking, and returns alternatives for weekends, unavailable times, or unknown providers. Non-demo scheduling is `not_configured`. |
| [7. Safety / escalation](../safety.md) | `assess_emergency`, `get_911_or_988_script`, `create_urgent_alert`, `enforce_response_latency`, `create_clinical_review_task`, `route_member_distress`, `create_safety_follow_up` | Active safety checks; escalation recording active; latency control active for ACS calls | Emergency detection returns fixed 911/988 wording and ends the call. Every emergency also runs the escalation tools, which record an urgent alert, a clinical review task and a next-business-day safety follow-up in the escalation log (see [`safety.md`](../safety.md)). At 8 seconds Clara plays a brief filler; at 15 seconds it gives a connection fallback and ignores a late response. Three slow/failed turns open a 60-second process-local circuit. Escalations are recorded, not dispatched: no paging, case-management or care-team system receives them, and nobody is transferred. |
| 8. Security / operations | `FAMILIES["security"]` tools | Active safety checks; 13 of 17 tools are working drafts | Member scope and prompt-injection checks run during care turns. Injection-like content is blocked. **Working drafts** (`security.py`): `authorize_tool_call`, `enforce_member_scope` and `apply_tool_allowlist` report the gateway's real decisions; `audit_event` and `record_policy_decision` write to the audit log; `apply_rate_limit` and `apply_circuit_breaker` keep real state. Every tool call is now also written to the audit log (durable when `AUDIT_LOG_PATH` is set), the pre-call decision is recorded, `classify_sensitive_data` labels text (direct identifier, health, financial) and redacts identifiers by rule; `detect_prompt_injection` flags seven kinds of attempt (instruction override, role hijack, prompt or data exfiltration, safety bypass, tool abuse, markup) by rule. Both run in the call flow: caller words are checked for injection before any model sees them, in the identity steps and in the conversation, and patient words are redacted before they reach the dashboard, the saved transcript and the log. Each call is limited to `TOOL_CALLS_PER_MINUTE` ordinary tool calls (emergency and identity tools are exempt), and the escalation webhook sits behind a circuit breaker. State is per process and lost on restart. `redact_for_logs` removes direct identifiers, and the same redaction is applied to every server log line. `minimize_prompt_context` cuts the call context down before each model turn: the prompt gets only the fields it reads, the care tools get no identifier fields, and free text is redacted and capped. `validate_rag_source` keeps only passages from a registered source (the diabetes playbook or the plan policy) and attaches warnings when the source is unapproved or out of date. `sanitize_untrusted_content` removes instruction-like text from care, guidance and navigation tool output before the model reads it. All of these are rule-based, with no model check, so unusual phrasing can get past them. **Still placeholders:** the other 4 tools (`enforce_role_or_tenant_scope`, `apply_retention_policy`, `apply_output_dlp`, `raise_security_incident`). |

## Shared implementation

All catalog entries are exposed as typed LangChain `@tool` definitions and dispatched via
the shared LangGraph capability loop. The outreach-brief and goals tools use empty argument schemas
so the LLM can select them but cannot supply or alter the underlying member facts. Tool results are
reviewed by the model, but authorization,
identity comparison, consent, emergency wording, and other safety-critical decisions remain
server-side/deterministic. The gateway audit log and default member data are in-process/demo
resources, not durable production integrations.

`lookup_policy` uses LangChain PDF loading/splitting, FastEmbed local embeddings, Chroma vector
retrieval, and an LLM-selected query. Extra LLM query expansion is opt-in through
`CLARA_RAG_QUERY_EXPANSION=1` so it does not add a paid model round-trip to every care answer.
For an out-of-pocket-limit question, the returned PDF table is parsed into a source-bound exact-answer
field; Clara must preserve those values and cite its page. It indexes the supplied
`data/policies/sbc-gpsd69bceiilo-il-2025.pdf`; retrieved passages include page numbers. The system
does not infer that this source has been reviewed or approved by the plan owner.
`provider_directory_search` reads the explicitly fictional data in `data/provider_directory.json` and
includes each matching demo provider's next three unbooked weekday demo slots.
`request_appointment` uses `scheduling.py` for its bounded local demonstration: 09:00, 10:00, 11:00,
13:00, 14:00, and 15:00 America/Chicago, Monday–Friday. It prevents duplicate bookings within the
running process, offers the next three dated slots when needed, and stores at most 100 simulated
appointments in memory. It does not contact a clinic or create a real appointment.

Primary code: `tools.py` (eight node-to-tool lists and stage availability), `catalog.py`
(decorated LangChain tools and schemas), `domains.py` (reference handlers), `gateway.py`
(scope and audit boundary), `workflows/graph.py` (explicit LangGraph capability graph),
`workflows/outreach.py` and `telephony/outbound.py` (authorized outbound flow).

The phone response-deadline policy is documented in [`safety.md`](../safety.md). It is
enforced by `telephony/server.py` through the safety-family `enforce_response_latency`
tool, not left to an LLM decision.

## Local phone transcript history

The authenticated `/live` view retains the newest 50 *completed* demo calls in the local SQLite file
`data/transcripts/clara_calls.sqlite3` and reloads them after `clara-server` restarts. The file is
ignored by Git because it can contain caller speech and other PHI-like data. It is a local-demo aid,
not an approved production transcript/audit store; delete that file to remove local history.

## Updating this matrix

When a tool changes, verify the catalog and registered handler, identify the actual caller
workflow, and update that function's status and notes here. Promote **Reference** or
**Not connected** only after a real adapter is configured and an offline test verifies its
success and failure behavior. Never mark an operation integrated just because the model
can select its LangChain tool.

## Phase 2 plan

Identity improvements not required for the currently working name-and-DOB flow:

| Planned work | Functions | Plan / acceptance boundary |
|---|---|---|
| LLM-assisted name adjudication | `verify_full_name` | Let the LLM assess whether the caller's *actually stated* name plausibly matches the server-bound expected name, including ASR/spelling variants. Keep the expected record server-selected; require a structured, reasoned decision; reject contradictory names, invented/missing values, and uncertain answers. The LLM must never override failed DOB or server-side policy checks. Add adversarial and ambiguous-name offline tests before enabling. |
| OTP verification | `issue_and_verify_otp` | Connect an approved OTP delivery/verification provider; never expose codes in prompts, transcripts, or audit logs. |
| Low-confidence speech handling | `handle_low_asr_confidence` | Connect the telephony ASR confidence signal to a repeat/stop decision and verify it cannot advance identity verification below the configured threshold. |
| Authorized representative verification | `verify_authorized_representative` | Resolve representative authority from an authoritative member/consent system, rather than caller-supplied reference values. |
| Durable verification audit | `record_verification_failure` | Persist minimized outcome events to an approved audit store without names, DOBs, OTPs, or raw speech. |

LLM-assisted name adjudication is for interpreting noisy speech, not replacing authentication
controls. Keep full DOB comparison exact and deterministic; do not use fuzzy DOB matching.
