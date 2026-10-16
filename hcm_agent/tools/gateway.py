"""A small policy-enforcement gateway for all agent tools.

The graph and LLM can request an operation, but only this gateway decides whether
it may run.  Production deployments can replace the in-memory audit sink and
tool handlers with their service-backed equivalents without changing the graph.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from .contracts import ToolCallContext, ToolDefinition, ToolResult
from .domains import register_domain_tools


class ToolGateway:
    """Register and invoke tools after tenant, purpose, scope, and member checks."""

    def __init__(self, tools: Iterable[ToolDefinition] = ()) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self.audit_log: list[dict[str, Any]] = []

    @property
    def tool_names(self) -> tuple[str, ...]:
        """Return tool names so callers can build an explicit allowlist."""
        return tuple(sorted(self._tools))

    def register(self, tool: ToolDefinition) -> None:
        """Add one tool; duplicate names are configuration mistakes."""
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def invoke(self, name: str, context: ToolCallContext, arguments: dict[str, Any]) -> ToolResult:
        """Authorize a tool call, execute an allowed handler, and write an audit record."""
        audit_id = uuid4().hex
        tool = self._tools.get(name)
        if tool is None:
            return self._deny(name, context, "tool is not allowlisted", audit_id)
        if not context.actor_id or not context.tenant_id or not context.purpose:
            return self._deny(name, context, "actor, tenant, and purpose are required", audit_id)
        if tool.required_scopes - context.scopes:
            return self._deny(name, context, "caller lacks required scope", audit_id)
        requested_member = arguments.get("member_id")
        if requested_member and requested_member != context.member_id:
            return self._deny(name, context, "member scope does not match", audit_id)

        data = tool.handler(dict(arguments))
        result = ToolResult(True, name, data=data, audit_id=audit_id)
        self._audit(result, context)
        return result

    def _deny(self, name: str, context: ToolCallContext, reason: str, audit_id: str) -> ToolResult:
        result = ToolResult(False, name, reason=reason, audit_id=audit_id)
        self._audit(result, context)
        return result

    def _audit(self, result: ToolResult, context: ToolCallContext) -> None:
        """Store minimized audit evidence; arguments and member content are never logged here."""
        self.audit_log.append({
            "audit_id": result.audit_id,
            "at": (context.requested_at or datetime.now(timezone.utc)).isoformat(),
            "tool": result.tool_name,
            "allowed": result.allowed,
            "reason": result.reason,
            "actor_id": context.actor_id,
            "tenant_id": context.tenant_id,
            "purpose": context.purpose,
            "member_id": context.member_id,
        })


def build_default_gateway() -> ToolGateway:
    """Build the in-process reference gateway with every documented tool registered."""
    return ToolGateway(register_domain_tools())
