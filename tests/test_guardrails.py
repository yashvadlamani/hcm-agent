import pytest

from hcm_agent.agent.guardrails import GuardrailViolation, VoiceAgentGuardrails

guardrails = VoiceAgentGuardrails()


@pytest.mark.parametrize("reply", [
    "I'm sorry to hear that, Yash. What do you have going on this week?",
    "You have been doing great with your checkups.",
    "That's a question for your doctor; I can't advise on insulin doses.",
    "Would you like me to help schedule an appointment with your provider?",
    "That dizzy spell at work sounds frightening. Were you able to eat or drink something afterwards?",
    # Talking or asking about medication, food and routines is not advice.
    "Ninety dollars is a big jump. How has that affected when and how you take your insulin?",
    "Skipping your meds when the pharmacy is closed must be frustrating.",
    "Working nights makes it hard to take your medication on time. What does a normal day look like?",
    "How long have you been stretching your insulin?",
    "What do you usually eat on the days you skip a meal at work?",
    "Has anything changed with your medication since the hospital stay?",
    "You can talk to your pharmacist about your medication. I'll note the cost for your care team.",
    # Declining to advise is the safe answer.
    "I can't tell you to change your insulin dose, but I'm glad you told me. What made this month harder?",
    "Please don't change any medication without talking to your doctor or pharmacist first.",
    "It's important to keep taking your medication as prescribed.",
])
def test_safe_replies_pass(reply):
    assert guardrails.check_agent_response(reply)[0] == GuardrailViolation.NONE


@pytest.mark.parametrize("reply, expected", [
    ("Based on what you describe, you have diabetic neuropathy.", GuardrailViolation.MEDICAL_DIAGNOSIS),
    ("You may have an infection.", GuardrailViolation.MEDICAL_DIAGNOSIS),
    ("That sounds like a thyroid condition.", GuardrailViolation.MEDICAL_DIAGNOSIS),
    ("You should increase your insulin dose.", GuardrailViolation.PRESCRIPTION_CHANGE),
    ("Take less insulin until your sugars settle.", GuardrailViolation.PRESCRIPTION_CHANGE),
    ("That's a lot of money. You could try taking half your dose for now.", GuardrailViolation.PRESCRIPTION_CHANGE),
    ("Have you considered skipping the evening dose?", GuardrailViolation.PRESCRIPTION_CHANGE),
    ("It's fine to stretch your insulin a little.", GuardrailViolation.PRESCRIPTION_CHANGE),
    ("Just stop the metformin if it upsets your stomach.", GuardrailViolation.PRESCRIPTION_CHANGE),
    ("I recommend taking a cinnamon supplement every morning.", GuardrailViolation.MEDICAL_ADVICE),
    ("You should avoid carbs after six.", GuardrailViolation.MEDICAL_ADVICE),
    ("Don't take your insulin on an empty stomach.", GuardrailViolation.MEDICAL_ADVICE),
    ("Try eating less sugar and see how you feel.", GuardrailViolation.MEDICAL_ADVICE),
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
