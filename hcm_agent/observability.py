"""Privacy-minimized OpenTelemetry traces for Clara's capability graph.

Spans deliberately exclude caller speech, tool arguments, member identifiers, and
retrieved document text. The local live dashboard consumes only names, durations,
success states, and safe source metadata.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import time
from typing import Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import SpanKind, Status, StatusCode

CALL_ID: ContextVar[str | None] = ContextVar("clara_call_id", default=None)
TURN_ID: ContextVar[int | None] = ContextVar("clara_turn_id", default=None)
MAX_SPANS_PER_CALL = 100


@dataclass(frozen=True)
class TraceEntry:
    name: str
    kind: str
    capability: str
    tool: str
    source: str
    duration_ms: int
    success: bool
    at: float
    turn: int | None


class TraceStore:
    """Thread-safe, bounded in-memory view of safe completed spans for the live UI."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: dict[str, list[TraceEntry]] = {}

    def add(self, call_id: str, entry: TraceEntry) -> None:
        with self._lock:
            entries = self._calls.setdefault(call_id, [])
            entries.append(entry)
            del entries[:-MAX_SPANS_PER_CALL]

    def summary(self, call_id: str) -> list[dict]:
        with self._lock:
            return [entry.__dict__.copy() for entry in self._calls.get(call_id, [])]

    def clear(self) -> None:
        with self._lock:
            self._calls.clear()


trace_store = TraceStore()


class LiveTraceExporter(SpanExporter):
    """Export only a redacted span summary to the local dashboard store."""

    def export(self, spans) -> SpanExportResult:
        for span in spans:
            attributes = span.attributes or {}
            call_id = attributes.get("app.call.id")
            if not call_id:
                continue
            duration_ms = max(0, int((span.end_time - span.start_time) / 1_000_000))
            trace_store.add(str(call_id), TraceEntry(
                name=span.name,
                kind=str(attributes.get("app.trace.kind", "operation")),
                capability=str(attributes.get("gen_ai.agent.name", "")),
                tool=str(attributes.get("gen_ai.tool.name", "")),
                source=str(attributes.get("app.source.label", "")),
                duration_ms=duration_ms,
                success=span.status.status_code is not StatusCode.ERROR,
                at=time(),
                turn=(int(attributes["app.conversation.turn"])
                      if attributes.get("app.conversation.turn") is not None else None),
            ))
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


def _configure_provider() -> None:
    provider = TracerProvider(resource=Resource.create({
        "service.name": "clara-care-management-agent",
        "service.version": "0.1.0",
        "deployment.environment.name": os.getenv("DEPLOYMENT_ENVIRONMENT", "development"),
    }))
    provider.add_span_processor(SimpleSpanProcessor(LiveTraceExporter()))
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip()
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        except ImportError:
            # Local tracing stays functional when a deployment omitted the optional OTLP package.
            pass
    trace.set_tracer_provider(provider)


_configure_provider()
tracer = trace.get_tracer("clara.langgraph", "0.1.0")


@contextmanager
def call_trace(call_id: str, *, turn: int | None = None) -> Iterator[None]:
    """Attach opaque call and turn correlation IDs to spans in this execution context."""
    token = CALL_ID.set(call_id)
    turn_token = TURN_ID.set(turn)
    try:
        yield
    finally:
        TURN_ID.reset(turn_token)
        CALL_ID.reset(token)


@contextmanager
def traced_operation(name: str, *, kind: str, capability: str = "", tool: str = "", source: str = "") -> Iterator[None]:
    """Create a standard OTel span with safe dashboard attributes."""
    attributes = {"app.trace.kind": kind}
    if CALL_ID.get():
        attributes["app.call.id"] = CALL_ID.get()
    if TURN_ID.get() is not None:
        attributes["app.conversation.turn"] = TURN_ID.get()
    if capability:
        attributes["gen_ai.agent.name"] = capability
    if tool:
        attributes["gen_ai.tool.name"] = tool
    if source:
        attributes["app.source.label"] = source
    with tracer.start_as_current_span(name, kind=SpanKind.INTERNAL, attributes=attributes) as span:
        try:
            yield
            span.set_attribute("app.operation.success", True)
        except Exception as error:
            span.set_attribute("error.type", type(error).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise
