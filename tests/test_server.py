import dataclasses
from types import SimpleNamespace

import pytest
from azure.communication.callautomation import PhoneNumberIdentifier

from hcm_agent.agent.conversation import FEEDBACK_QUESTION, HCMVoiceAgent
from hcm_agent.telephony import live_feed, server
from test_config import VALID
from test_conversation import ScriptedLLM, turn_json

KEY = "test-webhook-key-0123456789"
CALL = "call-1"
PATIENT = "+15555550100"
REPLY = "Thanks for sharing that. What's been hardest lately?"


class FakeACS:
    """Records what Clara asks ACS to do: ("listen", text, target), ("say", text, context), ("hang_up",)."""

    def __init__(self):
        self.actions = []

    def get_call_connection(self, call_id):
        fake = self

        class Connection:
            def list_participants(self):
                return [SimpleNamespace(identifier=PhoneNumberIdentifier(VALID.acs_phone_number)),
                        SimpleNamespace(identifier=PhoneNumberIdentifier(PATIENT))]

            def start_recognizing_media(self, input_type, target_participant, *, play_prompt, **kwargs):
                fake.actions.append(("listen", play_prompt.text, target_participant.properties["value"]))

            def play_media_to_all(self, play_source, *, operation_context=None, **kwargs):
                fake.actions.append(("say", play_source.text, operation_context))

            def hang_up(self, is_for_everyone):
                fake.actions.append(("hang_up",))

        return Connection()

    def last(self):
        return self.actions[-1]


class RunNow:
    def submit(self, fn, *args):
        fn(*args)


@pytest.fixture
def model():
    """The scripted model behind every call's real HCMVoiceAgent. Tests queue its responses."""
    return ScriptedLLM(turn_json(REPLY))


@pytest.fixture
def acs(monkeypatch, model):
    fake = FakeACS()
    monkeypatch.setattr(server, "HCMVoiceAgent", lambda **_: HCMVoiceAgent(settings=VALID, llm=model))
    monkeypatch.setattr(server, "shared_llm", lambda: model)
    monkeypatch.setattr(server, "warm_up_model", lambda: None)
    monkeypatch.setattr(server, "WEBHOOK_KEY", KEY)
    monkeypatch.setattr(server, "LIVE_VIEW_PASSWORD", "")
    monkeypatch.setattr(server, "settings", dataclasses.replace(VALID, phone_webhook_key=KEY))
    monkeypatch.setattr(server, "acs", lambda: fake)
    monkeypatch.setattr(server, "executor", RunNow())
    server.calls.clear()
    live_feed.clear()
    return fake


@pytest.fixture
def client(acs):
    return server.app.test_client()


def send(client, event_type, key=KEY, ctx="", **data):
    body = [{"type": f"Microsoft.Communication.{event_type}", "data": {"callConnectionId": CALL, **data}}]
    query = f"?ctx={ctx}" if ctx else ""
    return client.post(f"/acs/{key}/events{query}", json=body).status_code


def connect(client, name="Yash", drivers=(), confirm=True, reason=""):
    """Start a call. confirm=True answers Clara's opening as the patient ("Yes, this is Yash.")."""
    from hcm_agent.telephony.outbound import encode_call_context
    status = send(client, "CallConnected", ctx=encode_call_context(name, list(drivers), reason))
    if confirm:
        speak(client, f"Yes, this is {name}.")
    return status


def speak(client, text, confidence=None):
    return send(client, "RecognizeCompleted", recognitionType="speech",
                speechResult={"speech": text, "confidence": confidence})


def event_types():
    return [e["type"] for e in live_feed.history()]


def test_rejects_wrong_key(client, acs):
    assert send(client, "CallConnected", key="wrong-key") == 404
    assert acs.actions == []


def test_rejects_non_json(client):
    assert client.post(f"/acs/{KEY}/events", data="hello").status_code == 400


def test_opening_asks_for_the_patient_and_clara_listens(client, acs):
    assert connect(client, confirm=False) == 200
    action, text, target = acs.last()
    assert action == "listen" and target == PATIENT
    assert text == ("Hi, I'm Clara, a virtual assistant from your health insurance care team. "
                    "May I speak with Yash, please?")


def test_confirmed_patient_hears_the_reason_for_the_call(client, acs, model):
    connect(client)
    action, text, _ = acs.last()
    assert action == "listen" and text.startswith("Thanks, Yash. I'm calling to check in")
    assert model.requests == []
    identity = next(e for e in live_feed.history() if e["type"] == "identity")
    assert identity["status"] == "confirmed"


def test_someone_else_answering_leads_to_a_noted_callback_time(client, acs):
    connect(client, confirm=False)
    speak(client, "No, this is John.")
    assert acs.last() == ("listen", "No problem. What would be a good time to reach Yash?", PATIENT)
    speak(client, "Tomorrow after 5.")
    action, text, context = acs.last()
    assert action == "say" and "noted" in text and context == "goodbye"
    callback = next(e for e in live_feed.history() if e["type"] == "callback")
    assert callback["time"] == "Tomorrow after 5." and callback["spoke_with"] == "John"
    assert event_types()[-1] == "call_ended"


def test_reply_is_spoken_and_clara_listens_again(client, acs):
    connect(client)
    speak(client, "I'm feeling stressed.")
    assert acs.last() == ("listen", REPLY, PATIENT)


def test_keyword_emergency_skips_model_and_hangs_up_after_the_message(client, acs, model):
    connect(client)
    speak(client, "I'm having chest pain")
    action, text, context = acs.last()
    assert action == "say" and "9 1 1" in text and context == "goodbye"
    assert model.requests == []
    assert CALL not in server.calls

    send(client, "PlayCompleted", operationContext="goodbye")
    assert acs.last() == ("hang_up",)


def test_ai_emergency_without_keywords_ends_the_call(client, acs, model):
    low_sugar = ("medical", "confusion and sweating suggest severe low blood sugar")
    model.responses = [turn_json("Okay.", emergency=low_sugar)]
    connect(client)
    speak(client, "I feel really shaky and confused and I'm sweating a lot")
    action, text, context = acs.last()
    assert action == "say" and "9 1 1" in text and context == "goodbye"
    emergency = next(e for e in live_feed.history() if e["type"] == "emergency")
    assert emergency["source"] == "ai" and emergency["kind"] == "medical"
    assert "low blood sugar" in emergency["reason"]


def test_goodbye_offers_the_feedback_form_then_ends(client, acs):
    connect(client)
    speak(client, "That's all, goodbye.")
    assert acs.last() == ("listen", FEEDBACK_QUESTION, PATIENT)
    assert CALL in server.calls

    speak(client, "Yes please.")
    action, text, context = acs.last()
    assert action == "say" and "noted that you'd like the feedback form" in text and context == "goodbye"
    assert CALL not in server.calls
    feedback = next(e for e in live_feed.history() if e["type"] == "feedback")
    assert feedback["requested"] is True


def test_patient_done_moves_to_the_closing(client, acs, model):
    model.responses = [turn_json("I'm glad I could help.", state="patient_done")]
    connect(client)
    speak(client, "No, that's everything I needed.")
    assert acs.last() == ("listen", f"I'm glad I could help. {FEEDBACK_QUESTION}", PATIENT)
    closing = next(e for e in live_feed.history() if e["type"] == "closing")
    assert closing["reason"] == "Patient's needs addressed"


def test_silence_reprompts_once_then_says_goodbye(client, acs):
    connect(client)
    send(client, "RecognizeFailed", resultInformation={"code": 400, "subCode": 8510})
    action, text, _ = acs.last()
    assert action == "listen" and "didn't catch that" in text

    send(client, "RecognizeFailed", resultInformation={"code": 400, "subCode": 8510})
    action, text, context = acs.last()
    assert action == "say" and "didn't hear anything" in text and context == "goodbye"


def test_speaking_resets_the_silence_count(client, acs):
    connect(client)
    send(client, "RecognizeFailed")
    speak(client, "Sorry, I'm here.")
    send(client, "RecognizeFailed")
    assert acs.last()[0] == "listen"  # re-asked again instead of hanging up


def test_patient_hanging_up_ends_the_call(client):
    connect(client)
    send(client, "CallDisconnected")
    assert CALL not in server.calls
    assert event_types()[-1] == "call_ended"


def test_events_for_unknown_calls_are_ignored(client, acs):
    speak(client, "Hello?")
    assert acs.actions == []


def test_greeting_reads_encoded_call_context(client):
    drivers = ["HbA1c above 7.5% at last check", "Missed refills, twice"]
    connect(client, "Yash", drivers)
    started = next(e for e in live_feed.history() if e["type"] == "call_started")
    assert started["name"] == "Yash" and started["drivers"] == drivers
    assert started["reason"] == "diabetes management"


def test_call_uses_the_reason_from_the_request(client, acs):
    connect(client, "Yash", reason="Likelihood of high cost")
    started = next(e for e in live_feed.history() if e["type"] == "call_started")
    assert started["reason"] == "likelihood of high cost" and started["drivers"] == []
    assert acs.last()[1].startswith("Thanks, Yash. I'm calling to check in on your health")


def test_live_feed_records_a_conversation(client, model):
    model.responses = [turn_json(REPLY, sentiment=0.2)]
    connect(client)
    speak(client, "I'm feeling stressed.", confidence=0.42)
    speak(client, "That's all, goodbye.")
    speak(client, "No thanks.")
    assert event_types() == [
        "call_started", "clara",
        "patient", "thinking", "identity", "clara",
        "patient", "thinking", "sentiment", "clara",
        "patient", "thinking", "closing", "clara",
        "patient", "thinking", "clara", "feedback", "call_ended",
    ]
    patient = next(e for e in live_feed.history() if e["type"] == "patient" and e["text"] == "I'm feeling stressed.")
    assert patient["confidence"] == 0.42


def test_live_feed_tracks_sentiment_from_neutral(client, model):
    model.responses = [turn_json(sentiment=0.2), turn_json(sentiment=0.9)]
    connect(client)
    assert next(e for e in live_feed.history() if e["type"] == "call_started")["sentiment"] == 0.5
    speak(client, "I'm really stressed.")
    speak(client, "That helps a lot, thanks.")
    readings = [(e["value"], e["change"]) for e in live_feed.history() if e["type"] == "sentiment"]
    assert readings == [(0.32, -0.18), (0.67, 0.35)]


def test_live_feed_records_emergency(client):
    connect(client)
    speak(client, "I'm having chest pain")
    assert event_types()[-3:] == ["emergency", "clara", "call_ended"]
    emergency = next(e for e in live_feed.history() if e["type"] == "emergency")
    assert emergency["source"] == "keyword"


def test_live_feed_shows_blocked_reply(client, model):
    model.responses = [turn_json("You have neuropathy.")]
    connect(client)
    speak(client, "What's wrong with my feet?")
    guardrail = next(e for e in live_feed.history() if e["type"] == "guardrail")
    assert guardrail["rule"] == "medical_diagnosis"
    assert guardrail["blocked_text"] == "You have neuropathy."


def test_live_view_is_local_only(client):
    assert client.get("/live").status_code == 200
    via_proxy = client.get("/live", headers={"X-Forwarded-For": "203.0.113.7"})
    assert via_proxy.status_code == 404
    assert client.get("/live/events", headers={"X-Forwarded-For": "203.0.113.7"}).status_code == 404


def test_status_page(client):
    response = client.get("/")
    assert response.status_code == 200 and b"running" in response.data


def basic_auth(password):
    import base64
    return {"Authorization": "Basic " + base64.b64encode(f"viewer:{password}".encode()).decode()}


def test_live_view_requires_password_when_configured(client, monkeypatch):
    monkeypatch.setattr(server, "LIVE_VIEW_PASSWORD", "correct-horse")
    proxied = {"X-Forwarded-For": "203.0.113.7"}

    missing = client.get("/live", headers=proxied)
    assert missing.status_code == 401
    assert "Basic" in missing.headers["WWW-Authenticate"]
    assert client.get("/live", headers={**proxied, **basic_auth("wrong")}).status_code == 401
    assert client.get("/live/events", headers=proxied).status_code == 401
    assert client.get("/live", headers={**proxied, **basic_auth("correct-horse")}).status_code == 200
