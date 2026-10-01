"""HCMVoiceAgent: runs one patient conversation and applies the safety guardrails."""

import json
import logging
from typing import Optional, Tuple

from .. import config
from .guardrails import GuardrailViolation, VoiceAgentGuardrails
from .llm import LLM, create_llm
from .prompts import get_emergency_escalation_prompt, get_system_prompt

logger = logging.getLogger(__name__)

REFUSAL_REPLY = ("I'm not able to help with that on this call, but your care team can. "
                 "Is there anything else on your mind today?")
ERROR_REPLY = "I'm having trouble connecting right now. Please try again in a moment."
REPLACED_VIOLATIONS = (GuardrailViolation.MEDICAL_ADVICE, GuardrailViolation.MEDICAL_DIAGNOSIS,
                       GuardrailViolation.PRESCRIPTION_CHANGE)

# Clara can't schedule, transfer or arrange callbacks, so these only promise a note for the care team.
SAFE_FALLBACKS = {
    GuardrailViolation.MEDICAL_DIAGNOSIS:
        "I'm not able to say what that means, but it's important to tell your doctor. "
        "I'll note it for your care team.",
    GuardrailViolation.MEDICAL_ADVICE:
        "I can't give medical advice, but your doctor or pharmacist can help with that question. "
        "I'll note it for your care team.",
    GuardrailViolation.PRESCRIPTION_CHANGE:
        "Please don't change any medication without talking to your doctor or pharmacist first. "
        "I'll note your question for your care team.",
}


class HCMVoiceAgent:
    """One patient conversation: emergency checks, model replies and guardrail enforcement."""

    def __init__(self, api_key: Optional[str] = None, settings: Optional[config.Settings] = None,
                 llm: Optional[LLM] = None):
        settings = settings or config.load()
        self.provider = settings.llm_provider
        self.llm = llm or create_llm(settings, api_key)
        self.guardrails = VoiceAgentGuardrails()
        self.conversation_history: list[dict[str, str]] = []
        self.patient_context: dict = {}
        self.is_emergency = False
        self.escalation_reason: Optional[str] = None
        self.last_blocked_reply: Optional[dict] = None

    def initialize_call(self, patient_context: Optional[dict] = None) -> None:
        self.patient_context = patient_context or {}
        self.conversation_history = []
        self.is_emergency = False
        self.escalation_reason = None
        logger.info("Call initialized for patient: %s", self.patient_context.get("name", "Unknown"))

    def process_patient_input(self, patient_message: str) -> Tuple[bool, str]:
        """Check whether the patient's words indicate an emergency. Returns (is_emergency, reason)."""
        is_emergency, reason = self.guardrails.check_patient_statement(patient_message)
        if is_emergency:
            self.is_emergency = True
            self.escalation_reason = reason
            logger.warning("EMERGENCY DETECTED: %s", reason)
        return is_emergency, reason

    def generate_response(self, patient_message: str) -> str:
        """Reply to the patient, replacing any reply that breaks a guardrail with a safe fallback."""
        self.last_blocked_reply = None
        is_emergency, _ = self.process_patient_input(patient_message)
        system_prompt = (get_emergency_escalation_prompt() if is_emergency
                         else get_system_prompt(self.patient_context))
        self.conversation_history.append({"role": "user", "content": patient_message})

        try:
            model_reply = self.llm.complete(system_prompt, self.conversation_history)
        except Exception as e:
            logger.error("Error generating response: %s", e)
            return ERROR_REPLY

        if model_reply is None:
            agent_response = REFUSAL_REPLY
        else:
            agent_response = model_reply or "Sorry, could you say that again?"

        violation, violation_detail = self.guardrails.check_agent_response(agent_response)
        if violation != GuardrailViolation.NONE:
            logger.warning("GUARDRAIL VIOLATION: %s - %s", violation.value, violation_detail)
            if violation in REPLACED_VIOLATIONS:
                self.last_blocked_reply = {"rule": violation.value, "text": agent_response}
                agent_response = SAFE_FALLBACKS[violation]

        self.conversation_history.append({"role": "assistant", "content": agent_response})
        return agent_response

    def end_call(self) -> dict:
        summary = {
            "patient": self.patient_context.get("name", "Unknown"),
            "call_duration_turns": len(self.conversation_history),
            "emergency_detected": self.is_emergency,
            "escalation_reason": self.escalation_reason,
            "requires_care_manager_followup": self.is_emergency or self.escalation_reason is not None,
            "conversation": self.conversation_history,
        }
        logger.info("Call ended. Summary: %s",
                    json.dumps({k: v for k, v in summary.items() if k != "conversation"}, indent=2))
        return summary

    def get_conversation_transcript(self) -> str:
        transcript = ""
        for msg in self.conversation_history:
            role = "Patient" if msg["role"] == "user" else "Agent"
            transcript += f"\n{role}: {msg['content']}\n"
        return transcript
