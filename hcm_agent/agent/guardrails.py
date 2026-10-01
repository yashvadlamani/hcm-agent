"""Safety guardrails for HCM voice agent."""

import re
from enum import Enum
from typing import Tuple


class GuardrailViolation(Enum):
    """Types of guardrail violations."""
    MEDICAL_DIAGNOSIS = "medical_diagnosis"
    MEDICAL_ADVICE = "medical_advice"
    PRESCRIPTION_CHANGE = "prescription_change"
    PROMISE = "promise"
    EMERGENCY_SYMPTOM = "emergency_symptom"
    NONE = "none"


class VoiceAgentGuardrails:
    """Guardrails to prevent unsafe agent behavior."""

    # Medical diagnosis patterns
    DIAGNOSIS_PATTERNS = [
        r"\byou (have|suffer from|are diagnosed with|might have|may have) (a |an )?(\w+ ){0,2}"
        r"(disease|disorder|condition|syndrome|diabetes|neuropathy|hypertension|depression|infection|retinopathy)\b",
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

    # Promises Clara can't keep: she can't connect, transfer, schedule, send or arrange anything,
    # or commit anyone else to act. "I'll note that for your care team" is fine and isn't matched.
    PROMISE_PATTERNS = [
        r"\b(i'll|i will|i'm going to|let me|we'll|we will)\s+(\w+\s+){0,3}?"
        r"(connect|transfer|put you through|schedule|book|arrange|send|text|email|call you|"
        r"reach out|contact|get you|make sure|have someone)\b",
        r"\b(someone|somebody|a nurse|a doctor|your doctor|a care manager|your care manager|"
        r"the care team|your care team|they)\s+will\s+(\w+\s+){0,2}?"
        r"(call|contact|reach out|follow up|get back|be in touch|text|email|visit)\b",
        r"\b(right away|right now|immediately|as soon as possible|within the hour|today)\b.{0,40}"
        r"\b(connect|transfer|call you|contact you|reach out|follow up)\b",
        r"\b(connect|transfer|call you|contact you|reach out|follow up)\b.{0,40}"
        r"\b(right away|right now|immediately|as soon as possible|within the hour)\b",
        r"\bi (promise|guarantee)\b",
    ]

    # Emergency keywords: an instant safety net that runs before the model's own clinical assessment.
    EMERGENCY_KEYWORDS = [
        "chest pain", "difficulty breathing", "shortness of breath",
        "severe headache", "sudden vision loss", "loss of consciousness",
        "severe bleeding", "unbearable pain",
        "call 911", "go to emergency", "go to hospital immediately"
    ]
    MENTAL_HEALTH_KEYWORDS = [
        "suicidal", "suicide", "kill myself", "end my life", "ending my life", "want to die", "hurt myself",
        "self harm", "self-harm", "don't see the point of going on", "don't see the point in going on",
        "no reason to live", "not worth living", "better off dead", "better off without me", "can't go on",
    ]

    def __init__(self):
        self.diagnosis_regex = [re.compile(p, re.IGNORECASE) for p in self.DIAGNOSIS_PATTERNS]
        self.advice_regex = [re.compile(p, re.IGNORECASE) for p in self.ADVICE_PATTERNS]
        self.prescription_regex = [re.compile(p, re.IGNORECASE) for p in self.PRESCRIPTION_PATTERNS]
        self.promise_regex = [re.compile(p, re.IGNORECASE) for p in self.PROMISE_PATTERNS]

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

        # Check for promises Clara can't keep
        for pattern in self.promise_regex:
            if pattern.search(response):
                return GuardrailViolation.PROMISE, f"Promise pattern: {response[:100]}"

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

        for keyword in self.MENTAL_HEALTH_KEYWORDS:
            if keyword in statement_lower:
                return True, f"Mental health crisis: {keyword}"

        for keyword in self.EMERGENCY_KEYWORDS:
            if keyword in statement_lower:
                return True, f"Emergency detected: {keyword}"

        # Severe distress indicators. ("help me" was removed: "can you help me with my refills" is an
        # ordinary request. The model's clinical assessment judges distress in context instead.)
        distress_keywords = ["can't breathe", "cannot breathe", "i'm dying", "severe pain"]
        for keyword in distress_keywords:
            if keyword in statement_lower:
                return True, f"Patient distress: {keyword}"

        return False, ""
