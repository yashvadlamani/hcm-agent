import pytest

from hcm_agent.guardrails import GuardrailViolation, VoiceAgentGuardrails

guardrails = VoiceAgentGuardrails()


@pytest.mark.parametrize("reply", [
    "I'm sorry to hear that, Yash. What do you have going on this week?",
    "You have been doing great with your checkups.",
    "That's a question for your doctor; I can't advise on insulin doses.",
    "Would you like me to help schedule an appointment with your provider?",
])
def test_safe_replies_pass(reply):
    assert guardrails.check_agent_response(reply)[0] == GuardrailViolation.NONE


@pytest.mark.parametrize("reply, expected", [
    ("Based on what you describe, you have diabetic neuropathy.", GuardrailViolation.MEDICAL_DIAGNOSIS),
    ("You may have an infection.", GuardrailViolation.MEDICAL_DIAGNOSIS),
    ("That sounds like a thyroid condition.", GuardrailViolation.MEDICAL_DIAGNOSIS),
    ("You should increase your insulin dose.", GuardrailViolation.PRESCRIPTION_CHANGE),
    ("Take less insulin until your sugars settle.", GuardrailViolation.PRESCRIPTION_CHANGE),
])
def test_unsafe_replies_are_flagged(reply, expected):
    assert guardrails.check_agent_response(reply)[0] == expected


@pytest.mark.parametrize("statement", [
    "I'm having chest pain right now",
    "I have difficulty breathing",
    "I've been having suicidal thoughts",
])
def test_emergency_statements_are_detected(statement):
    is_emergency, _ = guardrails.check_patient_statement(statement)
    assert is_emergency


@pytest.mark.parametrize("statement", [
    "I'm feeling a bit stressed.",
    "I'm having trouble getting my refills because of the cost.",
])
def test_ordinary_statements_are_not_emergencies(statement):
    is_emergency, _ = guardrails.check_patient_statement(statement)
    assert not is_emergency
