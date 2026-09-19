"""HCM Voice Outreach Agent."""

from .agent import HCMVoiceAgent
from .guardrails import VoiceAgentGuardrails, GuardrailViolation
from .mock_voice import MockVoiceInterface, run_interactive_call
from .voice_service import (
    TwilioVoiceService,
    DeepgramASRService,
    ElevenLabsTTSService,
    VoiceCallManager
)

__version__ = "0.1.0"
__all__ = [
    "HCMVoiceAgent",
    "VoiceAgentGuardrails",
    "GuardrailViolation",
    "MockVoiceInterface",
    "run_interactive_call",
    "TwilioVoiceService",
    "DeepgramASRService",
    "ElevenLabsTTSService",
    "VoiceCallManager",
]
