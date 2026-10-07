"""Pre-call policy: GPT calls a LangChain tool; hard checks gate actual dialing."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from langchain_core.tools import tool

from ..tools import ToolCallContext, ToolGateway, build_default_gateway
from .graph import run_agent


@dataclass(frozen=True)
class OutreachRequest:
    """The privacy-minimized fields required for a pre-call authorization decision."""

    member_id: str
    phone: str
    tenant_id: str
    consent: bool
    do_not_call: bool
    local_hour: int
    outreach_attempts_7d: int = 0
    max_outreach_attempts_7d: int = 1
    member_active: bool = True
    language: str = "en-US"
    window_start_hour: int = 8
    window_end_hour: int = 20
    accessibility: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class OutreachResult:
    """The terminal policy decision produced before the telephony adapter can dial."""

    allowed: bool
    terminal_node: str
    reason: str
    authorization: str | None = None
    call_setup: dict[str, Any] = field(default_factory=dict)
    audit_ids: tuple[str, ...] = ()


class CareOutreachGraph:
    """One mandatory preflight tool, then GPT reviews the complete policy result."""

    def __init__(self, gateway: ToolGateway | None = None, llm=None):
        self.gateway = gateway or build_default_gateway()
        self.llm = llm

    def pre_call(self, request: OutreachRequest, actor_id="outreach-orchestrator") -> OutreachResult:
        from .. import config
        from ..agent.llm import create_llm

        context = ToolCallContext(actor_id, request.tenant_id, "care_management", request.member_id,
                                  frozenset({"care_outreach"}))
        arguments = {**asdict(request), "outreach_purpose": "care_management"}
        outcome = OutreachResult(False, "blocked", "preflight was not completed")

        @tool
        def authorize_outreach() -> dict:
            """Check eligibility, consent, local time and contact; authorize only when all pass."""
            nonlocal outcome
            evidence, audit = {}, []
            for name, decision_field, key in (
                ("check_outreach_eligibility", "eligible", "eligible"),
                ("check_consent_dnc", "allowed", "consent_allowed"),
                ("check_calling_window", "allowed", "window_allowed"),
                ("validate_contact", "valid", "contact_valid"),
                ("issue_call_authorization", "authorized", "authorized"),
            ):
                result = self.gateway.invoke(name, context, {**arguments, **evidence})
                audit.append(result.audit_id)
                if not result.allowed or result.data.get(decision_field) is not True:
                    outcome = OutreachResult(False, "blocked", result.reason or result.data.get("reason", name),
                                             audit_ids=tuple(audit))
                    return {"allowed": False, "reason": outcome.reason}
                evidence[key] = True
            authorization = result.data["authorization"]
            setup = self.gateway.invoke("configure_voice_and_asr", context,
                                        {"language": request.language, **request.accessibility})
            outcome = OutreachResult(True, "ready_to_dial", "all checks passed", authorization,
                                     setup.data, tuple([*audit, setup.audit_id]))
            return {"allowed": True, "ready_to_dial": True}

        llm = self.llm or create_llm(config.load())
        state = run_agent(llm.model, [authorize_outreach],
                          'Call authorize_outreach, then review its output. Return JSON {"allowed": true or false}. '
                          'Never approve a failed check. This authorizes a call; it does not dial.',
                          [{"role": "user", "content": "Evaluate this configured outreach request."}],
                          required_tool="authorize_outreach", max_rounds=1,
                          model_options=getattr(llm, "json_options", None))
        review = json.loads(state["messages"][-1].text)
        if review.get("allowed") is not True:
            return OutreachResult(False, "blocked", "model did not approve preflight", audit_ids=outcome.audit_ids)
        return outcome
