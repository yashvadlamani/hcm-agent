"""Shared contracts for tools and their policy decisions.

Tools return data, never prose intended for a member.  The conversation layer is
responsible for turning approved tool results into a safe member-facing response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    """A named operation with the minimum scopes needed to invoke it."""

    name: str
    handler: ToolHandler
    required_scopes: frozenset[str] = frozenset()
    description: str = ""


@dataclass(frozen=True)
class ToolCallContext:
    """Identity and purpose evaluated by the gateway for every tool invocation."""

    actor_id: str
    tenant_id: str
    purpose: str
    member_id: str | None = None
    scopes: frozenset[str] = frozenset()
    requested_at: datetime | None = None


@dataclass(frozen=True)
class ToolResult:
    """The gateway's auditable result for a single tool call."""

    allowed: bool
    tool_name: str
    data: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    audit_id: str = ""
