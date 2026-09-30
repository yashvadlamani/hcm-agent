"""Runtime settings, read from environment variables (and a local .env file).

Every setting the app uses is defined here, so there is one place to see what
needs configuring. See .env.example for descriptions.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

PROVIDERS = ("anthropic", "azure_openai")


class ConfigError(RuntimeError):
    """Raised when required settings are missing or invalid."""


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    anthropic_model: str
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_deployment: str
    azure_openai_reasoning_effort: str
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_phone_number: str
    phone_webhook_key: str
    live_view_password: str
    port: int
    clara_base_url: str
    allowed_call_numbers: tuple[str, ...]
    max_calls_per_hour: int


def load() -> Settings:
    env = os.environ.get
    return Settings(
        llm_provider=env("LLM_PROVIDER", "anthropic").strip().lower(),
        anthropic_model=env("ANTHROPIC_MODEL", "claude-opus-5"),
        azure_openai_endpoint=env("AZURE_OPENAI_ENDPOINT", ""),
        azure_openai_api_key=env("AZURE_OPENAI_API_KEY", ""),
        azure_openai_deployment=env("AZURE_OPENAI_DEPLOYMENT", ""),
        azure_openai_reasoning_effort=env("AZURE_OPENAI_REASONING_EFFORT", "minimal").strip(),
        twilio_account_sid=env("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=env("TWILIO_AUTH_TOKEN", ""),
        twilio_phone_number=env("TWILIO_PHONE_NUMBER", ""),
        phone_webhook_key=env("PHONE_WEBHOOK_KEY", ""),
        live_view_password=env("LIVE_VIEW_PASSWORD", ""),
        port=int(env("FLASK_PORT", "5000")),
        clara_base_url=env("CLARA_BASE_URL", "").rstrip("/"),
        allowed_call_numbers=tuple(n.strip() for n in env("ALLOWED_CALL_NUMBERS", "").split(",") if n.strip()),
        max_calls_per_hour=int(env("MAX_CALLS_PER_HOUR", "10")),
    )


def llm_problems(settings: Settings) -> list[str]:
    if settings.llm_provider not in PROVIDERS:
        return [f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)} (got '{settings.llm_provider}')"]
    if settings.llm_provider == "azure_openai":
        required = {
            "AZURE_OPENAI_ENDPOINT": settings.azure_openai_endpoint,
            "AZURE_OPENAI_API_KEY": settings.azure_openai_api_key,
            "AZURE_OPENAI_DEPLOYMENT": settings.azure_openai_deployment,
        }
        return [f"{name} is not set" for name, value in required.items() if not value]
    return []


def server_problems(settings: Settings) -> list[str]:
    problems = llm_problems(settings)
    if not settings.twilio_account_sid:
        problems.append("TWILIO_ACCOUNT_SID is not set")
    if len(settings.phone_webhook_key) < 20:
        problems.append("PHONE_WEBHOOK_KEY must be a random value of at least 20 characters")
    return problems


def call_problems(settings: Settings) -> list[str]:
    required = {
        "TWILIO_ACCOUNT_SID": settings.twilio_account_sid,
        "TWILIO_AUTH_TOKEN": settings.twilio_auth_token,
        "TWILIO_PHONE_NUMBER": settings.twilio_phone_number,
        "PHONE_WEBHOOK_KEY": settings.phone_webhook_key,
    }
    return [f"{name} is not set" for name, value in required.items() if not value]


def call_request_problems(settings: Settings) -> list[str]:
    """Settings the call-request Azure Function needs; it places calls without a person watching."""
    problems = call_problems(settings)
    if not settings.clara_base_url.startswith("https://"):
        problems.append("CLARA_BASE_URL must be the Clara server's https address")
    if not settings.allowed_call_numbers:
        problems.append("ALLOWED_CALL_NUMBERS must list the numbers that may be called (comma-separated)")
    return problems


def require(problems: list[str]) -> None:
    if problems:
        raise ConfigError("Configuration problems (check .env):\n  - " + "\n  - ".join(problems))
