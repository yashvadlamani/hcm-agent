"""LangChain model adapters; native LangGraph handles tool execution and review."""

import json
import logging
from typing import Optional, Protocol

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langchain.tools import tool as langchain_tool
from langchain_openai import ChatOpenAI

from ..config import Settings, llm_problems, require
from ..tools.catalog import DOBAnswer, NameAnswer
from ..workflows.graph import run_agent, run_capability_agent

logger = logging.getLogger(__name__)


class LLM(Protocol):
    def complete(self, system_prompt: str, messages: list, json_mode: bool = False, *, tools=(),
                 tool_context=None, capability_graph: bool = False) -> Optional[str]:
        """Return a reply after any model-selected tools have been executed and reviewed."""

    def call_and_review_tool(self, system_prompt: str, payload: dict, tool: dict, execute) -> bool:
        """Invoke and review one mandatory identity tool."""


class LangChainLLM:
    # Extra request options that make the provider return one JSON object (when it has such a mode).
    json_options: dict = {}

    def __init__(self, model):
        self.model = model
        self.last_filter_categories: set[str] = set()

    def complete(self, system_prompt: str, messages: list, json_mode: bool = False, *, tools=(),
                 tool_context=None, capability_graph: bool = False) -> Optional[str]:
        self.last_filter_categories = set()
        options = self.json_options if json_mode else {}
        if json_mode:
            system_prompt += "\nReturn the requested JSON object, without Markdown."
        try:
            if tools or capability_graph:
                result = (run_capability_agent(self.model, system_prompt, messages, tool_context=tool_context,
                                               model_options=options)
                          if capability_graph else
                          run_agent(self.model, list(tools), system_prompt, messages, tool_context=tool_context,
                                    model_options=options))
                response = result["messages"][-1]
                policy_answer = result.get("tool_results", {}).get("lookup_policy", {}).get("data", {})
            else:
                response = self.model.invoke([SystemMessage(system_prompt), *messages], **options)
                policy_answer = {}
        except Exception as error:
            if "content_filter" not in str(error):
                raise
            self.last_filter_categories = flagged_categories(str(error))
            return None
        if response.response_metadata.get("finish_reason") == "content_filter":
            self.last_filter_categories = flagged_categories(str(response.response_metadata))
            return None
        return _preserve_exact_policy_answer(response.text, policy_answer)

    def call_and_review_tool(self, system_prompt: str, payload: dict, tool: dict, execute) -> bool:
        definition = tool["function"]
        schemas = {"verify_full_name": NameAnswer, "verify_dob": DOBAnswer}
        schema = schemas.get(definition["name"])
        if schema is None:
            raise ValueError("Only supported identity checks can be called through this adapter.")

        def execute_identity(**arguments):
            """Run a single required identity check for the current turn."""
            return execute(arguments)

        identity_tool = langchain_tool(definition["name"], description=definition["description"],
                                       args_schema=schema)(execute_identity)
        result = run_agent(self.model, [identity_tool], system_prompt,
                           [{"role": "user", "content": json.dumps(payload)}],
                           required_tool=identity_tool.name, max_rounds=1, model_options=self.json_options)
        review = json.loads(result["messages"][-1].text)
        return isinstance(review, dict) and review.get("verified") is True


def _preserve_exact_policy_answer(response_text: str, policy_result: dict) -> str:
    """Keep deterministic PDF table facts intact if the final model response altered them."""
    answer = policy_result.get("answer") if isinstance(policy_result, dict) else None
    if not isinstance(answer, str) or not answer.strip() or answer in response_text:
        return response_text
    try:
        parsed = json.loads(response_text)
    except (TypeError, json.JSONDecodeError):
        return response_text
    if not isinstance(parsed, dict) or not isinstance(parsed.get("reply"), str):
        return response_text
    page = policy_result.get("answer_page")
    parsed["reply"] = answer + (f" Source: page {page}." if page else "")
    return json.dumps(parsed)

class AzureOpenAILLM(LangChainLLM):
    # Without JSON mode the model sometimes writes its reply in front of the JSON object, which Clara
    # would read aloud, losing the emergency assessment, sentiment and conversation state. Sent as
    # extra_body so it also applies to requests that offer tools: LangChain's own response_format
    # option refuses those unless every tool is declared strict.
    json_options = {"extra_body": {"response_format": {"type": "json_object"}}}

    def __init__(self, settings: Settings):
        # Azure's existing /openai/v1 endpoint uses LangChain's standard ChatOpenAI.
        options = {"reasoning_effort": settings.azure_openai_reasoning_effort} if (
            settings.azure_openai_reasoning_effort) else {}
        super().__init__(ChatOpenAI(
            model=settings.azure_openai_deployment, api_key=settings.azure_openai_api_key,
            base_url=settings.azure_openai_endpoint.rstrip("/") + "/",
            max_completion_tokens=2000, timeout=15, max_retries=0, **options,
        ))


class AnthropicLLM(LangChainLLM):
    def __init__(self, settings: Settings, api_key: Optional[str] = None):
        options = {"api_key": api_key} if api_key else {}
        super().__init__(ChatAnthropic(model=settings.anthropic_model, max_tokens=2000,
                                      timeout=15, max_retries=0, **options))


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
