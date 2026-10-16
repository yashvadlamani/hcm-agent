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
import json
import logging
import os
import secrets
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from azure.communication.callautomation import (
    CallAutomationClient,
    PhoneNumberIdentifier,
    RecognizeInputType,
    TextSource,
)
from flask import Flask, Response, abort, jsonify, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from .. import config
from ..agent import HCMVoiceAgent
from ..agent.llm import LLM, create_llm
from ..call_reasons import CALL_REASONS, call_reason
from ..observability import call_trace, trace_store
from ..tools import security
from ..workflows.member_data import DEMO_MEMBERS_PATH, identity_record_for_phone, load_demo_members
from . import live_feed
from .call_requests import InvalidCallRequest, parse_call_request
from .outbound import decode_call_context, encode_call_context, to_e164
from .transcripts import transcript_store

logging.basicConfig(level=logging.INFO)
for _handler in logging.getLogger().handlers:  # phone numbers and other identifiers never reach the log
    _handler.addFilter(security.RedactingLogFilter())
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
NO_INPUT_GOODBYE = "I didn't hear anything, so I'll let you go. Your care team will follow up. Goodbye."
RESPONSE_FILLER_SECONDS = 8
RESPONSE_DEADLINE_SECONDS = 15
RESPONSE_FILLER = "Thanks for your patience. I'm checking that now."
RESPONSE_TIMEOUT_REPLY = "I'm having trouble connecting right now. Please try again in a moment."
RESPONSE_PENDING_REPLY = "I'm still checking that. Please give me another moment."


@dataclass
class CallState:
    agent: HCMVoiceAgent
    patient: PhoneNumberIdentifier
    lock: threading.Lock = field(default_factory=threading.Lock)
    silent_turns: int = 0
    pending_response: Future | None = None
    turn_number: int = 0


calls: dict[str, CallState] = {}
executor = ThreadPoolExecutor(max_workers=8)
# Never submit model work to the event executor: its workers must remain free to acknowledge ACS events.
response_executor = ThreadPoolExecutor(max_workers=8)
_client: CallAutomationClient | None = None
_llm: LLM | None = None


def acs() -> CallAutomationClient:
    global _client
    if _client is None:
        _client = (LocalPhone() if LOCAL_CHAT
                   else CallAutomationClient.from_connection_string(settings.acs_connection_string))
    return _client


def shared_llm() -> LLM:
    """One model client for every call, so calls reuse its open connection."""
    global _llm
    if _llm is None:
        _llm = create_llm(settings)
    return _llm


def warm_up_model() -> None:
    """A tiny request while the greeting plays, so a cold model never delays the patient's first turn."""
    started = time.monotonic()
    try:
        shared_llm().complete('Reply with the JSON object {"ok": true}.', [{"role": "user", "content": "ping"}],
                              json_mode=True)
        logger.info("Model warm-up took %.1fs", time.monotonic() - started)
    except Exception as e:
        logger.warning("Model warm-up failed: %s", e)


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
    name, drivers, reason = decode_call_context(ctx)
    reason = call_reason(reason).label
    executor.submit(warm_up_model)
    agent = HCMVoiceAgent(llm=shared_llm())
    patient = find_patient(call_id)
    identity_record = identity_record_for_phone(patient.properties["value"])
    agent.initialize_call({"name": name, "risk_drivers": drivers, "call_reason": reason, "call_id": call_id,
                           **LOCAL_CALLS.get(call_id, {}).get("context", {})},
                          identity_record=identity_record)
    greeting = agent.start_call()
    calls[call_id] = CallState(agent, patient)
    logger.info("Call %s connected for %s (%s)", call_id, name, reason)
    live_feed.publish(call_id, "call_started", name=name, drivers=drivers, reason=reason,
                      sentiment=agent.sentiment)
    say_and_listen(call_id, clara_says(call_id, greeting, kind="greeting"))


def on_speech(call_id: str, data: dict) -> None:
    state = calls.get(call_id)
    if state is None:
        return
    # Not named "speech": that would hide the speech() function the latency filler below calls.
    recognized = data.get("speechResult") or {}
    said = (recognized.get("speech") or "").strip()
    with state.lock:
        if not said:
            return listen_again(call_id, state)
        if state.pending_response is not None:
            return say_and_listen(call_id, clara_says(call_id, RESPONSE_PENDING_REPLY, kind="system"))
        if not _latency_control(state, "start").get("allowed", False):
            return say_and_listen(call_id, clara_says(call_id, RESPONSE_TIMEOUT_REPLY, kind="system"))
        state.silent_turns = 0
        state.turn_number += 1
        turn_number = state.turn_number
        agent = state.agent
        audit_start = len(agent.identity_gateway.audit_log)
        if agent.phase in ("verify_name", "verify_dob"):
            recorded, redacted = "[Identity answer provided]", False
        else:  # the dashboard, the saved transcript and the log get a copy without direct identifiers
            recorded, redacted = shown_text(agent, said)
        logger.info("Patient: %s", recorded)
        live_feed.publish(call_id, "patient", text=recorded, confidence=recognized.get("confidence"), redacted=redacted)
        sentiment_before, phase_before = agent.sentiment, agent.phase
        live_feed.publish(call_id, "thinking")
        future = response_executor.submit(_take_turn_with_trace, call_id, agent, said, turn_number)
        state.pending_response = future

    started = time.monotonic()
    try:
        turn = future.result(timeout=RESPONSE_FILLER_SECONDS)
    except TimeoutError:
        # Play only a prompt here (not recognition), so the same patient turn remains in progress.
        clara_says(call_id, RESPONSE_FILLER, kind="system", latency_notice=True)
        try:
            acs().get_call_connection(call_id).play_media_to_all(speech(RESPONSE_FILLER), operation_context="latency_filler")
            turn = future.result(timeout=RESPONSE_DEADLINE_SECONDS - RESPONSE_FILLER_SECONDS)
        except TimeoutError:
            _latency_control(state, "timeout")
            _clear_when_complete(state, future)
            logger.warning("Clara response exceeded %ss for %s", RESPONSE_DEADLINE_SECONDS, call_id[-8:])
            return say_and_listen(call_id, clara_says(call_id, RESPONSE_TIMEOUT_REPLY, kind="system",
                                                       latency=RESPONSE_DEADLINE_SECONDS, timed_out=True))
        except Exception:
            _latency_control(state, "failure")
            _clear_pending(state, future)
            logger.exception("Clara response failed after filler for %s", call_id[-8:])
            return say_and_listen(call_id, clara_says(call_id, RESPONSE_TIMEOUT_REPLY, kind="system"))
    except Exception:
        _latency_control(state, "failure")
        _clear_pending(state, future)
        logger.exception("Clara response failed for %s", call_id[-8:])
        return say_and_listen(call_id, clara_says(call_id, RESPONSE_TIMEOUT_REPLY, kind="system"))

    latency = time.monotonic() - started
    _latency_control(state, "success")
    _clear_pending(state, future)
    _deliver_turn(call_id, state, agent, turn, latency, sentiment_before, phase_before, turn_number,
                  tools=tools_used(agent, audit_start))


def _latency_control(state: CallState, action: str) -> dict:
    """Invoke the safety-family tool outside model control at every response-policy boundary."""
    result = state.agent.identity_gateway.invoke(
        "enforce_response_latency", state.agent.identity_context, {"action": action},
    )
    if not result.allowed:
        logger.error("Latency safety tool denied: %s", result.reason)
        return {"allowed": False}
    return result.data


def shown_text(agent: HCMVoiceAgent, said: str) -> tuple[str, bool]:
    """What the patient said, with phone numbers, card numbers and other direct identifiers replaced,
    using the classification tool. The model still receives the original words."""
    try:
        result = agent.identity_gateway.invoke("classify_sensitive_data", agent.identity_context, {
            "text": said, "member_id": agent.identity_context.member_id})
        if result.allowed and result.data.get("identifier_count"):
            return result.data["redacted_text"], True
    except Exception:
        logger.exception("Could not classify the patient's words; showing them as said")
    return said, False


def tools_used(agent: HCMVoiceAgent, audit_start: int) -> list[dict]:
    """The tools that ran during one turn, from the gateway's audit log: names and allowed/denied only."""
    return [{"tool": entry["tool"], "allowed": entry["allowed"]}
            for entry in agent.identity_gateway.audit_log[audit_start:]
            if entry["tool"] != "enforce_response_latency"]  # the deadline bookkeeping around every turn
def _take_turn_with_trace(call_id: str, agent: HCMVoiceAgent, said: str, turn_number: int):
    """Carry the opaque call correlation ID into the response-worker thread."""
    with call_trace(call_id, turn=turn_number):
        return agent.take_turn(said)


def _clear_pending(state: CallState, future: Future) -> None:
    with state.lock:
        if state.pending_response is future:
            state.pending_response = None


def _clear_when_complete(state: CallState, future: Future) -> None:
    """A timed-out SDK request cannot be force-cancelled; discard its reply when it eventually returns."""
    future.add_done_callback(lambda completed: _clear_pending(state, completed))


def _deliver_turn(call_id: str, state: CallState, agent: HCMVoiceAgent, turn, latency: float,
                  sentiment_before: float, phase_before: str, turn_number: int,
                  tools: list[dict] | None = None) -> None:
    """Publish and speak a completed turn after the safety deadline has been met."""
    logger.info("Clara (%.1fs, %s): %s", latency, turn.action, turn.reply)
    trace_entries = trace_store.summary(call_id)
    if trace_entries:
        live_feed.publish(call_id, "agent_trace", entries=trace_entries)
    if (turn.used_model and phase_before == "conversation") or turn.sentiment != sentiment_before:
        live_feed.publish(call_id, "sentiment", value=turn.sentiment, change=round(turn.sentiment - sentiment_before, 2))
    if turn.emergency:
        live_feed.publish(call_id, "emergency", kind=turn.emergency.kind, source=turn.emergency.source,
                          reason=turn.emergency.reason)
    if turn.escalation:
        live_feed.publish(call_id, "escalation", flagged=turn.escalation["flagged"],
                          queue=turn.escalation["queue"], records=turn.escalation["records"])
    if turn.security:
        live_feed.publish(call_id, "security", categories=turn.security.get("categories", []))
    if turn.blocked:
        live_feed.publish(call_id, "guardrail", rule=turn.blocked["rule"], blocked_text=turn.blocked["text"])
    if turn.identity:
        live_feed.publish(call_id, "identity", status=turn.identity, spoke_with=turn.spoke_with)
    if turn.callback_time:
        live_feed.publish(call_id, "callback", time=turn.callback_time, spoke_with=turn.spoke_with)
    if phase_before == "conversation" and turn.phase == "feedback":
        live_feed.publish(call_id, "closing", reason=agent.closing_reason)
    kind = ("emergency" if turn.emergency else "goodbye" if turn.action == "hang_up" else
            "opening" if turn.phase in ("verify_name", "verify_dob") or turn.identity == "confirmed" else
            "closing" if turn.phase == "feedback" else "reply")
    timing = {"latency": round(latency, 1)} if turn.used_model else {}
    clara_says(call_id, turn.reply, kind=kind, tools=tools or [], **timing)
    if turn.feedback_opt_in is not None:
        live_feed.publish(call_id, "feedback", requested=turn.feedback_opt_in)
    if turn.action == "hang_up":
        end_call(call_id, reason=turn.end_reason or "Call complete")
        return say_and_hang_up(call_id, turn.reply)
    say_and_listen(call_id, turn.reply)


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
        transcript_store.save(call_id, [event for event in live_feed.history() if event["call"] == call_id])
        logger.info("Transcript for %s:%s", call_id, state.agent.get_conversation_transcript())


def clara_says(call_id: str, text: str, **extra) -> str:
    live_feed.publish(call_id, "clara", text=text, **extra)
    return text


# ---- Local test chat (clara-interactive-chat): a typed call with no phone and no ACS minutes ----

# Off on Azure. clara-interactive-chat turns it on for a server that only this machine can reach.
LOCAL_CHAT = False
LOCAL_CALLS: dict[str, dict] = {}  # call id -> {"phone": the chosen member's number, "context": extra call context}


class LocalPhone:
    """Stands in for ACS in a local test chat. The call runs through the same handlers as a phone
    call, but Clara's words go only to the live page and the patient's words are typed there."""

    def get_call_connection(self, call_id: str):
        return LocalConnection(call_id)


class LocalConnection:
    def __init__(self, call_id: str):
        self.call_id = call_id

    def list_participants(self):
        # The chosen member's number, so the server finds the same member record a phone call would.
        return [SimpleNamespace(identifier=PhoneNumberIdentifier(LOCAL_CALLS[self.call_id]["phone"]))]

    def start_recognizing_media(self, *args, **kwargs) -> None:
        """Clara spoke and is listening: the page already shows her words and waits for typing."""

    def play_media_to_all(self, *args, **kwargs) -> None:
        """A filler or goodbye: already shown on the page."""

    def hang_up(self, *args, **kwargs) -> None:
        pass


def local_members() -> list[dict]:
    return load_demo_members(Path(os.environ.get("MEMBER_DATA_PATH", str(DEMO_MEMBERS_PATH))))


def require_local_chat() -> None:
    if not LOCAL_CHAT:
        abort(404)
    protect_live_view()


def local_call_id() -> str:
    call_id = (request.get_json(silent=True) or {}).get("call", "")
    if call_id not in calls:
        abort(Response("That call has ended.", 409))
    return call_id


@app.get("/chat/config")
def chat_config():
    """The members a test call can be started for. Dates of birth are included because this is a
    local tool for the demo data: the tester has to give the right answers to pass verification."""
    require_local_chat()
    members = [{"member_id": m["member_id"], "name": m["name"], "date_of_birth": m.get("date_of_birth", ""),
                "scenario": m.get("scenario", ""), "for": (m.get("demo_call_context") or {}).get("for", ""),
                "risk_drivers": (m.get("demo_call_context") or {}).get("risk_drivers", [])}
               for m in local_members()]
    return jsonify(members=members, reasons=sorted(CALL_REASONS))


@app.post("/chat/start")
def chat_start():
    """Start a test call for one member of the member data, as if their phone had been dialed."""
    require_local_chat()
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        abort(Response("Expected a JSON object.", 400))
    member = next((m for m in local_members() if m["member_id"] == body.get("member_id")), None)
    if member is None:
        abort(Response("Choose a member from the member data.", 400))
    demo = member.get("demo_call_context") or {}
    try:
        call = parse_call_request(json.dumps({
            "to": member["phone"], "name": member["name"],
            "for": body.get("for") or demo.get("for") or "diabetes management",
            "risk_drivers": body.get("risk_drivers", demo.get("risk_drivers", [])),
        }).encode())
    except InvalidCallRequest as e:
        abort(Response(f"Invalid call request: {e}", 400))
    call_id = f"local-{secrets.token_hex(4)}"
    # local_demo_context lets the care tools use the member's fictional demo scenario, as clara-chat does.
    LOCAL_CALLS[call_id] = {"phone": to_e164(member["phone"]), "context": {"local_demo_context": bool(demo)}}
    on_connected(call_id, encode_call_context(call.name, call.risk_drivers, call.reason))
    return jsonify(call=call_id)


@app.post("/chat/say")
def chat_say():
    """The patient's typed words. Empty text is the patient staying silent."""
    require_local_chat()
    call_id = local_call_id()
    text = str((request.get_json(silent=True) or {}).get("text", "")).strip()
    if text:
        executor.submit(handle_event, "RecognizeCompleted",
                        {"callConnectionId": call_id, "speechResult": {"speech": text}}, "")
    else:
        executor.submit(handle_event, "RecognizeFailed", {"callConnectionId": call_id}, "")
    return "", 202


@app.post("/chat/hangup")
def chat_hangup():
    require_local_chat()
    handle_event("CallDisconnected", {"callConnectionId": local_call_id()}, "")
    return "", 200


def run_local_chat(port: int) -> None:
    """Serve the local test chat on this machine only. Needs a model, but no ACS settings."""
    global LOCAL_CHAT, _client
    config.require(config.llm_problems(settings))
    LOCAL_CHAT, _client = True, None
    app.run(host="127.0.0.1", port=port, threaded=True)


# ---- Status page and live view ----

def protect_live_view() -> None:
    if LIVE_VIEW_PASSWORD and not LOCAL_CHAT:
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


@app.get("/live/history")
def live_history():
    """Return locally retained, completed demo calls for the authenticated live view."""
    protect_live_view()
    return {"calls": transcript_store.recent()}


@app.delete("/live/history")
def delete_live_history():
    """Delete only dashboard-selected completed local-demo transcripts."""
    protect_live_view()
    payload = request.get_json(silent=True) or {}
    call_ids = payload.get("call_ids", [])
    if not isinstance(call_ids, list) or len(call_ids) > 50:
        abort(400)
    deleted = transcript_store.delete(call_ids)
    live_feed.remove_calls(set(deleted))
    return {"deleted": deleted}


@app.post("/live/events")
def live_event_ingest():
    """Accept dashboard events from the local CLI simulator.

    This endpoint uses the same local-only/Basic Auth protection as the live view.
    It is deliberately not used by ACS or exposed as a general event collector.
    """
    protect_live_view()
    payload = request.get_json(silent=True) or {}
    call_id = str(payload.get("call", "")).strip()
    event_type = str(payload.get("type", "")).strip()
    data = payload.get("data", {})
    allowed = {"call_started", "patient", "thinking", "agent_trace", "sentiment", "identity",
               "callback", "closing", "feedback", "clara", "call_ended", "emergency", "guardrail"}
    if not call_id or event_type not in allowed or not isinstance(data, dict):
        abort(400)
    live_feed.publish(call_id, event_type, **data)
    if event_type == "call_ended":
        transcript_store.save(call_id, [event for event in live_feed.history() if event["call"] == call_id])
    return "", 204


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
