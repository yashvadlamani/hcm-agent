"""Safety guardrails for HCM voice agent."""

import re
from enum import Enum
from typing import Tuple


class GuardrailViolation(Enum):
    """Types of guardrail violations."""
    MEDICAL_DIAGNOSIS = "medical_diagnosis"
    MEDICAL_ADVICE = "medical_advice"
    PRESCRIPTION_CHANGE = "prescription_change"
    EMERGENCY_SYMPTOM = "emergency_symptom"
    NONE = "none"


class VoiceAgentGuardrails:
    """Guardrails to prevent unsafe agent behavior."""

    # Medical diagnosis patterns
    DIAGNOSIS_PATTERNS = [
        r"you (have|suffer from|are diagnosed with)",
        r"(this is|that's|looks like|sounds like) (\w+ ){0,3}(disease|disorder|condition|syndrome)",
        r"you (are|seem to be) (diabetic|prediabetic|hypertensive|depressed)",
        r"based on your symptoms?, (you )?have",
    ]

    # Medical advice patterns
    ADVICE_PATTERNS = [
        r"(take|stop|increase|decrease) (your )?(\w+ ){0,2}(medication|insulin|pill|drug)",
        r"(you should|i recommend|try|consider) .*?(medication|treatment|therapy|exercise routine)",
        r"(eat|avoid|eliminate) .*?(food|drink|diet)",
        r"don't (take|use|eat)",
    ]

    # Prescription change patterns
    PRESCRIPTION_PATTERNS = [
        r"(change|switch|stop|start) .*?(medication|insulin|dose)",
        r"(increase|decrease|adjust) your .*?(dose|dosage)",
        r"(take|use) (more|less) .*?(insulin|medication)",
    ]

    # Emergency symptom keywords
    EMERGENCY_KEYWORDS = [
        "chest pain", "difficulty breathing", "shortness of breath",
        "severe headache", "sudden vision loss", "loss of consciousness",
        "severe bleeding", "unbearable pain", "suicidal", "suicide",
        "call 911", "go to emergency", "go to hospital immediately"
    ]

    def __init__(self):
        self.diagnosis_regex = [re.compile(p, re.IGNORECASE) for p in self.DIAGNOSIS_PATTERNS]
        self.advice_regex = [re.compile(p, re.IGNORECASE) for p in self.ADVICE_PATTERNS]
        self.prescription_regex = [re.compile(p, re.IGNORECASE) for p in self.PRESCRIPTION_PATTERNS]

    def check_agent_response(self, response: str) -> Tuple[GuardrailViolation, str]:
        """
        Check if agent response violates guardrails.
        Returns: (violation_type, violation_text)
        """
        # Check for emergency symptoms (patient expression, not violation)
        for keyword in self.EMERGENCY_KEYWORDS:
            if keyword.lower() in response.lower():
                return GuardrailViolation.EMERGENCY_SYMPTOM, f"Emergency keyword detected: {keyword}"

        # Check for medical diagnosis
        for pattern in self.diagnosis_regex:
            if pattern.search(response):
                return GuardrailViolation.MEDICAL_DIAGNOSIS, f"Diagnosis pattern detected: {response[:100]}"

        # Check for prescription changes
        for pattern in self.prescription_regex:
            if pattern.search(response):
                return GuardrailViolation.PRESCRIPTION_CHANGE, f"Prescription change pattern: {response[:100]}"

        # Check for medical advice (excluding appointment scheduling)
        if not ("schedule" in response.lower() or "appointment" in response.lower()):
            for pattern in self.advice_regex:
                if pattern.search(response):
                    return GuardrailViolation.MEDICAL_ADVICE, f"Medical advice pattern: {response[:100]}"

        return GuardrailViolation.NONE, ""

    def check_patient_statement(self, statement: str) -> Tuple[bool, str]:
        """
        Check if patient statement indicates emergency or distress.
        Returns: (is_emergency, description)
        """
        statement_lower = statement.lower()

        for keyword in self.EMERGENCY_KEYWORDS:
            if keyword in statement_lower:
                return True, f"Emergency detected: {keyword}"

        # Check for severe distress indicators
        distress_keywords = ["help me", "can't breathe", "dying", "severe pain"]
        for keyword in distress_keywords:
            if keyword in statement_lower:
                return True, f"Patient distress: {keyword}"

        return False, ""
