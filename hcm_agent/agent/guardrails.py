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

    # Advice and medication changes are judged one sentence at a time, and only when Clara is telling
    # the patient what to do: a command ("Take less insulin") or a recommendation ("You should...",
    # "Try..."). Talking or asking about the same things ("How has that affected when you take your
    # insulin?", "Skipping doses when the pharmacy is closed must be frustrating") is not advice.
    RECOMMENDING = (r"\b(you should|you could|you can|you need to|you must|you have to|you might want to|"
                    r"you may want to|you'd better|i recommend|i'd recommend|i suggest|i'd suggest|i would suggest|"
                    r"i advise|my advice is to|try to|try|consider|make sure to|make sure you|it's best to|"
                    r"it is best to|it's fine to|it's okay to|it's ok to|go ahead and|why don't you|how about|"
                    r"what if you|have you tried|have you considered)\s+(\w+\s+){0,3}?")
    COMMANDING = r"^\W*((please|just|maybe|so|then|and)\s+)*"
    MEDICINE = r"\b(medications?|medicines?|meds|insulin|doses?|dosage|pills?|tablets?|metformin|prescriptions?)\b"
    ADVICE_TOPIC = (r"\b(medications?|medicines?|meds|insulin|pills?|tablets?|drugs?|supplements?|vitamins?|"
                    r"treatments?|therapy|diet|foods?|carbs|sugar|meals?|exercise|workouts?)\b")
    CHANGE = (r"(change|switch|stop|start|increase|decrease|reduce|adjust|skip|split|halve|double|cut|stretch|"
              r"lower|raise|take (more|less|half|double|extra|fewer)|use (more|less))\b")
    CHANGING = (r"(chang(e|ing)|switch(ing)?|stop(ping)?|start(ing)?|increas(e|ing)|decreas(e|ing)|reduc(e|ing)|"
                r"adjust(ing)?|skip(ping)?|split(ting)?|halv(e|ing)|doubl(e|ing)|cut(ting)?|stretch(ing)?|"
                r"lower(ing)?|rais(e|ing)|tak(e|ing) (more|less|half|double|extra|fewer)|us(e|ing) (more|less))\b")
    ADVISE = r"((don't|do not|never)\s+)?(take|use|eat|drink|avoid|eliminate|add|follow)\b"
    ADVISING = r"((don't|do not|never|not)\s+)?(tak(e|ing)|us(e|ing)|eat(ing)?|drink(ing)?|avoid(ing)?|" \
               r"eliminat(e|ing)|add(ing)?|follow(ing)?)\b"
    PRESCRIPTION_PATTERNS = [COMMANDING + CHANGE + r".{0,40}?" + MEDICINE,
                             RECOMMENDING + CHANGING + r".{0,40}?" + MEDICINE]
    ADVICE_PATTERNS = [COMMANDING + ADVISE + r".{0,40}?" + ADVICE_TOPIC,
                       RECOMMENDING + ADVISING + r".{0,40}?" + ADVICE_TOPIC]
    # Declining to advise, or pointing back to what the doctor prescribed, is the safe answer.
    NOT_ADVICE = (r"\b(i can't|i cannot|i can not|i'm not able to|i am not able to|i'm unable to|i won't|"
                  r"not something i can|as prescribed|as directed|as your doctor)\b")

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
        self.not_advice_regex = re.compile(self.NOT_ADVICE, re.IGNORECASE)

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

        # Check each sentence for medication changes, then for other medical advice
        sentences = [s for s in re.split(r"(?<=[.!?;])\s+", response) if not self.not_advice_regex.search(s)]
        for sentence in sentences:
            if any(pattern.search(sentence) for pattern in self.prescription_regex):
                return GuardrailViolation.PRESCRIPTION_CHANGE, f"Prescription change pattern: {response[:100]}"
        for sentence in sentences:
            if any(pattern.search(sentence) for pattern in self.advice_regex):
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
