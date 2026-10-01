import dataclasses
from types import SimpleNamespace

import pytest
from azure.communication.callautomation import PhoneNumberIdentifier

from hcm_agent.telephony import live_feed, server
from test_config import VALID

KEY = "test-webhook-key-0123456789"
CALL = "call-1"
PATIENT = "+15555550100"


class FakeAgent:
    """Stands in for HCMVoiceAgent so tests never call a model."""

    reply = "Thanks for sharing that. How can I help?"

    def __init__(self):
        self.conversation_history = []
        self.generate_calls = 0

    def initialize_call(self, patient_context):
        self.patient_context = patient_context

    def process_patient_input(self, said):
        is_emergency = "chest pain" in said.lower()
        return is_emergency, "chest pain" if is_emergency else ""

    def generate_response(self, said):
        self.generate_calls += 1
        return FakeAgent.reply

    def end_call(self):
        return {}

    def get_conversation_transcript(self):
        return ""


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
def acs(monkeypatch):
    fake = FakeACS()
    monkeypatch.setattr(server, "HCMVoiceAgent", FakeAgent)
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


def connect(client, name="Yash", drivers=()):
    from hcm_agent.telephony.outbound import encode_call_context
    return send(client, "CallConnected", ctx=encode_call_context(name, list(drivers)))


def speak(client, text, confidence=None):
    return send(client, "RecognizeCompleted", recognitionType="speech",
                speechResult={"speech": text, "confidence": confidence})


def test_rejects_wrong_key(client, acs):
    assert send(client, "CallConnected", key="wrong-key") == 404
    assert acs.actions == []


def test_rejects_non_json(client):
    assert client.post(f"/acs/{KEY}/events", data="hello").status_code == 400


def test_greeting_is_spoken_to_the_patient_and_clara_listens(client, acs):
    assert connect(client) == 200
    action, text, target = acs.last()
    assert action == "listen" and target == PATIENT
    assert text.startswith("Hi Yash, this is Clara")


def test_reply_is_spoken_and_clara_listens_again(client, acs):
    connect(client)
    speak(client, "I'm feeling stressed.")
    assert acs.last() == ("listen", FakeAgent.reply, PATIENT)


def test_emergency_skips_model_and_hangs_up_after_the_message(client, acs):
    connect(client)
    agent = server.calls[CALL].agent
    speak(client, "I'm having chest pain")
    action, text, context = acs.last()
    assert action == "say" and "9 1 1" in text and context == "goodbye"
    assert agent.generate_calls == 0
    assert CALL not in server.calls

    send(client, "PlayCompleted", operationContext="goodbye")
    assert acs.last() == ("hang_up",)


def test_goodbye_ends_the_call(client, acs):
    connect(client)
    speak(client, "That's all, goodbye.")
    assert acs.last() == ("say", FakeAgent.reply, "goodbye")
    assert CALL not in server.calls


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


def test_live_feed_records_a_conversation(client):
    connect(client)
    speak(client, "I'm feeling stressed.", confidence=0.42)
    speak(client, "That's all, goodbye.")
    assert event_types() == [
        "call_started", "clara",
        "patient", "thinking", "clara",
        "patient", "thinking", "clara", "call_ended",
    ]
    patient = next(e for e in live_feed.history() if e["type"] == "patient")
    assert patient["confidence"] == 0.42


def test_live_feed_records_emergency(client):
    connect(client)
    speak(client, "I'm having chest pain")
    assert event_types()[-3:] == ["emergency", "clara", "call_ended"]


def test_live_feed_shows_blocked_reply(client):
    connect(client)
    server.calls[CALL].agent.last_blocked_reply = {"rule": "medical_diagnosis", "text": "You have neuropathy."}
    speak(client, "What's wrong with my feet?")
    guardrail = next(e for e in live_feed.history() if e["type"] == "guardrail")
    assert guardrail["rule"] == "medical_diagnosis"
    assert guardrail["blocked_text"] == "You have neuropathy."


def event_types():
    return [e["type"] for e in live_feed.history()]


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
