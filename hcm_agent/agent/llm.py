"""LangChain model adapters; native LangGraph handles tool execution and review."""

import json
import logging
from typing import Optional, Protocol

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI

from ..config import Settings, llm_problems, require
from ..workflows.graph import run_agent

logger = logging.getLogger(__name__)


class LLM(Protocol):
    def complete(self, system_prompt: str, messages: list, json_mode: bool = False, *, tools=()) -> Optional[str]:
        """Return a reply after any model-selected tools have been executed and reviewed."""

    def call_and_review_tool(self, system_prompt: str, payload: dict, tool: dict, execute) -> bool:
        """Invoke and review one mandatory identity tool."""


class LangChainLLM:
    def __init__(self, model):
        self.model = model
        self.last_filter_categories: set[str] = set()

    def complete(self, system_prompt: str, messages: list, json_mode: bool = False, *, tools=()) -> Optional[str]:
        self.last_filter_categories = set()
        if json_mode:
            system_prompt += "\nReturn the requested JSON object, without Markdown."
        try:
            if tools:
                result = run_agent(self.model, list(tools), system_prompt, messages)
                response = result["messages"][-1]
            else:
                response = self.model.invoke([SystemMessage(system_prompt), *messages])
        except Exception as error:
            if "content_filter" not in str(error):
                raise
            self.last_filter_categories = flagged_categories(str(error))
            return None
        if response.response_metadata.get("finish_reason") == "content_filter":
            self.last_filter_categories = flagged_categories(str(response.response_metadata))
            return None
        return response.text

    def call_and_review_tool(self, system_prompt: str, payload: dict, tool: dict, execute) -> bool:
        definition = tool["function"]
        identity_tool = StructuredTool.from_function(
            func=lambda **arguments: execute(arguments),
            name=definition["name"], description=definition["description"],
            args_schema=definition["parameters"],
        )
        result = run_agent(self.model, [identity_tool], system_prompt,
                           [{"role": "user", "content": json.dumps(payload)}],
                           required_tool=identity_tool.name, max_rounds=1)
        review = json.loads(result["messages"][-1].text)
        return isinstance(review, dict) and review.get("verified") is True


class AzureOpenAILLM(LangChainLLM):
    def __init__(self, settings: Settings):
        # Azure's existing /openai/v1 endpoint uses LangChain's standard ChatOpenAI.
        options = {"reasoning_effort": settings.azure_openai_reasoning_effort} if (
            settings.azure_openai_reasoning_effort) else {}
        super().__init__(ChatOpenAI(
            model=settings.azure_openai_deployment, api_key=settings.azure_openai_api_key,
            base_url=settings.azure_openai_endpoint.rstrip("/") + "/",
            max_completion_tokens=2000, timeout=30, max_retries=1, **options,
        ))


class AnthropicLLM(LangChainLLM):
    def __init__(self, settings: Settings, api_key: Optional[str] = None):
        options = {"api_key": api_key} if api_key else {}
        super().__init__(ChatAnthropic(model=settings.anthropic_model, max_tokens=2000,
                                      timeout=30, max_retries=1, **options))


FILTER_CATEGORIES = ("self_harm", "violence", "hate", "sexual", "jailbreak")


def flagged_categories(details: str) -> set[str]:
    found = set()
    for category in FILTER_CATEGORIES:
        at = details.find(f"'{category}'") if f"'{category}'" in details else details.find(f'"{category}"')
        entry = details[at:details.find("}", at) + 1] if at >= 0 else ""
        if "'filtered': true" in entry.lower() or '"filtered": true' in entry.lower():
            found.add(category)
    return found


def create_llm(settings: Settings, api_key: Optional[str] = None) -> LLM:
    require(llm_problems(settings))
    return AzureOpenAILLM(settings) if settings.llm_provider == "azure_openai" else AnthropicLLM(settings, api_key)
