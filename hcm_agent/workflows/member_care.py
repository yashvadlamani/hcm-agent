"""Verified-member care through the shared native LangGraph tool loop."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..tools import ToolCallContext, ToolGateway, build_default_gateway
from ..tools.catalog import TOOL_POLICY, build_tools


@dataclass(frozen=True)
class MemberTurnRequest:
    """Bounded inputs from telephony and authoritative member systems for one turn."""

    member_id: str
    tenant_id: str
    statement: str
    intent: str = "general"
    identity_method: str = "dob"
    affirmed: bool = False
    provided_name: str = ""
    expected_name: str = ""
    asr_confidence: float = 1.0
    provided_dob: str = ""
    expected_dob: str = ""
    provided_otp: str = ""
    expected_otp: str = ""
    representative_id: str = ""
    authorized_representative_id: str = ""
    profile: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemberTurnResult:
    """A terminal turn decision and safe context for the conversation agent."""

    terminal_node: str
    verified: bool
    member_context: dict[str, Any] = field(default_factory=dict)
    escalation: dict[str, Any] = field(default_factory=dict)
    audit_ids: tuple[str, ...] = ()


class MemberCareGraph:
    """All care families are selected by the model, rather than hard-coded intent branches."""

    def __init__(self, gateway: ToolGateway | None = None, llm=None):
        self.gateway = gateway or build_default_gateway()
        self.llm = llm

    def respond(self, llm, context, profile, system_prompt, messages, *, verified):
        tools = build_tools(self.gateway, context, profile, verified=verified)
        return llm.complete(system_prompt + "\n" + TOOL_POLICY, messages, json_mode=True, tools=tools)

    def handle_turn(self, request: MemberTurnRequest, actor_id="conversation-orchestrator") -> MemberTurnResult:
        """Standalone entry point, sharing the same identity and care tools as live calls."""
        from .. import config
        from ..agent.identity import verify_identity_turn
        from ..agent.llm import create_llm

        llm = self.llm or create_llm(config.load())
        context = ToolCallContext(actor_id, request.tenant_id, "care_management", request.member_id,
                                  frozenset({"care_outreach", "member_verify", "safety_escalation"}))
        record = {"name": request.expected_name, "date_of_birth": request.expected_dob}
        verified = request.identity_method == "dob" and request.affirmed and request.asr_confidence >= 0.8
        for phase, answer in (("verify_name", request.provided_name), ("verify_dob", request.provided_dob)):
            if verified:
                verified, _ = verify_identity_turn(llm, self.gateway, context, record, phase, answer)
        if not verified:
            return MemberTurnResult("restricted_identity", False)
        raw = self.respond(llm, context, request.profile,
                           'Help this verified member. Return JSON with a "reply" string.',
                           [{"role": "user", "content": request.statement}], verified=True)
        return MemberTurnResult("completed", True, member_context=json.loads(raw),
                                audit_ids=tuple(e["audit_id"] for e in self.gateway.audit_log))
