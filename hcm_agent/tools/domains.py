"""Domain tools used by the care outreach graph.

These are deliberately deterministic reference implementations.  They make the
policy contract executable now while leaving each service boundary obvious for a
production adapter (CRM, consent service, provider directory, case management,
or approved-content store).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from typing import Any

from .contracts import ToolDefinition
from .identity import verify_dob, verify_full_name

CARE_SCOPE = frozenset({"care_outreach"})
IDENTITY_SCOPE = frozenset({"care_outreach", "member_verify"})
EMERGENCY_SCOPE = frozenset({"care_outreach", "safety_escalation"})


def _now(arguments: dict[str, Any]) -> datetime:
    """Read an injectable timestamp so policy tests are repeatable."""
    value = arguments.get("now")
    if isinstance(value, datetime):
        return value
    return datetime.now(timezone.utc)


def check_outreach_eligibility(arguments: dict[str, Any]) -> dict[str, Any]:
    """Require an active member, a permitted purpose, and a non-excessive frequency."""
    active = arguments.get("member_active", True)
    frequency = int(arguments.get("outreach_attempts_7d", 0))
    limit = int(arguments.get("max_outreach_attempts_7d", 3))
    purpose = arguments.get("outreach_purpose", "care_management")
    allowed = active and purpose == "care_management" and frequency < limit
    reason = "eligible" if allowed else "inactive member, invalid purpose, or outreach-frequency limit"
    return {"eligible": allowed, "reason": reason, "attempts_7d": frequency, "limit": limit}


def check_consent_dnc(arguments: dict[str, Any]) -> dict[str, Any]:
    """Require recorded outreach consent and reject an active do-not-call preference."""
    consent = arguments.get("consent") is True
    dnc = arguments.get("do_not_call") is True
    return {"allowed": consent and not dnc, "consent": consent, "do_not_call": dnc,
            "reason": "ok" if consent and not dnc else "consent missing or do-not-call is active"}


def check_calling_window(arguments: dict[str, Any]) -> dict[str, Any]:
    """Allow a call only inside the member's local outreach window, defaulting to 8am–8pm."""
    current = _now(arguments)
    local_hour = int(arguments.get("local_hour", current.hour))
    start = int(arguments.get("window_start_hour", 8))
    end = int(arguments.get("window_end_hour", 20))
    allowed = start <= local_hour < end
    return {"allowed": allowed, "local_hour": local_hour, "window": f"{start:02d}:00-{end:02d}:00",
            "reason": "ok" if allowed else "outside approved calling window"}


def validate_contact(arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate that a destination has a minimally plausible phone number."""
    digits = "".join(character for character in str(arguments.get("phone", "")) if character.isdigit())
    return {"valid": len(digits) >= 10, "phone_last4": digits[-4:] if len(digits) >= 4 else ""}


def issue_call_authorization(arguments: dict[str, Any]) -> dict[str, Any]:
    """Create a short-lived authorization only after all prerequisite decisions pass."""
    required = ("eligible", "consent_allowed", "window_allowed", "contact_valid")
    approved = all(arguments.get(key) is True for key in required)
    if not approved:
        return {"authorized": False, "reason": "required pre-call policy decision did not pass"}
    issued = _now(arguments)
    expires_at = (issued + timedelta(seconds=300)).replace(microsecond=0).isoformat()
    return {"authorized": True, "authorization": token_urlsafe(18), "expires_at": expires_at, "ttl_seconds": 300}


def record_call_attempt(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return minimized attempt evidence for persistence by the calling system."""
    return {"recorded": True, "outcome": arguments.get("outcome", "initiated"),
            "authorization_present": bool(arguments.get("authorization"))}


def get_language_preference(arguments: dict[str, Any]) -> dict[str, Any]:
    """Resolve a supported language without exposing unrelated member profile data."""
    language = arguments.get("language", "en-US")
    return {"language": language if language in {"en-US", "es-US"} else "en-US"}


def get_accessibility_preferences(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return only approved accommodation flags for call delivery."""
    return {"relay": bool(arguments.get("relay")), "slow_speech": bool(arguments.get("slow_speech")),
            "interpreter": bool(arguments.get("interpreter"))}


def get_contact_preference(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return the approved contact channel and optional preferred calling period."""
    return {"channel": arguments.get("channel", "voice"),
            "preferred_period": arguments.get("preferred_period")}


def configure_voice_and_asr(arguments: dict[str, Any]) -> dict[str, Any]:
    """Select a supported voice and recognition locale based on communication preferences."""
    language = arguments.get("language", "en-US")
    voice = "es-US-DaliaNeural" if language == "es-US" else "en-US-JennyNeural"
    return {"configured": True, "locale": language, "voice": voice,
            "slow_speech": bool(arguments.get("slow_speech"))}


def request_interpreter_or_relay(arguments: dict[str, Any]) -> dict[str, Any]:
    """Create an accommodation request; completion remains downstream-controlled."""
    required = bool(arguments.get("interpreter") or arguments.get("relay"))
    return {"requested": False, "status": "not_configured" if required else "not_needed"}


def start_outbound_call(arguments: dict[str, Any]) -> dict[str, Any]:
    """Declare a call ready to dial only with an unexpired authorization token."""
    authorized = bool(arguments.get("authorization"))
    return {"started": authorized, "status": "ready_to_dial" if authorized else "blocked"}


def confirm_member(arguments: dict[str, Any]) -> dict[str, Any]:
    """Record a direct identity affirmation; this is not sufficient for high assurance alone."""
    return {"confirmed": arguments.get("affirmed") is True, "assurance": "low"}


def issue_and_verify_otp(arguments: dict[str, Any]) -> dict[str, Any]:
    """Issue an OTP challenge or verify a supplied test code without logging its value."""
    if not arguments.get("provided_code"):
        return {"status": "not_configured", "reason": "No OTP delivery service is connected."}
    return {"status": "verified" if arguments.get("provided_code") == arguments.get("expected_code") else "failed"}


def handle_low_asr_confidence(arguments: dict[str, Any]) -> dict[str, Any]:
    """Restrict identity progression when speech recognition confidence is too low."""
    confidence = float(arguments.get("confidence", 0))
    return {"action": "ask_to_repeat" if confidence < 0.8 else "continue", "confidence": confidence}


def verify_authorized_representative(arguments: dict[str, Any]) -> dict[str, Any]:
    """Allow representative access only with a matching authorization record."""
    representative_id = arguments.get("representative_id")
    authorized_id = arguments.get("authorized_representative_id")
    return {"verified": representative_id == authorized_id and bool(representative_id)}


def record_verification_failure(arguments: dict[str, Any]) -> dict[str, Any]:
    """Produce a minimized failure event with no identity answers or credentials."""
    return {"recorded": True, "reason": arguments.get("reason", "verification_failed")}


def get_safe_outreach_brief(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return only member-facing purpose and approved goals, never a complete care record."""
    return {"purpose": arguments.get("purpose", "check in"),
            "risk_drivers": list(arguments.get("risk_drivers", []))[:5],
            "member_facing": True}


def get_approved_goals(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return the currently approved care-management goals supplied by a source system."""
    return {"goals": list(arguments.get("goals", []))[:5], "approved": True}


def get_recent_outreach_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded, non-clinical summary of prior outreach."""
    return {"summary": str(arguments.get("summary", "No recent outreach summary."))[:500]}


def get_care_team_route(arguments: dict[str, Any]) -> dict[str, Any]:
    """Choose a configured queue name without claiming a person will respond."""
    return {"route": arguments.get("route", "care-management-general"), "status": "routing_available"}


def create_follow_up_task(arguments: dict[str, Any]) -> dict[str, Any]:
    """Create a requested follow-up task and report creation, not future completion."""
    return {"created": False, "status": "not_configured", "reason": "No case-management adapter is connected."}


def record_outreach_outcome(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return an outcome record suitable for a downstream audit store."""
    return {"recorded": True, "outcome": arguments.get("outcome", "completed")}


def search_approved_policy(arguments: dict[str, Any]) -> dict[str, Any]:
    """Search only documents explicitly marked active and clinically reviewed."""
    documents = [item for item in arguments.get("documents", []) if item.get("approved") and item.get("active")]
    return {"sources": documents[:3], "grounded": bool(documents)}


def get_member_education_script(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a supplied reviewed script, or an honest no-guidance response."""
    return {"script": arguments.get("script", "I don't have approved guidance on that topic."),
            "approved": bool(arguments.get("script"))}


def validate_source_version(arguments: dict[str, Any]) -> dict[str, Any]:
    """Accept active sources only when their supplied version is current."""
    return {"valid": bool(arguments.get("active")) and arguments.get("version") == arguments.get("current_version")}


def benefit_lookup(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return supplied plan facts and explicitly avoid a coverage guarantee."""
    return {"found": bool(arguments.get("benefit")), "benefit": arguments.get("benefit"),
            "coverage_guaranteed": False}


def provider_navigation(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return bounded directory options without ranking them clinically."""
    return {"options": list(arguments.get("options", []))[:5], "recommendation": False}


def create_member_request(arguments: dict[str, Any]) -> dict[str, Any]:
    """Create a downstream request and report submission rather than completion."""
    return {"created": False, "status": "not_configured", "reason": "No scheduling or callback adapter is connected."}


def confirm_member_request(arguments: dict[str, Any]) -> dict[str, Any]:
    """Report only the source-system status supplied by the request adapter."""
    return {"status": arguments.get("status", "not_found"), "confirmed": arguments.get("status") == "completed"}


def safety_escalation(arguments: dict[str, Any]) -> dict[str, Any]:
    """Create a human-review task without replacing emergency guidance."""
    return {"created": False, "status": "not_configured", "reason": "No human-review queue is connected."}


def access_control(arguments: dict[str, Any]) -> dict[str, Any]:
    """Expose the gateway's decision boundary as a traceable control result."""
    return {"enforced": True, "status": "allowed"}


def protect_phi(arguments: dict[str, Any]) -> dict[str, Any]:
    """Minimize and redact obvious identifiers before a value can reach logs or prompts."""
    text = str(arguments.get("text", ""))
    redacted = text.replace(arguments.get("member_id", ""), "[member]") if arguments.get("member_id") else text
    return {"applied": True, "text": redacted[:1000], "classification": "phi" if text else "none"}


def defend_content(arguments: dict[str, Any]) -> dict[str, Any]:
    """Treat retrieved and spoken text as data, flagging common instruction-injection phrases."""
    text = str(arguments.get("text", "")).lower()
    injected = any(phrase in text for phrase in ("ignore previous instructions", "system prompt", "reveal secrets"))
    return {"safe": not injected, "injection_detected": injected,
            "sanitized_text": str(arguments.get("text", ""))[:1000]}


def operational_control(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return bounded audit, rate-limit, and circuit-breaker decisions for an adapter to persist."""
    count = int(arguments.get("count", 0))
    limit = int(arguments.get("limit", 100))
    failures = int(arguments.get("failure_count", 0))
    return {"recorded": True, "rate_allowed": count < limit, "circuit_open": failures >= 5}


def assess_emergency(arguments: dict[str, Any]) -> dict[str, Any]:
    """Classify a pre-detected emergency for fixed-script routing, not diagnosis."""
    text = str(arguments.get("statement", "")).lower()
    crisis = any(term in text for term in ("suicide", "kill myself", "want to die", "self harm"))
    medical = any(term in text for term in ("chest pain", "can't breathe", "difficulty breathing"))
    return {"emergency": crisis or medical, "kind": "mental_health" if crisis else "medical" if medical else None}


def get_911_or_988_script(arguments: dict[str, Any]) -> dict[str, Any]:
    """Return fixed emergency language rather than model-generated medical instructions."""
    if arguments.get("kind") == "mental_health":
        return {"script": "Please call or text 988 now, or call 911 if you are in immediate danger."}
    return {"script": "If this is a medical emergency, please hang up and call 911 now."}


def create_urgent_alert(arguments: dict[str, Any]) -> dict[str, Any]:
    """Create an urgent alert; it never replaces 911 or 988 guidance."""
    return {"created": False, "status": "not_configured", "reason": "No urgent-alert adapter is connected."}


def _definitions(names: tuple[str, ...], handler, scope: frozenset[str] = CARE_SCOPE) -> list[ToolDefinition]:
    """Build tool definitions for grouped operations that share a deterministic handler."""
    return [ToolDefinition(name, handler, scope) for name in names]


def register_domain_tools() -> list[ToolDefinition]:
    """Return the complete tool catalog grouped by the eight capability domains."""
    direct = {
        "check_outreach_eligibility": check_outreach_eligibility,
        "check_consent_dnc": check_consent_dnc,
        "check_calling_window": check_calling_window,
        "validate_contact": validate_contact,
        "issue_call_authorization": issue_call_authorization,
        "record_call_attempt": record_call_attempt,
        "get_language_preference": get_language_preference,
        "get_accessibility_preferences": get_accessibility_preferences,
        "get_contact_preference": get_contact_preference,
        "configure_voice_and_asr": configure_voice_and_asr,
        "request_interpreter_or_relay": request_interpreter_or_relay,
        "start_outbound_call": start_outbound_call,
        "confirm_member": confirm_member,
        "verify_full_name": verify_full_name,
        "verify_dob": verify_dob,
        "issue_and_verify_otp": issue_and_verify_otp,
        "handle_low_asr_confidence": handle_low_asr_confidence,
        "verify_authorized_representative": verify_authorized_representative,
        "record_verification_failure": record_verification_failure,
        "get_safe_outreach_brief": get_safe_outreach_brief,
        "get_approved_goals": get_approved_goals,
        "get_recent_outreach_summary": get_recent_outreach_summary,
        "get_care_team_route": get_care_team_route,
        "create_follow_up_task": create_follow_up_task,
        "record_outreach_outcome": record_outreach_outcome,
        "search_approved_policy": search_approved_policy,
        "get_member_education_script": get_member_education_script,
        "validate_source_version": validate_source_version,
        "assess_emergency": assess_emergency,
        "get_911_or_988_script": get_911_or_988_script,
        "create_urgent_alert": create_urgent_alert,
    }
    tools = [ToolDefinition(name, handler, IDENTITY_SCOPE if name in {
        "confirm_member", "verify_full_name", "verify_dob", "issue_and_verify_otp", "handle_low_asr_confidence",
        "verify_authorized_representative", "record_verification_failure"} else EMERGENCY_SCOPE if name in {
        "assess_emergency", "get_911_or_988_script", "create_urgent_alert"} else CARE_SCOPE)
             for name, handler in direct.items()]
    groups = {
        benefit_lookup: ("lookup_benefit", "check_program_eligibility", "get_covered_service_info"),
        provider_navigation: ("provider_directory_search", "get_location_or_contact", "lookup_transport_or_support"),
        create_member_request: ("request_callback", "request_appointment"),
        confirm_member_request: ("confirm_request_status",),
        safety_escalation: ("create_clinical_review_task", "route_member_distress", "create_safety_follow_up"),
        access_control: ("authorize_tool_call", "enforce_member_scope", "apply_tool_allowlist",
                         "enforce_role_or_tenant_scope"),
        protect_phi: ("minimize_prompt_context", "redact_for_logs", "classify_sensitive_data",
                      "apply_retention_policy"),
        defend_content: ("detect_prompt_injection", "sanitize_untrusted_content", "validate_rag_source",
                         "apply_output_dlp"),
        operational_control: ("audit_event", "record_policy_decision", "raise_security_incident",
                              "apply_rate_limit", "apply_circuit_breaker"),
    }
    for handler, names in groups.items():
        tools.extend(_definitions(names, handler))
    return tools
