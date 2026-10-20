"""A small policy-enforcement gateway for all agent tools.

The graph and LLM can request an operation, but only this gateway decides whether
it may run.  Production deployments can replace the in-memory audit sink and
tool handlers with their service-backed equivalents without changing the graph.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from . import security
from .contracts import ToolCallContext, ToolDefinition, ToolResult
from .domains import register_domain_tools

logger = logging.getLogger(__name__)

# Security tools that report this gateway's own decisions are handed the gateway and the caller's context.
CONTEXT_TOOLS = frozenset({"authorize_tool_call", "enforce_member_scope", "apply_tool_allowlist", "apply_rate_limit"})
# A runaway model must not flood the tools. Emergency and identity tools are never rate-limited.
TOOL_CALLS_PER_MINUTE = int(os.environ.get("TOOL_CALLS_PER_MINUTE", "120"))
UNLIMITED_SCOPES = frozenset({"safety_escalation", "member_verify"})


class ToolGateway:
    """Register and invoke tools after tenant, purpose, scope, and member checks."""

    def __init__(self, tools: Iterable[ToolDefinition] = ()) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self.audit_log: list[dict[str, Any]] = []
        self.rate_limiter = security.RateLimiter()  # one gateway serves one call, so limits are per call

    @property
    def tool_names(self) -> tuple[str, ...]:
        """Return tool names so callers can build an explicit allowlist."""
        return tuple(sorted(self._tools))

    def register(self, tool: ToolDefinition) -> None:
        """Add one tool; duplicate names are configuration mistakes."""
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def check(self, name: str, context: ToolCallContext, arguments: dict[str, Any] | None = None) -> tuple[bool, str]:
        """Would this call be allowed? The allow-list, caller, scope and member checks, without running it."""
        tool = self._tools.get(name)
        if tool is None:
            return False, "tool is not allowlisted"
        if not context.actor_id or not context.tenant_id or not context.purpose:
            return False, "actor, tenant, and purpose are required"
        if tool.required_scopes - context.scopes:
            return False, "caller lacks required scope"
        requested_member = (arguments or {}).get("member_id")
        if requested_member and requested_member != context.member_id:
            return False, "member scope does not match"
        return True, ""

    def invoke(self, name: str, context: ToolCallContext, arguments: dict[str, Any]) -> ToolResult:
        """Authorize a tool call, execute an allowed handler, and write an audit record."""
        audit_id = uuid4().hex
        allowed, reason = self.check(name, context, arguments)
        if not allowed:
            return self._deny(name, context, reason, audit_id)
        tool = self._tools[name]
        if not (tool.required_scopes & UNLIMITED_SCOPES):
            if not self.rate_limiter.hit("tool_calls", TOOL_CALLS_PER_MINUTE, 60)["allowed"]:
                return self._deny(name, context, "tool-call rate limit reached", audit_id)

        handler_arguments = dict(arguments)
        if name in CONTEXT_TOOLS:
            handler_arguments.update(_gateway=self, _context=context)
        data = tool.handler(handler_arguments)
        result = ToolResult(True, name, data=data, audit_id=audit_id)
        self._audit(result, context)
        return result

    def _deny(self, name: str, context: ToolCallContext, reason: str, audit_id: str) -> ToolResult:
        result = ToolResult(False, name, reason=reason, audit_id=audit_id)
        self._audit(result, context)
        return result

    def _audit(self, result: ToolResult, context: ToolCallContext) -> None:
        """Store minimized audit evidence; arguments and member content are never logged here."""
        entry = {
            "audit_id": result.audit_id,
            "at": (context.requested_at or datetime.now(timezone.utc)).isoformat(),
            "tool": result.tool_name,
            "allowed": result.allowed,
            "reason": result.reason,
            "actor_id": context.actor_id,
            "tenant_id": context.tenant_id,
            "purpose": context.purpose,
            "member_id": context.member_id,
        }
        self.audit_log.append(entry)
        try:  # also keep it in the process-wide audit log, which can be written to a file
            security.audit_log().record("tool_call", **{k: v for k, v in entry.items() if k != "at"})
        except Exception:
            logger.exception("Could not write the audit log entry for %s", result.tool_name)


def build_default_gateway() -> ToolGateway:
    """Build the in-process reference gateway with every documented tool registered."""
    return ToolGateway(register_domain_tools())
