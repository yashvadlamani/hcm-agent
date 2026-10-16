# Tool-family implementation status

Last reviewed: 2026-10-06

This is the implementation-status source for the tool catalog in `catalog.py` and its
handlers in `domains.py`. Update this file whenever a tool is added, removed, wired into
a workflow, or connected to a real service. A callable tool is not necessarily a live
integration.

## Status key

- **Integrated** — used by the current application flow and backed by a configured source or service.
- **Reference** — callable, deterministic demo behavior; no production source or persistence is connected.
- **Not connected** — explicitly returns `not_configured`, denies use, or has no real service adapter.
- **Partial** — some enforcement or local behavior exists, but the advertised capability is not complete.

## Families

| Family | Functions | Status | Notes |
|---|---|---|---|
| Outreach | `check_outreach_eligibility`, `check_consent_dnc`, `check_calling_window`, `validate_contact`, `issue_call_authorization`, `record_call_attempt` | **Partial** | `CareOutreachGraph` invokes a mandatory LangChain preflight tool through LangGraph before dialing; consent, eligibility, time-window, contact and authorization checks run deterministically and can block ACS. Current decisions use the member-data record/reference gateway, not a connected consent or outreach-policy service. Authorization is an in-process short-lived token. `record_call_attempt` returns evidence but does not persist it. |
| Communication / accessibility | `get_language_preference`, `get_accessibility_preferences`, `get_contact_preference`, `configure_voice_and_asr`, `request_interpreter_or_relay`, `start_outbound_call` | **Partial** | Preference reads and voice/locale selection are reference behavior; no preference system or interpreter/relay service is connected. Accommodation requests return `not_configured`. Catalog `start_outbound_call` is deliberately denied; the separate, authorized ACS adapter is integrated and is invoked as an LLM-selected tool only after preflight succeeds. |
| Identity | `confirm_member`, `verify_full_name`, `verify_dob`, `issue_and_verify_otp`, `handle_low_asr_confidence`, `verify_authorized_representative`, `record_verification_failure` | **Partial** | The live call's name and DOB steps are integrated: GPT interprets the spoken answer, LangGraph calls the verification tool, and GPT reviews its result. Name acceptance is currently deterministic against the server-selected member record (exact, first-name, or bounded phonetic match); DOB must normalize to the exact stored date. This was chosen as a security boundary, not mainly for latency: the LLM must not be able to override a failed credential check. The deterministic phonetic threshold can still reject legitimate ASR variants, so Phase 2 plans LLM-assisted name adjudication behind server-side constraints. OTP delivery is not connected. Affirmation, ASR threshold, and representative checks are reference-only; verification-failure audit is in memory. |
| Care context / follow-up | `get_safe_outreach_brief`, `get_approved_goals`, `get_recent_outreach_summary`, `get_care_team_route`, `create_follow_up_task`, `record_outreach_outcome` | **Partial** | Reads return only supplied profile values or safe defaults; no care-management/CRM source is connected. Follow-up task creation returns `not_configured`; route selection and outcome recording do not dispatch or persist to a queue/system. |
| Approved guidance | `search_approved_policy`, `get_member_education_script`, `validate_source_version` | **Reference** | Filters and validates documents/scripts passed to the handler. There is no connected approved-content repository, search/RAG index, or authoritative source-version service, so this is not yet production-grounded guidance. |
| Benefits / navigation / requests | `lookup_benefit`, `check_program_eligibility`, `get_covered_service_info`, `provider_directory_search`, `get_location_or_contact`, `lookup_transport_or_support`, `request_callback`, `request_appointment`, `confirm_request_status` | **Partial** | Benefit lookup can use the selected demo member's `profile` and is exercised by an offline test. Other lookups operate on supplied reference data; no payer benefit API, eligibility system, provider directory, or support-service directory is connected. Callback and appointment requests return `not_configured`; request status only reflects supplied status. |
| Safety / escalation | `assess_emergency`, `get_911_or_988_script`, `create_urgent_alert`, `create_clinical_review_task`, `route_member_distress`, `create_safety_follow_up` | **Partial** | The conversation path has a deterministic emergency keyword safety net and fixed emergency replies; the assessment/script tools are callable reference tools, not a connected clinical service. Urgent alerts, clinical-review tasks, distress routing, and safety follow-up are not connected and report `not_configured`. |
| Security / operations | `authorize_tool_call`, `enforce_member_scope`, `apply_tool_allowlist`, `enforce_role_or_tenant_scope`, `minimize_prompt_context`, `redact_for_logs`, `classify_sensitive_data`, `apply_retention_policy`, `detect_prompt_injection`, `sanitize_untrusted_content`, `validate_rag_source`, `apply_output_dlp`, `audit_event`, `record_policy_decision`, `raise_security_incident`, `apply_rate_limit`, `apply_circuit_breaker` | **Partial** | Actual controls include per-tool allowlisting, required-scope checks, member-ID boundary checks, server-bound context, and minimized in-memory audit events in `ToolGateway`. The grouped security tools are mostly reference checks: redaction/injection detection are simple heuristics; retention, DLP, incident handling, rate limiting and circuit breaking are not backed by persistent/enforcing services. Tenant/role authorization needs a real identity/authorization provider before production. |

## Shared implementation

All catalog entries are exposed as typed LangChain `StructuredTool`s and dispatched via
the shared LangGraph agent loop. Tool results are reviewed by the model, but authorization,
identity comparison, consent, emergency wording, and other safety-critical decisions remain
server-side/deterministic. The gateway audit log and default member data are in-process/demo
resources, not durable production integrations.

Primary code: `catalog.py` (families and LangChain schemas), `domains.py` (reference
handlers), `gateway.py` (scope and audit boundary), `workflows/graph.py` (LangGraph loop),
`workflows/outreach.py` and `telephony/outbound.py` (authorized outbound flow).

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
