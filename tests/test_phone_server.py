import threading

import pytest

from hcm_agent import phone_server

KEY = "test-webhook-key-0123456789"
ACCOUNT = "ACtest"
BASE = "https://example.ngrok-free.dev"


class FakeAgent:
    """Stands in for HCMVoiceAgent so tests never call Claude."""

    reply = "Thanks for sharing that. How can I help?"
    release: threading.Event | None = None

    def __init__(self):
        self.conversation_history = []
        self.is_emergency = False
        self.generate_calls = 0

    def initialize_call(self, patient_context):
        self.patient_context = patient_context

    def process_patient_input(self, said):
        self.is_emergency = "chest pain" in said.lower()
        return self.is_emergency, "chest pain" if self.is_emergency else ""

    def generate_response(self, said):
        self.generate_calls += 1
        if FakeAgent.release is not None:
            FakeAgent.release.wait(timeout=5)
        return FakeAgent.reply

    def end_call(self):
        return {}

    def get_conversation_transcript(self):
        return ""


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(phone_server, "HCMVoiceAgent", FakeAgent)
    monkeypatch.setattr(phone_server, "WEBHOOK_KEY", KEY)
    monkeypatch.setattr(phone_server, "ACCOUNT_SID", ACCOUNT)
    monkeypatch.setattr(phone_server, "HOLD_SECONDS", 0.2)
    phone_server.calls.clear()
    phone_server.pending.clear()
    FakeAgent.release = None
    return phone_server.app.test_client()


def post(client, path, key=KEY, account=ACCOUNT, **form):
    data = {"AccountSid": account, "CallSid": "CA1", **form}
    response = client.post(f"/t/{key}/{path}", data=data, base_url=BASE)
    return response.status_code, response.get_data(as_text=True)


def test_rejects_wrong_key(client):
    assert post(client, "voice", key="wrong-key")[0] == 404


def test_rejects_other_twilio_account(client):
    assert post(client, "voice", account="ACother")[0] == 403


def test_greeting_uses_clara_and_absolute_callback(client):
    status, body = post(client, "voice?name=Yash")
    assert status == 200
    assert "Hi Yash, this is Clara" in body
    assert f'action="{BASE}/t/{KEY}/respond"' in body


def test_reply_is_spoken_and_clara_listens_again(client):
    post(client, "voice?name=Yash")
    status, body = post(client, "respond", SpeechResult="I'm feeling stressed.")
    assert status == 200
    assert FakeAgent.reply in body
    assert "<Gather" in body


def test_emergency_skips_model_and_hangs_up(client):
    post(client, "voice?name=Yash")
    agent = phone_server.calls["CA1"]
    _, body = post(client, "respond", SpeechResult="I'm having chest pain")
    assert "9 1 1" in body and "<Hangup" in body
    assert agent.generate_calls == 0
    assert "CA1" not in phone_server.calls


def test_goodbye_ends_the_call(client):
    post(client, "voice?name=Yash")
    _, body = post(client, "respond", SpeechResult="That's all, goodbye.")
    assert "<Hangup" in body


def test_empty_speech_reprompts(client):
    post(client, "voice?name=Yash")
    _, body = post(client, "respond", SpeechResult="")
    assert "didn't catch that" in body and "<Gather" in body


def test_slow_reply_pauses_then_delivers(client):
    post(client, "voice?name=Yash")
    FakeAgent.release = threading.Event()

    _, body = post(client, "respond", SpeechResult="Tell me more.")
    assert "<Pause" in body and f"{BASE}/t/{KEY}/reply" in body

    FakeAgent.release.set()
    _, body = post(client, "reply")
    assert FakeAgent.reply in body


def test_no_input_hangs_up(client):
    post(client, "voice?name=Yash")
    _, body = post(client, "no-input")
    assert "<Hangup" in body
