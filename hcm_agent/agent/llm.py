"""Model backends that turn a system prompt and conversation into Clara's next reply.

LLM_PROVIDER picks the backend: "anthropic" (Claude, default) or "azure_openai"
(a model deployed in Azure AI Foundry / Azure OpenAI).
"""

import logging
from typing import Optional, Protocol

import openai
from anthropic import Anthropic
from openai import OpenAI

from ..config import Settings, llm_problems, require

logger = logging.getLogger(__name__)

Messages = list[dict[str, str]]


class LLM(Protocol):
    def complete(self, system_prompt: str, messages: Messages) -> Optional[str]:
        """Return the reply text, or None if the provider refused or filtered it."""


class AnthropicLLM:
    def __init__(self, settings: Settings, api_key: Optional[str] = None):
        self.model = settings.anthropic_model
        self.client = Anthropic(api_key=api_key) if api_key else Anthropic()

    def complete(self, system_prompt: str, messages: Messages) -> Optional[str]:
        # Low effort keeps each turn fast enough for a live phone call.
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            return None
        return next((block.text for block in response.content if block.type == "text"), "").strip()


class AzureOpenAILLM:
    def __init__(self, settings: Settings):
        self.deployment = settings.azure_openai_deployment
        self.reasoning_effort = settings.azure_openai_reasoning_effort
        # Azure's v1 endpoint (https://<resource>.openai.azure.com/openai/v1) takes the standard client.
        self.client = OpenAI(api_key=settings.azure_openai_api_key,
                             base_url=settings.azure_openai_endpoint.rstrip("/") + "/")

    def complete(self, system_prompt: str, messages: Messages) -> Optional[str]:
        request = {
            "model": self.deployment,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "max_completion_tokens": 2000,
        }
        # Reasoning models (gpt-5 family) are slow at default effort; "minimal" keeps phone turns quick.
        # AZURE_OPENAI_REASONING_EFFORT is empty for non-reasoning models such as gpt-4o.
        if self.reasoning_effort:
            request["reasoning_effort"] = self.reasoning_effort
        try:
            response = self.client.chat.completions.create(**request)
        except openai.BadRequestError as e:
            if "content_filter" in str(e):
                logger.warning("Azure content filter blocked the request")
                return None
            raise
        choice = response.choices[0]
        if choice.finish_reason == "content_filter":
            logger.warning("Azure content filter blocked the reply")
            return None
        return (choice.message.content or "").strip()


def create_llm(settings: Settings, api_key: Optional[str] = None) -> LLM:
    require(llm_problems(settings))
    if settings.llm_provider == "azure_openai":
        return AzureOpenAILLM(settings)
    return AnthropicLLM(settings, api_key)
