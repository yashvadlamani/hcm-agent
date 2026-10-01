"""Clara's phone conversation server, driven by Azure Communication Services (ACS) Call Automation.

ACS dials the patient (see outbound.py) and posts call events here. Each turn, Clara speaks with
ACS text-to-speech and listens with ACS speech recognition. When the patient's words arrive,
HCMVoiceAgent replies (guardrails applied), and Clara speaks the reply and listens again.

Events are acknowledged immediately and handled in the background, so a slow model reply never
times out the call.

NOTE: trial phone numbers are for testing only (30 days, 5-minute calls). Production needs a
purchased number and Microsoft's BAA in place for HIPAA workloads.
"""

import hmac
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from azure.communication.callautomation import (
    CallAutomationClient,
    PhoneNumberIdentifier,
    RecognizeInputType,
    TextSource,
)
from flask import Flask, Response, abort, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from .. import config
from ..agent import HCMVoiceAgent
from . import live_feed
from .outbound import decode_call_context, to_e164

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
app = Flask(__name__, static_folder=None)
# Azure App Service terminates HTTPS; trust its forwarded headers.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

settings = config.load()
WEBHOOK_KEY = settings.phone_webhook_key
# When set (e.g. on Azure), /live asks for this password; when unset, /live is local-only.
LIVE_VIEW_PASSWORD = settings.live_view_password
for problem in config.server_problems(settings):
    logger.warning("Configuration problem: %s", problem)

VOICE = settings.acs_voice
INITIAL_SILENCE_SECONDS = 8   # how long to wait for the patient to start speaking
END_SILENCE_SECONDS = 2       # pause that marks the end of what they said
MAX_SILENT_TURNS = 2          # re-ask once, then say goodbye
DEFAULT_RISK_DRIVERS = ["HbA1c above 7.5%", "Missed medication refills"]
GOODBYE = re.compile(r"\b(bye|goodbye|hang up|that's all|that is all)\b", re.IGNORECASE)
EMERGENCY_LINES = (
    "I'm really sorry you're going through this, and I want you to get help right away. "
    "If this is a medical emergency, please hang up and call 9 1 1 now. "
    "I'm also flagging this call for your care manager. Goodbye."
)
NO_INPUT_GOODBYE = "I didn't hear anything, so I'll let you go. Your care team will follow up. Goodbye."


@dataclass
class CallState:
    agent: HCMVoiceAgent
    patient: PhoneNumberIdentifier
    lock: threading.Lock = field(default_factory=threading.Lock)
    silent_turns: int = 0


calls: dict[str, CallState] = {}
executor = ThreadPoolExecutor(max_workers=8)
_client: CallAutomationClient | None = None


def acs() -> CallAutomationClient:
    global _client
    if _client is None:
        _client = CallAutomationClient.from_connection_string(settings.acs_connection_string)
    return _client


# ---- Call events from ACS ----

@app.post("/acs/<key>/events")
def acs_events(key):
    # The secret key in the callback URL (known only to ACS and our own apps) authorizes events.
    if not hmac.compare_digest(key, WEBHOOK_KEY):
        abort(404)
    events = request.get_json(silent=True)
    if isinstance(events, dict):
        events = [events]
    if not isinstance(events, list):
        abort(400)
    ctx = request.args.get("ctx", "")
    for event in events:
        if isinstance(event, dict):
            executor.submit(handle_event, event.get("type", ""), event.get("data") or {}, ctx)
    return "", 200


def handle_event(event_type: str, data: dict, ctx: str) -> None:
    kind = event_type.removeprefix("Microsoft.Communication.")
    call_id = data.get("callConnectionId", "")
    result = data.get("resultInformation") or {}
    logger.info("ACS %s for %s (%s %s)", kind, call_id[-8:], result.get("code", ""), result.get("message", ""))
    try:
        if kind == "CallConnected":
            on_connected(call_id, ctx)
        elif kind == "RecognizeCompleted":
            on_speech(call_id, data)
        elif kind == "RecognizeFailed":
            on_silence(call_id)
        elif kind in ("PlayCompleted", "PlayFailed") and data.get("operationContext") == "goodbye":
            hang_up(call_id)
        elif kind == "CallDisconnected":
            end_call(call_id, reason="Call disconnected")
        elif kind == "CreateCallFailed":
            logger.warning("Call could not be placed: %s", result)
    except Exception:
        logger.exception("Error handling %s for %s", kind, call_id)


def on_connected(call_id: str, ctx: str) -> None:
    name, drivers = decode_call_context(ctx)
    greeting = (
        f"Hi {name}, this is Clara, a virtual assistant from your health insurance care team. "
        "I'm calling to check in on how you're doing with your diabetes management. "
        "How have you been feeling lately?"
    )
    agent = HCMVoiceAgent()
    agent.initialize_call({"name": name, "risk_drivers": drivers or DEFAULT_RISK_DRIVERS})
    agent.conversation_history = [
        {"role": "user", "content": "[The call has connected.]"},
        {"role": "assistant", "content": greeting},
    ]
    calls[call_id] = CallState(agent, find_patient(call_id))
    logger.info("Call %s connected for %s", call_id, name)
    live_feed.publish(call_id, "call_started", name=name, drivers=agent.patient_context.get("risk_drivers", []))
    say_and_listen(call_id, clara_says(call_id, greeting, kind="greeting"))


def on_speech(call_id: str, data: dict) -> None:
    state = calls.get(call_id)
    if state is None:
        return
    speech = data.get("speechResult") or {}
    said = (speech.get("speech") or "").strip()
    with state.lock:
        if not said:
            return listen_again(call_id, state)
        state.silent_turns = 0
        logger.info("Patient: %s", said)
        live_feed.publish(call_id, "patient", text=said, confidence=speech.get("confidence"))

        # Emergencies get a fixed, immediate response instead of waiting on the model.
        is_emergency, reason = state.agent.process_patient_input(said)
        if is_emergency:
            live_feed.publish(call_id, "emergency", reason=reason)
            clara_says(call_id, EMERGENCY_LINES, kind="emergency")
            end_call(call_id, reason="Emergency detected")
            return say_and_hang_up(call_id, EMERGENCY_LINES)

        live_feed.publish(call_id, "thinking")
        started = time.monotonic()
        text = state.agent.generate_response(said)
        latency = time.monotonic() - started
        logger.info("Clara (%.1fs): %s", latency, text)

        blocked = getattr(state.agent, "last_blocked_reply", None)
        if blocked:
            live_feed.publish(call_id, "guardrail", rule=blocked["rule"], blocked_text=blocked["text"])
        clara_says(call_id, text, kind="reply", latency=round(latency, 1))

        if GOODBYE.search(said):
            end_call(call_id, reason="Patient said goodbye")
            return say_and_hang_up(call_id, text)
        say_and_listen(call_id, text)


def on_silence(call_id: str) -> None:
    state = calls.get(call_id)
    if state is not None:
        with state.lock:
            listen_again(call_id, state)


def listen_again(call_id: str, state: CallState) -> None:
    """The patient said nothing (or nothing we caught): re-ask once, then end the call politely."""
    state.silent_turns += 1
    if state.silent_turns >= MAX_SILENT_TURNS:
        clara_says(call_id, NO_INPUT_GOODBYE, kind="system")
        end_call(call_id, reason="No response from patient")
        return say_and_hang_up(call_id, NO_INPUT_GOODBYE)
    say_and_listen(call_id, clara_says(call_id, "Sorry, I didn't catch that. Could you say it again?", kind="system"))


# ---- Talking to ACS ----

def find_patient(call_id: str) -> PhoneNumberIdentifier:
    """The patient is the phone participant that isn't Clara's own number."""
    ours = to_e164(settings.acs_phone_number)
    for participant in acs().get_call_connection(call_id).list_participants():
        identifier = participant.identifier
        if isinstance(identifier, PhoneNumberIdentifier) and identifier.properties.get("value") != ours:
            return identifier
    raise RuntimeError(f"No patient phone number among the participants of call {call_id}")


def speech(text: str) -> TextSource:
    return TextSource(text=text, voice_name=VOICE)


def say_and_listen(call_id: str, text: str) -> None:
    state = calls.get(call_id)
    if state is None:
        return
    acs().get_call_connection(call_id).start_recognizing_media(
        input_type=RecognizeInputType.SPEECH,
        target_participant=state.patient,
        play_prompt=speech(text),
        initial_silence_timeout=INITIAL_SILENCE_SECONDS,
        end_silence_timeout=END_SILENCE_SECONDS,
        speech_language="en-US",
        operation_context="turn",
    )


def say_and_hang_up(call_id: str, text: str) -> None:
    # Hang up once the goodbye has played (PlayCompleted with operationContext "goodbye").
    acs().get_call_connection(call_id).play_media_to_all(speech(text), operation_context="goodbye")


def hang_up(call_id: str) -> None:
    try:
        acs().get_call_connection(call_id).hang_up(is_for_everyone=True)
    except Exception:  # already disconnected
        logger.info("Call %s was already over", call_id)


def end_call(call_id: str, reason: str) -> None:
    state = calls.pop(call_id, None)
    if state:
        state.agent.end_call()
        live_feed.publish(call_id, "call_ended", reason=reason)
        logger.info("Transcript for %s:%s", call_id, state.agent.get_conversation_transcript())


def clara_says(call_id: str, text: str, **extra) -> str:
    live_feed.publish(call_id, "clara", text=text, **extra)
    return text


# ---- Status page and live view ----

def protect_live_view() -> None:
    if LIVE_VIEW_PASSWORD:
        auth = request.authorization
        if not auth or not hmac.compare_digest(auth.password or "", LIVE_VIEW_PASSWORD):
            abort(Response("Sign in to view live calls.", 401,
                           {"WWW-Authenticate": 'Basic realm="Clara live calls"'}))
        return
    # No password configured: allow only direct requests from this machine. Traffic that came
    # through a proxy or load balancer (such as Azure's front end) carries X-Forwarded-For.
    if request.headers.get("X-Forwarded-For") or request.remote_addr not in ("127.0.0.1", "::1"):
        abort(404)


@app.get("/")
def status():
    return Response("Clara phone server is running.", mimetype="text/plain")


@app.get("/live")
def live_page():
    protect_live_view()
    return send_from_directory(STATIC_DIR, "live.html")


@app.get("/live/events")
def live_events():
    protect_live_view()
    return Response(live_feed.stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache"})


def main() -> None:
    """Run the development server locally (`clara-server`). Azure runs `app` under gunicorn."""
    try:
        config.require(config.server_problems(settings))
    except config.ConfigError as e:
        raise SystemExit(str(e))
    logger.info("Clara phone server listening on http://127.0.0.1:%s", settings.port)
    logger.info("Live call view: http://127.0.0.1:%s/live", settings.port)
    app.run(host="127.0.0.1", port=settings.port, threaded=True)


if __name__ == "__main__":
    main()
