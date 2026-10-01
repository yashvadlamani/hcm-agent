from types import SimpleNamespace

import pytest

from hcm_agent.agent import llm as llm_module
from hcm_agent.agent.conversation import REFUSAL_REPLY, HCMVoiceAgent
from hcm_agent.config import ConfigError


class FakeOpenAI:
    """Stands in for the openai.OpenAI client pointed at Azure."""

    reply = "I'm sorry you're dealing with that. What's been hardest this week?"
    finish_reason = "stop"

    def __init__(self, api_key, base_url):
        self.api_key, self.base_url = api_key, base_url
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **request):
        self.requests.append(request)
        message = SimpleNamespace(content=FakeOpenAI.reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=FakeOpenAI.finish_reason)])


class FakeAnthropic:
    def __init__(self, api_key=None):
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **request):
        return SimpleNamespace(stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text="Hello from Claude.")])


@pytest.fixture
def azure_env(monkeypatch):
    monkeypatch.setattr(llm_module, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("LLM_PROVIDER", "azure_openai")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/openai/v1")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "clara-chat")
    monkeypatch.delenv("AZURE_OPENAI_REASONING_EFFORT", raising=False)


def new_agent():
    agent = HCMVoiceAgent()
    agent.initialize_call({"name": "Yash", "risk_drivers": ["HbA1c above 7.5%"]})
    return agent


def test_azure_openai_request_shape(azure_env):
    agent = new_agent()
    reply = agent.generate_response("I've been stressed about my refills.")

    assert reply == FakeOpenAI.reply
    assert agent.llm.client.base_url == "https://example.openai.azure.com/openai/v1/"
    request = agent.llm.client.requests[0]
    assert request["model"] == "clara-chat"
    assert request["reasoning_effort"] == "minimal"
    assert request["messages"][0]["role"] == "system"
    assert request["messages"][-1] == {"role": "user", "content": "I've been stressed about my refills."}


def test_azure_reasoning_effort_can_be_disabled(azure_env, monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_REASONING_EFFORT", "")
    agent = new_agent()
    agent.generate_response("Hello")
    assert "reasoning_effort" not in agent.llm.client.requests[0]


def test_azure_content_filter_gives_safe_reply(azure_env, monkeypatch):
    monkeypatch.setattr(FakeOpenAI, "finish_reason", "content_filter")
    assert new_agent().generate_response("Hello") == REFUSAL_REPLY


def test_guardrails_still_apply_to_azure_replies(azure_env, monkeypatch):
    monkeypatch.setattr(FakeOpenAI, "reply", "You should increase your insulin dose.")
    agent = new_agent()
    reply = agent.generate_response("My sugars are high.")
    assert "insulin dose" not in reply.lower()
    assert agent.last_blocked_reply["rule"] == "prescription_change"


def test_anthropic_is_the_default(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setattr(llm_module, "Anthropic", FakeAnthropic)
    assert new_agent().generate_response("Hi Clara") == "Hello from Claude."


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "something-else")
    with pytest.raises(ConfigError):
        HCMVoiceAgent()
