import dataclasses

import pytest

from hcm_agent import config
from hcm_agent.agent.conversation import SAFE_FALLBACKS

VALID = config.Settings(
    llm_provider="anthropic", anthropic_model="claude-opus-5",
    azure_openai_endpoint="", azure_openai_api_key="", azure_openai_deployment="",
    azure_openai_reasoning_effort="minimal",
    twilio_account_sid="ACtest", twilio_auth_token="token", twilio_phone_number="+15550100",
    phone_webhook_key="k" * 24, live_view_password="", port=5000,
)


def test_valid_settings_have_no_problems():
    assert config.server_problems(VALID) == []
    assert config.call_problems(VALID) == []


def test_unknown_provider_is_reported():
    problems = config.llm_problems(dataclasses.replace(VALID, llm_provider="gemini"))
    assert problems and "LLM_PROVIDER" in problems[0]


def test_azure_provider_needs_its_settings():
    problems = config.llm_problems(dataclasses.replace(VALID, llm_provider="azure_openai"))
    assert problems == [
        "AZURE_OPENAI_ENDPOINT is not set",
        "AZURE_OPENAI_API_KEY is not set",
        "AZURE_OPENAI_DEPLOYMENT is not set",
    ]


def test_short_webhook_key_is_rejected():
    problems = config.server_problems(dataclasses.replace(VALID, phone_webhook_key="short"))
    assert any("PHONE_WEBHOOK_KEY" in p for p in problems)


def test_require_raises_with_every_problem_listed():
    with pytest.raises(config.ConfigError, match="A is bad(.|\n)*B is bad"):
        config.require(["A is bad", "B is bad"])


@pytest.mark.parametrize("fallback", SAFE_FALLBACKS.values())
def test_safe_fallbacks_promise_nothing_clara_cannot_do(fallback):
    for promise in ("schedule", "connect you", "arrange", "transfer"):
        assert promise not in fallback.lower()
