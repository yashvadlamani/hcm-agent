"""Core HCM Voice Agent implementation."""

import json
import logging
import os
from typing import Optional, Tuple

import openai
from anthropic import Anthropic
from openai import OpenAI

from .guardrails import VoiceAgentGuardrails, GuardrailViolation
from .prompts import get_system_prompt, get_emergency_escalation_prompt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REFUSAL_REPLY = ("I'm not able to help with that on this call, but your care manager can. "
                 "Is there anything else I can help with today?")


class HCMVoiceAgent:
    """Main voice outreach agent with guardrails.

    LLM_PROVIDER picks the model backend: "anthropic" (Claude, default) or
    "azure_openai" (an Azure AI Foundry / Azure OpenAI deployment).
    """

    def __init__(self, api_key: str = None):
        self.provider = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
        if self.provider == "azure_openai":
            # Azure's v1 endpoint (https://<resource>.openai.azure.com/openai/v1) takes the standard client.
            self.client = OpenAI(api_key=os.environ["AZURE_OPENAI_API_KEY"],
                                 base_url=os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/") + "/")
        elif self.provider == "anthropic":
            self.client = Anthropic(api_key=api_key) if api_key else Anthropic()
        else:
            raise ValueError(f"Unknown LLM_PROVIDER '{self.provider}' (use 'anthropic' or 'azure_openai')")
        self.guardrails = VoiceAgentGuardrails()
        self.conversation_history = []
        self.patient_context = None
        self.is_emergency = False
        self.escalation_reason = None
        self.last_blocked_reply = None

    def initialize_call(self, patient_context: dict = None):
        """Initialize a call with patient context."""
        self.patient_context = patient_context or {}
        self.conversation_history = []
        self.is_emergency = False
        self.escalation_reason = None
        logger.info(f"Call initialized for patient: {self.patient_context.get('name', 'Unknown')}")

    def process_patient_input(self, patient_message: str) -> Tuple[bool, str]:
        """
        Check if patient message indicates emergency.
        Returns: (is_emergency, reason)
        """
        is_emergency, reason = self.guardrails.check_patient_statement(patient_message)
        if is_emergency:
            self.is_emergency = True
            self.escalation_reason = reason
            logger.warning(f"EMERGENCY DETECTED: {reason}")
        return is_emergency, reason

    def generate_response(self, patient_message: str) -> str:
        """
        Generate agent response to patient message with guardrails.

        Returns the agent response text.
        """
        self.last_blocked_reply = None

        # Check for emergency
        is_emergency, reason = self.process_patient_input(patient_message)

        # Build system prompt
        if is_emergency:
            system_prompt = get_emergency_escalation_prompt()
        else:
            system_prompt = get_system_prompt(self.patient_context)

        # Add patient message to history
        self.conversation_history.append({
            "role": "user",
            "content": patient_message
        })

        try:
            model_reply = self._call_model(system_prompt)
            if model_reply is None:
                agent_response = REFUSAL_REPLY
            else:
                agent_response = model_reply or "Sorry, could you say that again?"

            # Check for guardrail violations in agent response
            violation, violation_detail = self.guardrails.check_agent_response(agent_response)

            if violation != GuardrailViolation.NONE:
                logger.warning(f"GUARDRAIL VIOLATION: {violation.value} - {violation_detail}")

                # If it's a medical advice/diagnosis violation, regenerate
                if violation in [GuardrailViolation.MEDICAL_ADVICE, GuardrailViolation.MEDICAL_DIAGNOSIS, GuardrailViolation.PRESCRIPTION_CHANGE]:
                    logger.info("Regenerating response due to guardrail violation...")
                    self.last_blocked_reply = {"rule": violation.value, "text": agent_response}
                    agent_response = self._safe_fallback_response(patient_message, violation)

            # Add agent response to history
            self.conversation_history.append({
                "role": "assistant",
                "content": agent_response
            })

            return agent_response

        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "I'm having trouble connecting right now. Please try again in a moment."

    def _call_model(self, system_prompt: str) -> Optional[str]:
        """Return the model's reply text, or None if the provider refused or filtered it."""
        if self.provider == "azure_openai":
            return self._call_azure_openai(system_prompt)

        # Low effort keeps each turn fast enough for a live phone call.
        response = self.client.beta.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-opus-5"),
            max_tokens=4096,
            system=system_prompt,
            messages=self.conversation_history,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            return None
        return next((block.text for block in response.content if block.type == "text"), "").strip()

    def _call_azure_openai(self, system_prompt: str) -> Optional[str]:
        request = {
            "model": os.environ["AZURE_OPENAI_DEPLOYMENT"],
            "messages": [{"role": "system", "content": system_prompt}, *self.conversation_history],
            "max_completion_tokens": 2000,
        }
        # Reasoning models (gpt-5 family) are slow at default effort; "minimal" keeps phone turns quick.
        # Set AZURE_OPENAI_REASONING_EFFORT to empty for non-reasoning models such as gpt-4o.
        effort = os.getenv("AZURE_OPENAI_REASONING_EFFORT", "minimal").strip()
        if effort:
            request["reasoning_effort"] = effort
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

    def _safe_fallback_response(self, patient_message: str, violation: GuardrailViolation) -> str:
        """Generate a safe fallback response for guardrail violations."""
        if violation == GuardrailViolation.MEDICAL_DIAGNOSIS:
            return "I'm not able to diagnose conditions. That's something to discuss with your doctor. What I can help with is encouraging healthy habits and connecting you with your care team."
        elif violation == GuardrailViolation.MEDICAL_ADVICE:
            return "I can't provide medical advice, but your doctor or care manager would be happy to answer those questions. Is there something else I can help with?"
        elif violation == GuardrailViolation.PRESCRIPTION_CHANGE:
            return "Any changes to your medications need to be discussed with your doctor. I'd be happy to help schedule an appointment if needed."
        else:
            return "I want to make sure you get the right help for that. Let me connect you with your care manager."

    def end_call(self) -> dict:
        """End the call and return a summary."""
        summary = {
            "patient": self.patient_context.get("name", "Unknown"),
            "call_duration_turns": len(self.conversation_history),
            "emergency_detected": self.is_emergency,
            "escalation_reason": self.escalation_reason,
            "requires_care_manager_followup": self.is_emergency or self.escalation_reason is not None,
            "conversation": self.conversation_history
        }

        logger.info(f"Call ended. Summary: {json.dumps({k: v for k, v in summary.items() if k != 'conversation'}, indent=2)}")

        return summary

    def get_conversation_transcript(self) -> str:
        """Get formatted conversation transcript."""
        transcript = ""
        for msg in self.conversation_history:
            role = "Patient" if msg["role"] == "user" else "Agent"
            transcript += f"\n{role}: {msg['content']}\n"
        return transcript
