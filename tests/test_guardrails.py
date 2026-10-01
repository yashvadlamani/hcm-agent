import pytest

from hcm_agent.agent.guardrails import GuardrailViolation, VoiceAgentGuardrails

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
    "Can someone help me with my refills?",
    "Could you help me understand my insurance card?",
])
def test_ordinary_statements_are_not_emergencies(statement):
    is_emergency, _ = guardrails.check_patient_statement(statement)
    assert not is_emergency


def test_mental_health_statements_are_labeled():
    is_emergency, reason = guardrails.check_patient_statement("Sometimes I want to die")
    assert is_emergency and reason.startswith("Mental health")


@pytest.mark.parametrize("reply", [
    "I'll connect you with your care manager right away.",
    "Let me transfer you to a nurse.",
    "Someone will call you back this afternoon.",
    "Your care team will reach out to you tomorrow.",
    "I'll send you a text with the details.",
    "I'll make sure your doctor sees this.",
    "I promise this will be sorted out.",
])
def test_promises_are_flagged(reply):
    assert guardrails.check_agent_response(reply)[0] == GuardrailViolation.PROMISE


@pytest.mark.parametrize("reply", [
    "I'll note that for your care team so they can follow up.",
    "Please call your doctor's office or the number on your insurance card.",
    "I've noted that you'd like the feedback form.",
    "Is there anything else I can help you with today?",
])
def test_honest_replies_are_not_promises(reply):
    assert guardrails.check_agent_response(reply)[0] == GuardrailViolation.NONE
