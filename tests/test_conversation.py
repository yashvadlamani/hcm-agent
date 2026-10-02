"""Tests for one conversation's flow: emergencies, promises, sentiment and the closing sequence."""

import json

import pytest

from hcm_agent.agent.conversation import (
    EMERGENCY_REPLIES,
    FEEDBACK_QUESTION,
    HCMVoiceAgent,
    parse_model_output,
)
from hcm_agent.agent.prompts import get_system_prompt
from hcm_agent.call_reasons import CALL_REASONS, call_reason
from test_config import VALID


def turn_json(reply="Thanks for telling me. What's been hardest lately?", sentiment=0.5, state="ongoing",
              emergency=None):
    """The JSON object the model returns each turn (see prompts.py, RESPONSE FORMAT)."""
    flag = {"detected": False, "type": "none", "reason": ""}
    if emergency:
        flag = {"detected": True, "type": emergency[0], "reason": emergency[1]}
    return json.dumps({"reply": reply, "emergency": flag, "sentiment": sentiment, "conversation_state": state})


class ScriptedLLM:
    """Stands in for the model: returns queued responses (the last one repeats) and records requests."""

    def __init__(self, *responses):
        self.responses = list(responses) or [turn_json()]
        self.requests = []

    def complete(self, system_prompt, messages, json_mode=False):
        self.requests.append({"system": system_prompt, "messages": list(messages), "json_mode": json_mode})
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def new_agent(*responses, name="Maria", verified=True):
    """An agent mid-call. verified=True starts past the identity check, as most tests are about the check-in."""
    llm = ScriptedLLM(*responses)
    agent = HCMVoiceAgent(settings=VALID, llm=llm)
    agent.initialize_call({"name": name, "risk_drivers": ["HbA1c above 7.5%"]})
    agent.start_call()
    if verified:
        agent.phase = "conversation"
    return agent, llm


# ---- Replies and the model request ----

def test_reply_comes_from_the_structured_model_output():
    agent, llm = new_agent(turn_json("I'm sorry, that sounds stressful. What's been hardest?"))
    turn = agent.take_turn("I've been stressed about my insulin costs.")
    assert turn.reply == "I'm sorry, that sounds stressful. What's been hardest?"
    assert turn.action == "listen" and turn.used_model
    assert llm.requests[0]["json_mode"] is True
    assert "RESPONSE FORMAT" in llm.requests[0]["system"]
    assert llm.requests[0]["messages"][-1] == {"role": "user", "content": "I've been stressed about my insulin costs."}


def test_plain_text_from_the_model_is_still_used_as_the_reply():
    agent, _ = new_agent("Sorry to hear that. How have you been sleeping?")
    turn = agent.take_turn("Not great.")
    assert turn.reply == "Sorry to hear that. How have you been sleeping?"
    assert turn.sentiment == 0.5 and turn.action == "listen"


def test_history_keeps_only_the_spoken_words():
    agent, _ = new_agent(turn_json("What's been hardest?"))
    agent.take_turn("I'm stressed.")
    assert agent.conversation_history[-2:] == [{"role": "user", "content": "I'm stressed."},
                                               {"role": "assistant", "content": "What's been hardest?"}]


# ---- Sentiment ----

def test_sentiment_starts_neutral_and_moves_toward_each_reading():
    agent, _ = new_agent(turn_json(sentiment=0.2), turn_json(sentiment=0.9))
    assert agent.sentiment == 0.5
    assert agent.take_turn("I'm really stressed.").sentiment == 0.32   # 0.4 * 0.5 + 0.6 * 0.2
    assert agent.take_turn("That really helps, thanks.").sentiment == 0.67


@pytest.mark.parametrize("reading", [1.7, -3, True, "high", None])
def test_out_of_range_or_invalid_sentiment_is_clamped_or_ignored(reading):
    agent, _ = new_agent(json.dumps({"reply": "Okay.", "sentiment": reading}))
    value = agent.take_turn("Hello").sentiment
    assert 0.0 <= value <= 1.0
    if reading in (True, "high", None):
        assert value == 0.5


# ---- Emergencies ----

def test_keyword_emergency_skips_the_model():
    agent, llm = new_agent()
    turn = agent.take_turn("I'm having chest pain right now")
    assert turn.action == "hang_up" and turn.end_reason == "Emergency detected"
    assert turn.emergency.source == "keyword" and turn.emergency.kind == "medical"
    assert turn.reply == EMERGENCY_REPLIES["medical"] and "9 1 1" in turn.reply
    assert llm.requests == []


def test_ai_detects_an_emergency_described_without_keywords():
    low_sugar = ("medical", "confusion and sweating suggest severe low blood sugar")
    agent, _ = new_agent(turn_json("Okay.", emergency=low_sugar))
    turn = agent.take_turn("I feel really shaky and confused and I'm sweating a lot")
    assert turn.action == "hang_up"
    assert turn.emergency.source == "ai" and turn.emergency.kind == "medical"
    assert "low blood sugar" in turn.emergency.reason
    assert turn.reply == EMERGENCY_REPLIES["medical"]
    assert agent.is_emergency


def test_mental_health_crisis_gets_the_988_message():
    agent, _ = new_agent(turn_json("Okay.", emergency=("mental_health", "says they don't want to go on")))
    turn = agent.take_turn("Some days I don't see the point of going on anymore")
    assert turn.emergency.kind == "mental_health"
    assert "9 8 8" in turn.reply and turn.action == "hang_up"


def test_keyword_emergency_drops_the_sentiment():
    """Found on a real call: "I'm having chest pain" left the dashboard showing 0.50 Neutral."""
    agent, _ = new_agent()
    assert agent.take_turn("I'm having chest pain").sentiment == 0.26  # 0.4*0.5 + 0.6*0.1


def test_emergency_keeps_a_score_the_model_already_set_low():
    agent, _ = new_agent(turn_json("Okay.", sentiment=0.05, emergency=("medical", "fainting")))
    assert agent.take_turn("I keep almost passing out").sentiment == 0.23  # model's reading only


def test_mental_health_keyword_is_caught_instantly():
    agent, llm = new_agent()
    turn = agent.take_turn("I've been thinking about ending my life, I just want to die")
    assert turn.emergency.kind == "mental_health" and turn.emergency.source == "keyword"
    assert "9 8 8" in turn.reply and llm.requests == []


# ---- No promises ----

@pytest.mark.parametrize("promise", [
    "I'll connect you with your care manager right away.",
    "Someone will call you back this afternoon.",
    "Your care team will reach out to you tomorrow.",
    "I'll send you a link to the form now.",
])
def test_promises_are_replaced_with_an_honest_reply(promise):
    agent, _ = new_agent(turn_json(promise))
    turn = agent.take_turn("Can someone help me with my refills?")
    assert turn.reply != promise and "note it for your care team" in turn.reply
    assert turn.blocked == {"rule": "promise", "text": promise}


def test_noting_something_for_the_care_team_is_allowed():
    honest = "I'll note that for your care team so they can follow up."
    agent, _ = new_agent(turn_json(honest))
    assert agent.take_turn("My refills keep getting delayed.").reply == honest


# ---- Ending the call and the feedback form ----

def test_patient_done_leads_to_the_feedback_question_then_goodbye():
    agent, _ = new_agent(
        turn_json("I'll note that for your care team. Is there anything else I can help you with today?",
                  sentiment=0.6, state="needs_met"),
        turn_json("I'm glad I could help.", sentiment=0.8, state="patient_done"),
    )
    assert agent.take_turn("I skipped a refill because of the cost.").action == "listen"

    closing = agent.take_turn("No, that's really helpful, thank you.")
    assert closing.action == "listen" and closing.phase == "feedback"
    assert closing.reply == f"I'm glad I could help. {FEEDBACK_QUESTION}"

    goodbye = agent.take_turn("Sure.")
    assert goodbye.action == "hang_up" and goodbye.feedback_opt_in is True
    assert goodbye.end_reason == "Patient's needs addressed"
    assert "noted that you'd like the feedback form" in goodbye.reply and "Maria" in goodbye.reply


@pytest.mark.parametrize("answer, wants_form", [
    ("Yes please", True), ("Sure, no problem", True), ("Okay", True),
    ("No thanks", False), ("Nah, I'm good", False), ("I'll pass", False), ("Hmm", False),
])
def test_feedback_answer_is_recorded(answer, wants_form):
    agent, _ = new_agent(turn_json(state="patient_done"))
    agent.take_turn("No, that's everything.")
    turn = agent.take_turn(answer)
    assert turn.feedback_opt_in is wants_form and turn.action == "hang_up"
    assert ("noted that you'd like" in turn.reply) is wants_form
    assert agent.end_call()["feedback_form_requested"] is wants_form


def test_saying_goodbye_offers_the_feedback_form_without_the_model():
    agent, llm = new_agent()
    turn = agent.take_turn("Okay, I have to go now, bye.")
    assert turn.reply == FEEDBACK_QUESTION and turn.action == "listen" and llm.requests == []
    final = agent.take_turn("No.")
    assert final.action == "hang_up" and final.end_reason == "Patient said goodbye"
    assert final.feedback_opt_in is False


def test_emergency_during_the_closing_still_wins():
    agent, _ = new_agent()
    agent.take_turn("Bye.")
    turn = agent.take_turn("Actually wait, I'm having chest pain")
    assert turn.emergency is not None and turn.action == "hang_up"
    assert turn.feedback_opt_in is None


def test_call_summary_includes_the_new_fields():
    agent, _ = new_agent(turn_json(sentiment=0.9, state="patient_done"))
    agent.take_turn("That's everything, thanks.")
    agent.take_turn("Yes")
    summary = agent.end_call()
    assert summary["final_sentiment"] == agent.sentiment
    assert summary["end_reason"] == "Patient's needs addressed"
    assert summary["feedback_form_requested"] is True


# ---- Parsing the model's output ----

def test_parse_accepts_json_in_a_code_fence():
    result = parse_model_output("```json\n" + turn_json("Hi.", sentiment=0.7) + "\n```")
    assert result["reply"] == "Hi." and result["sentiment"] == 0.7


def test_parse_ignores_unknown_states_and_emergency_types():
    raw = json.dumps({"reply": "Hi.", "conversation_state": "finished",
                      "emergency": {"detected": True, "type": "weird", "reason": "x"}})
    result = parse_model_output(raw)
    assert result["state"] == "ongoing" and result["emergency"]["kind"] == "medical"


# ---- Fixes found by testing against the real model ----

class FilteredLLM(ScriptedLLM):
    """Like Azure when its content-safety filter blocks a request."""

    def __init__(self, categories):
        super().__init__()
        self.categories = categories

    def complete(self, system_prompt, messages, json_mode=False):
        self.last_filter_categories = set(self.categories)
        return None


def test_self_harm_blocked_by_content_safety_is_treated_as_a_crisis():
    agent = HCMVoiceAgent(settings=VALID, llm=FilteredLLM({"self_harm"}))
    agent.initialize_call({"name": "Maria"})
    agent.phase = "conversation"
    turn = agent.take_turn("Things have been really dark lately.")
    assert turn.emergency.kind == "mental_health" and "9 8 8" in turn.reply
    assert turn.action == "hang_up"


def test_other_content_filter_blocks_get_the_polite_refusal():
    agent = HCMVoiceAgent(settings=VALID, llm=FilteredLLM({"violence"}))
    agent.initialize_call({"name": "Maria"})
    agent.phase = "conversation"
    turn = agent.take_turn("Something unrelated.")
    assert turn.emergency is None and turn.action == "listen"


def test_crisis_phrase_without_the_word_suicide_is_caught_instantly():
    agent, llm = new_agent()
    turn = agent.take_turn("Honestly some days I don't see the point of going on anymore.")
    assert turn.emergency.kind == "mental_health" and llm.requests == []


def test_no_to_anything_else_closes_without_the_model():
    agent, llm = new_agent(turn_json("I'll note that. Is there anything else I can help you with today?"))
    agent.take_turn("I skipped a refill because of the cost.")
    turn = agent.take_turn("No, that's really helpful, thank you.")
    assert turn.phase == "feedback" and turn.reply.endswith(FEEDBACK_QUESTION)
    assert len(llm.requests) == 1  # only the first turn asked the model


def test_thanks_in_a_closing_turn_lifts_the_sentiment():
    agent, _ = new_agent(turn_json("Is there anything else I can help you with today?", sentiment=0.3))
    assert agent.take_turn("I skipped a refill.").sentiment == 0.38
    assert agent.take_turn("No, that's really helpful, thank you.").sentiment == 0.63  # 0.4*0.38 + 0.6*0.8
    assert agent.take_turn("No thanks.").sentiment == 0.63  # declining the form isn't a mood signal


def test_no_with_more_to_say_keeps_the_conversation_going():
    agent, llm = new_agent(turn_json("Is there anything else I can help you with today?"), turn_json("Of course."))
    agent.take_turn("I skipped a refill.")
    turn = agent.take_turn("No, but actually I have a question about my test strips.")
    assert turn.phase == "conversation" and len(llm.requests) == 2


def test_filter_categories_are_read_from_azure_error_details():
    from hcm_agent.agent.llm import flagged_categories
    details = ("{'hate': {'filtered': False, 'severity': 'safe'}, 'self_harm': {'filtered': True, "
               "'severity': 'medium'}, 'sexual': {'filtered': False, 'severity': 'safe'}, "
               "'violence': {'filtered': False, 'severity': 'safe'}}")
    assert flagged_categories(details) == {"self_harm"}
    assert flagged_categories("no filter details") == set()


# ---- Opening: confirming who answered ----

def test_opening_asks_for_the_patient_without_mentioning_health():
    agent, _ = new_agent(verified=False)
    opening = agent.conversation_history[-1]["content"]
    assert opening == ("Hi, I'm Clara, a virtual assistant from your health insurance care team. "
                       "May I speak with Maria, please?")
    assert "diabetes" not in opening.lower()


@pytest.mark.parametrize("answer", ["Yes, this is Maria.", "Speaking.", "Yeah, that's me", "This is Maria", "Uh huh"])
def test_confirmed_patient_moves_on_to_the_check_in(answer):
    agent, llm = new_agent(verified=False)
    turn = agent.take_turn(answer)
    assert turn.identity == "confirmed" and turn.phase == "conversation" and turn.action == "listen"
    assert turn.reply.startswith("Thanks, Maria. I'm calling to check in on how you're doing with your diabetes")
    assert llm.requests == []  # no model needed for the opening


def test_someone_else_is_asked_for_a_good_time_then_the_time_is_noted():
    agent, llm = new_agent(verified=False)
    turn = agent.take_turn("No, this is John.")
    assert turn.identity == "not_available" and turn.spoke_with == "John" and turn.action == "listen"
    assert turn.reply == "No problem. What would be a good time to reach Maria?"
    assert "diabetes" not in turn.reply.lower()  # nothing health-related said to someone else

    final = agent.take_turn("Try tomorrow after 5 pm.")
    assert final.action == "hang_up" and final.callback_time == "Try tomorrow after 5 pm."
    assert final.end_reason == "Patient not available"
    assert "noted" in final.reply and "call" not in final.reply.lower()  # no promise to call back
    summary = agent.end_call()
    assert summary["callback_time"] == "Try tomorrow after 5 pm." and summary["spoke_with"] == "John"
    assert llm.requests == []


@pytest.mark.parametrize("heard", ["Yes, this is Yesh.", "Yes, this is Josh.", "This is Yash", "It's Yosh"])
def test_misheard_names_still_confirm_the_patient(heard):
    """Found on a real call: speech recognition heard "Yes, this is Yesh" for "Yes, this is Yash"."""
    agent, _ = new_agent(name="Yash", verified=False)
    turn = agent.take_turn(heard)
    assert turn.identity == "confirmed" and turn.phase == "conversation"


def test_a_clearly_different_name_is_someone_else():
    agent, _ = new_agent(name="Yash", verified=False)
    assert agent.take_turn("This is Michael.").identity == "not_available"


def test_a_time_given_up_front_is_noted_without_asking_again():
    agent, _ = new_agent(verified=False)
    turn = agent.take_turn("She's not here right now, she gets back around 6 tonight.")
    assert turn.action == "hang_up" and turn.callback_time.endswith("around 6 tonight.")


def test_a_relative_naming_the_patient_is_not_mistaken_for_them():
    agent, _ = new_agent(verified=False)
    turn = agent.take_turn("No, this is Maria's husband.")
    assert turn.identity == "not_available" and turn.spoke_with is None
    assert "good time to reach Maria" in turn.reply


def test_wrong_number_ends_politely():
    agent, _ = new_agent(verified=False)
    turn = agent.take_turn("I think you have the wrong number.")
    assert turn.identity == "wrong_number" and turn.action == "hang_up"
    assert turn.end_reason == "Wrong number" and "Maria" not in turn.reply


def test_unclear_answer_asks_again_then_moves_on():
    agent, _ = new_agent(verified=False)
    first = agent.take_turn("Hello?")
    assert first.reply == "Sorry, I didn't catch that. Am I speaking with Maria?" and first.phase == "verify"
    second = agent.take_turn("What's this about?")
    assert second.phase == "callback" and "good time to reach Maria" in second.reply


def test_emergency_during_the_opening_still_wins():
    agent, _ = new_agent(verified=False)
    turn = agent.take_turn("Help, my husband is having chest pain!")
    assert turn.emergency is not None and turn.action == "hang_up"


def test_without_a_name_the_call_starts_with_the_check_in():
    agent = HCMVoiceAgent(settings=VALID, llm=ScriptedLLM())
    agent.initialize_call({"name": "there"})
    assert agent.phase == "conversation" and "diabetes management" in agent.start_call()


# ---- The reason for the call and personal replies ----

def test_the_reason_for_the_call_shapes_what_the_patient_hears():
    agent = HCMVoiceAgent(settings=VALID, llm=ScriptedLLM())
    agent.initialize_call({"name": "Maria Lopez", "call_reason": "likelihood of high cost"})
    agent.start_call()
    reply = agent.take_turn("Yes, this is Maria.").reply
    assert reply.startswith("Thanks, Maria. I'm calling to check in on your health")
    assert "cost" not in reply.lower() and "diabetes" not in reply.lower()  # the internal label is never spoken


@pytest.mark.parametrize("label", sorted(CALL_REASONS))
def test_known_reasons_never_say_their_internal_label(label):
    reason = call_reason(label)
    said = f"{reason.purpose} {reason.question}".lower()
    assert not any(word in said for word in ("risk", "cost", "adherence", "readmission", "gap"))


def test_an_unlisted_reason_gets_a_general_opening_and_still_reaches_the_model():
    context = {"name": "Sam", "call_reason": "fall prevention"}
    agent = HCMVoiceAgent(settings=VALID, llm=ScriptedLLM())
    agent.initialize_call(context)
    agent.start_call()
    assert "check in on how you're doing with your health" in agent.take_turn("Yes, this is Sam.").reply
    assert "reason for this call: fall prevention." in get_system_prompt(context)


def test_prompt_carries_the_reason_and_what_the_care_team_noticed():
    prompt = get_system_prompt({"name": "Maria Lopez", "call_reason": "likelihood of high cost",
                                "risk_drivers": ["3 ER visits in the last 6 months"]})
    assert "reason for this call: likelihood of high cost." in prompt
    assert "- 3 ER visits in the last 6 months" in prompt
    assert "Call them Maria." in prompt and "MAKE IT PERSONAL" in prompt
    assert "noticed about this patient" not in get_system_prompt({"name": "Maria"})


def test_goodbye_uses_the_first_name():
    agent, _ = new_agent(name="John Doe")
    agent.take_turn("That's all, goodbye.")
    assert "Thank you for your time today, John." in agent.take_turn("No thanks.").reply


def test_curly_apostrophes_cannot_slip_a_promise_past_the_guardrails():
    agent, _ = new_agent(turn_json("I\u2019ll make sure a nurse calls you today \u2014 don\u2019t worry."))
    turn = agent.take_turn("Can someone call me?")
    assert turn.blocked["rule"] == "promise" and "note it for your care team" in turn.reply


def test_dashes_are_spoken_as_pauses():
    agent, _ = new_agent(turn_json("Night shifts are hard \u2014 how do you fit refills in?"))
    assert agent.take_turn("I work nights.").reply == "Night shifts are hard, how do you fit refills in?"
