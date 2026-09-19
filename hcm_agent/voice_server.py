"""Flask server for handling Twilio webhooks and managing voice calls."""

import os
import logging
import json
from flask import Flask, request, jsonify
from twilio.twiml.voice_response import VoiceResponse

from .agent import HCMVoiceAgent
from .voice_service import (
    TwilioVoiceService, DeepgramASRService, ElevenLabsTTSService, VoiceCallManager
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Initialize services
try:
    agent = HCMVoiceAgent()
    twilio_service = TwilioVoiceService()
    deepgram_service = DeepgramASRService()
    elevenlabs_service = ElevenLabsTTSService()
    call_manager = VoiceCallManager(agent, twilio_service, deepgram_service, elevenlabs_service)
except ValueError as e:
    logger.error(f"Failed to initialize voice services: {e}")
    logger.error("Make sure all required API keys are set in .env file")


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "service": "HCM Voice Agent"}), 200


@app.route("/call/initiate", methods=["POST"])
def initiate_call():
    """
    Initiate an outbound call to a patient.

    Expected JSON:
    {
        "to_number": "+1-704-430-5315",
        "patient_context": {
            "name": "John Doe",
            "risk_drivers": ["HbA1c > 7.5%", "BP elevated"]
        }
    }
    """
    try:
        data = request.get_json()
        to_number = data.get("to_number")
        patient_context = data.get("patient_context", {})

        if not to_number:
            return jsonify({"error": "Missing 'to_number'"}), 400

        # Get the webhook URL for call events
        webhook_url = f"{request.host_url}call/handle-inbound"

        # Initiate the call
        call_sid = call_manager.initiate_outbound_call(to_number, patient_context, webhook_url)

        return jsonify({
            "status": "initiated",
            "call_sid": call_sid,
            "patient": patient_context.get("name", "Unknown"),
            "to_number": to_number
        }), 200

    except Exception as e:
        logger.error(f"Error initiating call: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/call/handle-inbound", methods=["POST"])
def handle_inbound_call():
    """
    Handle incoming Twilio webhook for call events.
    This is called when:
    1. Call connects (CallStatus=in-progress)
    2. User leaves voicemail (CallStatus=completed)
    3. Call recording becomes available
    """
    try:
        call_sid = request.form.get("CallSid")
        call_status = request.form.get("CallStatus")
        recording_url = request.form.get("RecordingUrl")

        logger.info(f"Webhook received - CallSid: {call_sid}, Status: {call_status}")

        response = VoiceResponse()

        if call_status == "in-progress":
            # Call is connected, prompt user to speak
            response.say("Please leave a message or describe how you're feeling today.")
            response.record(
                max_length=60,
                action=f"/call/process-recording",
                method="POST"
            )

        elif call_status == "completed":
            # Call ended
            call_record = call_manager.end_call(call_sid)
            logger.info(f"Call completed: {json.dumps(call_record, indent=2)}")

        return str(response)

    except Exception as e:
        logger.error(f"Error handling inbound call: {e}")
        response = VoiceResponse()
        response.say("An error occurred. Please try again later.")
        return str(response), 500


@app.route("/call/process-recording", methods=["POST"])
def process_recording():
    """
    Process recorded audio from patient.
    This is where the agent processes the patient's message and responds.
    """
    try:
        call_sid = request.form.get("CallSid")
        recording_url = request.form.get("RecordingUrl")

        if not recording_url:
            logger.error("No recording URL received")
            response = VoiceResponse()
            response.say("We couldn't capture your message. Please try again.")
            return str(response)

        logger.info(f"Processing recording for call {call_sid}: {recording_url}")

        # In a real implementation, you would:
        # 1. Download the recording from recording_url
        # 2. Pass it to call_manager.process_patient_audio()
        # 3. Get agent response audio
        # 4. Stream it back to the caller

        # For now, return a simple response
        response = VoiceResponse()
        response.say("Thank you for your message. Our care team will review it shortly.")
        response.hangup()

        return str(response)

    except Exception as e:
        logger.error(f"Error processing recording: {e}")
        response = VoiceResponse()
        response.say("An error occurred processing your message.")
        return str(response), 500


@app.route("/call/status/<call_sid>", methods=["GET"])
def get_call_status(call_sid):
    """Get the status of an active call."""
    try:
        status = twilio_service.get_call_status(call_sid)
        if status:
            return jsonify(status), 200
        else:
            return jsonify({"error": "Call not found"}), 404
    except Exception as e:
        logger.error(f"Error getting call status: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/call/end/<call_sid>", methods=["POST"])
def end_call(call_sid):
    """Manually end a call."""
    try:
        call_record = call_manager.end_call(call_sid)
        return jsonify(call_record), 200
    except Exception as e:
        logger.error(f"Error ending call: {e}")
        return jsonify({"error": str(e)}), 500


def run_server(host: str = None, port: int = None, debug: bool = False):
    """Start the Flask voice server."""
    host = host or os.getenv("FLASK_HOST", "0.0.0.0")
    port = port or int(os.getenv("FLASK_PORT", "5000"))

    logger.info(f"Starting HCM Voice Server on {host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    run_server(debug=True)
