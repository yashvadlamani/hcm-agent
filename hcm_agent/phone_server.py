"""Twilio phone conversation server for Guppy.

Twilio does speech-to-text and text-to-speech; each turn it posts what the
patient said here, HCMVoiceAgent replies (guardrails applied), and Twilio
speaks the reply and listens again.

NOTE: Twilio trial/standard tier is for testing only. Before production, move
to Twilio's HIPAA-eligible offering with a signed BAA.
"""

import hmac
import logging
import os
import re
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait

from dotenv import load_dotenv
from flask import Flask, Response, abort, request
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import Gather, VoiceResponse
from werkzeug.middleware.proxy_fix import ProxyFix

from .agent import HCMVoiceAgent

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# ngrok terminates HTTPS; trust its forwarded headers so request.url matches the URL Twilio signed.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

validator = RequestValidator(os.getenv("TWILIO_AUTH_TOKEN", ""))
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
WEBHOOK_KEY = os.getenv("PHONE_WEBHOOK_KEY", "")
calls: dict[str, HCMVoiceAgent] = {}
pending: dict[str, tuple[Future, str, float]] = {}
executor = ThreadPoolExecutor(max_workers=4)

VOICE = "Polly.Joanna"
MAX_REPLY_WAIT_SECONDS = 25
HOLD_SECONDS = 4.0
DEFAULT_RISK_DRIVERS = ["HbA1c above 7.5%", "Missed medication refills"]
GOODBYE = re.compile(r"\b(bye|goodbye|hang up|that's all|that is all)\b", re.IGNORECASE)


def twiml(response: VoiceResponse) -> Response:
    return Response(str(response), mimetype="text/xml")


def authorize(key: str) -> None:
    # Trial accounts send webhooks without X-Twilio-Signature, so the secret key in the
    # URL path is the primary check; a signature is still verified whenever one is sent.
    if not hmac.compare_digest(key, WEBHOOK_KEY):
        abort(404)
    if request.form.get("AccountSid") != ACCOUNT_SID:
        logger.warning("Rejected request for a different Twilio account")
        abort(403)
    signature = request.headers.get("X-Twilio-Signature")
    if signature and not validator.validate(request.url, request.form, signature):
        logger.warning("Rejected request with invalid Twilio signature: %s", request.url)
        abort(403)


def step_url(key: str, path: str) -> str:
    # Absolute URLs: the trial account's webhook fetcher fails on relative ones.
    return f"{request.host_url}t/{key}/{path}"


def say_and_listen(key: str, text: str) -> Response:
    response = VoiceResponse()
    gather = Gather(input="speech", action=step_url(key, "respond"), method="POST",
                    speech_timeout="2", language="en-US")
    gather.say(text, voice=VOICE)
    response.append(gather)
    response.redirect(step_url(key, "no-input"), method="POST")
    return twiml(response)


def say_and_hang_up(*lines: str) -> Response:
    response = VoiceResponse()
    for line in lines:
        response.say(line, voice=VOICE)
    response.hangup()
    return twiml(response)


def end_call(call_sid: str) -> None:
    pending.pop(call_sid, None)
    agent = calls.pop(call_sid, None)
    if agent:
        agent.end_call()
        logger.info("Transcript for %s:%s", call_sid, agent.get_conversation_transcript())


@app.post("/t/<key>/voice")
def voice(key):
    authorize(key)
    call_sid = request.form["CallSid"]
    name = request.args.get("name", "there")
    drivers = [d.strip() for d in request.args.get("drivers", "").split(",") if d.strip()]

    greeting = (
        f"Hi {name}, this is Guppy, a virtual assistant from your health insurance care team. "
        "I'm calling to check in on how you're doing with your diabetes management. "
        "How have you been feeling lately?"
    )

    agent = HCMVoiceAgent()
    agent.initialize_call({"name": name, "risk_drivers": drivers or DEFAULT_RISK_DRIVERS})
    agent.conversation_history = [
        {"role": "user", "content": "[The call has connected.]"},
        {"role": "assistant", "content": greeting},
    ]
    calls[call_sid] = agent
    logger.info("Call %s connected for %s", call_sid, name)
    return say_and_listen(key, greeting)


@app.post("/t/<key>/respond")
def respond(key):
    authorize(key)
    call_sid = request.form.get("CallSid", "")
    agent = calls.get(call_sid)
    if agent is None:
        return say_and_hang_up("Sorry, this call session has expired. Goodbye.")

    said = request.form.get("SpeechResult", "").strip()
    logger.info("Patient: %s", said)
    if not said:
        return say_and_listen(key, "Sorry, I didn't catch that. Could you say it again?")

    # Emergencies get a fixed, immediate response instead of waiting on the model.
    is_emergency, reason = agent.process_patient_input(said)
    if is_emergency:
        end_call(call_sid)
        return say_and_hang_up(
            "I'm really sorry you're going through this, and I want you to get help right away.",
            "If this is a medical emergency, please hang up and call 9 1 1 now. "
            "I'm also flagging this call for your care manager. Goodbye.",
        )

    pending[call_sid] = (executor.submit(agent.generate_response, said), said, time.monotonic())
    return reply_or_wait(key, call_sid)


@app.post("/t/<key>/reply")
def reply(key):
    authorize(key)
    return reply_or_wait(key, request.form.get("CallSid", ""))


def reply_or_wait(key: str, call_sid: str) -> Response:
    entry = pending.get(call_sid)
    if entry is None or call_sid not in calls:
        return say_and_listen(key, "Sorry, could you say that again?")

    future, said, started = entry
    # Trial accounts allow ~5s per webhook and ~10 webhooks per call, so block for most of
    # the 5s here and only fall back to a pause-and-recheck when the model is slower.
    wait([future], timeout=HOLD_SECONDS)
    logger.info("Reply check for %s: %s after %.1fs", call_sid[-6:],
                "ready" if future.done() else "not ready", time.monotonic() - started)
    if not future.done():
        if time.monotonic() - started > MAX_REPLY_WAIT_SECONDS:
            pending.pop(call_sid, None)
            return say_and_listen(key, "Sorry, I'm having trouble on my end. Could you say that again?")
        return wait_for_reply(key)

    pending.pop(call_sid, None)
    text = future.result()
    logger.info("Guppy (%.1fs): %s", time.monotonic() - started, text)

    if GOODBYE.search(said):
        end_call(call_sid)
        return say_and_hang_up(text)
    return say_and_listen(key, text)


def wait_for_reply(key: str) -> Response:
    response = VoiceResponse()
    response.pause(length=1)
    response.redirect(step_url(key, "reply"), method="POST")
    return twiml(response)


@app.post("/t/<key>/no-input")
def no_input(key):
    authorize(key)
    end_call(request.form.get("CallSid", ""))
    return say_and_hang_up(
        "I didn't hear anything, so I'll let you go. Your care team will follow up. Goodbye."
    )


if __name__ == "__main__":
    if len(WEBHOOK_KEY) < 20 or not ACCOUNT_SID:
        raise SystemExit("Set TWILIO_ACCOUNT_SID and a random PHONE_WEBHOOK_KEY (20+ chars) in .env")
    port = int(os.getenv("FLASK_PORT", "5000"))
    logger.info("Guppy phone server listening on http://127.0.0.1:%s", port)
    app.run(host="127.0.0.1", port=port)
