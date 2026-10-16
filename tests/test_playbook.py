"""Offline tests for the scoped, LangChain-backed playbook tool boundary."""

from hcm_agent.tools import ToolCallContext, build_default_gateway, domains
from hcm_agent.tools.playbook import PLAYBOOK_ID, PLAYBOOK_STATUS
from test_langgraph import invoke_catalog_tool


def _context():
    return ToolCallContext("agent", "test", "care_management", "m1", frozenset({"care_outreach"}))


def test_playbook_tool_returns_source_grounded_draft_status(monkeypatch):
    monkeypatch.setattr(domains, "retrieve_playbook", lambda query, llm=None: [{
        "id": "diabetes-1", "title": "Support", "content": "General support.",
        "sources": [{"id": "CDC-DSMES", "url": "https://www.cdc.gov/"}],
    }])
    gateway = build_default_gateway()
    result = invoke_catalog_tool("search_diabetes_playbook", {"query": "I need support"},
                                 gateway=gateway, context=_context(), verified=True)

    assert result["allowed"] is True
    assert result["data"]["playbook_id"] == PLAYBOOK_ID
    assert result["data"]["playbook_status"] == PLAYBOOK_STATUS
    assert result["data"]["production_approved"] is False
    assert result["data"]["grounded"] is True
    assert result["data"]["results"][0]["sources"][0]["id"] == "CDC-DSMES"


def test_playbook_tool_passes_configured_llm_to_llm_retriever(monkeypatch):
    seen = {}

    def retrieve(query, *, llm=None, limit=3):
        seen.update(query=query, llm=llm)
        return []

    monkeypatch.setattr(domains, "retrieve_playbook", retrieve)
    model = object()
    gateway = build_default_gateway()
    invoke_catalog_tool("search_diabetes_playbook", {"query": "I feel overwhelmed"},
                        gateway=gateway, context=_context(), verified=True, retrieval_llm=model)

    assert seen == {"query": "I feel overwhelmed", "llm": model}


def test_unverified_member_cannot_retrieve_care_playbook(monkeypatch):
    def unexpected_retrieval(*args, **kwargs):
        raise AssertionError("retrieval must not run before verification")

    monkeypatch.setattr(domains, "retrieve_playbook", unexpected_retrieval)
    gateway = build_default_gateway()
    result = invoke_catalog_tool("search_diabetes_playbook", {"query": "diabetes support"},
                                 gateway=gateway, context=_context(), verified=False)
    assert result["allowed"] is False
