"""Offline checks for LangChain model configuration and conversation behavior."""

import pytest
from langchain_core.messages import AIMessage

from hcm_agent.agent import llm as llm_module
from hcm_agent.agent.conversation import REFUSAL_REPLY, HCMVoiceAgent
from hcm_agent.config import ConfigError


class FakeChatModel:
    reply = "I'm sorry you're dealing with that. What's been hardest this week?"
    finish_reason = "stop"

    def __init__(self, **options):
        self.options, self.requests = options, []

    def bind_tools(self, tools, **options):
        return self

    def invoke(self, messages, **options):
        self.requests.append(messages)
        self.request_options = options
        return AIMessage(content=self.reply, response_metadata={"finish_reason": self.finish_reason})


@pytest.fixture
def azure_env(monkeypatch):
    monkeypatch.setattr(llm_module, "ChatOpenAI", FakeChatModel)
    monkeypatch.setenv("LLM_PROVIDER", "azure_openai")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/openai/v1")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "clara-chat")
    monkeypatch.delenv("AZURE_OPENAI_REASONING_EFFORT", raising=False)


def new_agent():
    agent = HCMVoiceAgent()
    agent.initialize_call({"name": "Yash", "risk_drivers": ["HbA1c above 7.5%"]})
    agent.phase = "conversation"
    return agent


def test_azure_openai_request_shape(azure_env):
    agent = new_agent()
    assert agent.generate_response("I've been stressed about my refills.") == FakeChatModel.reply
    options = agent.llm.model.options
    assert options["model"] == "clara-chat"
    assert options["base_url"] == "https://example.openai.azure.com/openai/v1/"
    assert options["reasoning_effort"] == "minimal"
    # JSON mode keeps the structured turn (reply, emergency, sentiment, state) from being read aloud.
    assert agent.llm.model.request_options == {"extra_body": {"response_format": {"type": "json_object"}}}


def test_azure_reasoning_effort_can_be_disabled(azure_env, monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", "")
    assert "reasoning_effort" not in new_agent().llm.model.options


def test_azure_content_filter_gives_safe_reply(azure_env, monkeypatch):
    monkeypatch.setattr(FakeChatModel, "finish_reason", "content_filter")
    assert new_agent().generate_response("Hello") == REFUSAL_REPLY


def test_guardrails_still_apply_to_azure_replies(azure_env, monkeypatch):
    monkeypatch.setattr(FakeChatModel, "reply", "You should increase your insulin dose.")
    agent = new_agent()
    assert "insulin dose" not in agent.generate_response("My sugars are high.").lower()
    assert agent.last_blocked_reply["rule"] == "prescription_change"


def test_anthropic_is_the_default(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setattr(llm_module, "ChatAnthropic", FakeChatModel)
    assert new_agent().generate_response("Hi Clara") == FakeChatModel.reply


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "something-else")
    with pytest.raises(ConfigError):
        HCMVoiceAgent()
