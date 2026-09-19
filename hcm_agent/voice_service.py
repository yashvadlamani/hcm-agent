"""Real voice infrastructure integration with Twilio, Deepgram, and ElevenLabs."""

import os
import logging
from typing import Optional
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
from deepgram import DeepgramClient, PrerecordedOptions
from elevenlabs import ElevenLabs, VoiceSettings

logger = logging.getLogger(__name__)


class TwilioVoiceService:
    """
    Twilio integration for phone calls.

    ⚠️ IMPORTANT: This implementation uses Twilio's standard service.
    For production with PHI/HIPAA data, you MUST upgrade to:
    - Twilio HIPAA-compliant service: https://www.twilio.com/en-us/solutions/healthcare
    - Ensure Business Associate Agreement (BAA) is in place
    - Enable HIPAA-compliant encryption (TLS 1.2+, AES-256)
    - Set up audit logging for all calls
    """

    def __init__(self, account_sid: str = None, auth_token: str = None, phone_number: str = None):
        self.account_sid = account_sid or os.getenv("TWILIO_ACCOUNT_SID")
        self.auth_token = auth_token or os.getenv("TWILIO_AUTH_TOKEN")
        self.phone_number = phone_number or os.getenv("TWILIO_PHONE_NUMBER")

        if not all([self.account_sid, self.auth_token, self.phone_number]):
            raise ValueError("Twilio credentials not configured. Check .env file.")

        self.client = Client(self.account_sid, self.auth_token)
        logger.info("Twilio service initialized")

    def make_call(self, to_number: str, patient_context: dict, webhook_url: str) -> str:
        """
        Make an outbound call to a patient.

        Args:
            to_number: Phone number to call (e.g., "+1-704-430-5315")
            patient_context: Patient information dict
            webhook_url: URL for Twilio to send events to

        Returns:
            Call SID for tracking
        """
        try:
            call = self.client.calls.create(
                to=to_number,
                from_=self.phone_number,
                url=webhook_url,
                method="POST",
                record=True,  # Record all calls for compliance
                record_track="both"  # Record both inbound and outbound
            )

            logger.info(f"Call initiated to {to_number}. Call SID: {call.sid}")
            return call.sid

        except Exception as e:
            logger.error(f"Failed to make call: {e}")
            raise

    def get_voice_response_for_greeting(self, patient_name: str) -> str:
        """Generate TwiML for initial call greeting."""
        response = VoiceResponse()

        greeting = f"Hi {patient_name}, this is a call from your healthcare provider. "
        greeting += "Please listen for my message."

        response.say(greeting, voice="alice")
        response.gather(
            num_digits=1,
            action="",  # Will be replaced with actual webhook
            method="POST",
            timeout=10
        )

        return str(response)

    def get_call_status(self, call_sid: str) -> dict:
        """Get the status of a call."""
        try:
            call = self.client.calls(call_sid).fetch()
            return {
                "sid": call.sid,
                "status": call.status,
                "duration": call.duration,
                "start_time": call.start_time,
                "end_time": call.end_time,
                "price": call.price,
            }
        except Exception as e:
            logger.error(f"Failed to get call status: {e}")
            return None


class DeepgramASRService:
    """
    Deepgram integration for speech-to-text.
    Converts audio streams to text for processing by the agent.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("DEEPGRAM_API_KEY")
        if not self.api_key:
            raise ValueError("Deepgram API key not configured. Check .env file.")

        self.client = DeepgramClient(api_key=self.api_key)
        logger.info("Deepgram ASR service initialized")

    async def transcribe_audio(self, audio_data: bytes, mimetype: str = "audio/wav") -> str:
        """
        Transcribe audio to text.

        Args:
            audio_data: Raw audio bytes
            mimetype: Audio format (audio/wav, audio/mp3, etc.)

        Returns:
            Transcribed text
        """
        try:
            options = PrerecordedOptions(
                model="nova-2",
                language="en",
                punctuate=True,
                paragraphs=True
            )

            # Note: This is a simplified example. In production, you'd use streaming
            response = await self.client.transcription.prerecorded(
                {"buffer": audio_data, "mimetype": mimetype},
                options
            )

            if response and response.get("results"):
                transcript = response["results"]["channels"][0]["alternatives"][0]["transcript"]
                return transcript

            return ""

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return ""


class ElevenLabsTTSService:
    """
    ElevenLabs integration for text-to-speech.
    Converts agent responses to natural-sounding audio.
    """

    def __init__(self, api_key: str = None, voice_id: str = None):
        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY")
        self.voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

        if not self.api_key:
            raise ValueError("ElevenLabs API key not configured. Check .env file.")

        self.client = ElevenLabs(api_key=self.api_key)
        logger.info("ElevenLabs TTS service initialized")

    def synthesize_speech(self, text: str) -> bytes:
        """
        Convert text to speech audio.

        Args:
            text: Text to synthesize

        Returns:
            Audio bytes (WAV format)
        """
        try:
            audio = self.client.generate(
                text=text,
                voice=self.voice_id,
                model="eleven_monolingual_v1"
            )

            return b"".join(audio)

        except Exception as e:
            logger.error(f"Speech synthesis failed: {e}")
            return b""

    def get_voice_settings(self) -> VoiceSettings:
        """Get current voice settings."""
        return VoiceSettings(
            stability=0.5,
            similarity_boost=0.75
        )


class VoiceCallManager:
    """
    Orchestrates the complete voice call flow:
    1. Twilio initiates call
    2. Patient speaks (audio captured)
    3. Deepgram transcribes
    4. Agent processes and responds
    5. ElevenLabs synthesizes response
    6. Patient hears response
    """

    def __init__(self, agent, twilio_service: TwilioVoiceService,
                 deepgram_service: DeepgramASRService,
                 elevenlabs_service: ElevenLabsTTSService):
        self.agent = agent
        self.twilio = twilio_service
        self.deepgram = deepgram_service
        self.elevenlabs = elevenlabs_service
        self.active_calls = {}
        logger.info("Voice call manager initialized")

    def initiate_outbound_call(self, to_number: str, patient_context: dict, webhook_url: str) -> str:
        """Initiate an outbound call to a patient."""
        call_sid = self.twilio.make_call(to_number, patient_context, webhook_url)

        self.active_calls[call_sid] = {
            "patient": patient_context,
            "start_time": None,
            "transcript": [],
            "status": "initiated"
        }

        # Initialize agent for this call
        self.agent.initialize_call(patient_context)

        return call_sid

    async def process_patient_audio(self, call_sid: str, audio_data: bytes) -> str:
        """
        Process patient audio: transcribe → get agent response → synthesize.

        Returns:
            Audio bytes of agent response
        """
        if call_sid not in self.active_calls:
            logger.error(f"Unknown call SID: {call_sid}")
            return b""

        try:
            # Step 1: Transcribe patient audio
            patient_text = await self.deepgram.transcribe_audio(audio_data)
            logger.info(f"Patient said: {patient_text}")

            # Step 2: Get agent response
            agent_response = self.agent.generate_response(patient_text)
            logger.info(f"Agent responds: {agent_response}")

            # Step 3: Synthesize agent response
            response_audio = self.elevenlabs.synthesize_speech(agent_response)

            # Step 4: Track in call record
            self.active_calls[call_sid]["transcript"].append({
                "role": "patient",
                "text": patient_text
            })
            self.active_calls[call_sid]["transcript"].append({
                "role": "agent",
                "text": agent_response
            })

            return response_audio

        except Exception as e:
            logger.error(f"Error processing patient audio: {e}")
            fallback_response = "I'm having trouble processing that. Could you say that again?"
            return self.elevenlabs.synthesize_speech(fallback_response)

    def end_call(self, call_sid: str) -> dict:
        """End call and get summary."""
        if call_sid not in self.active_calls:
            return {}

        call_record = self.active_calls.pop(call_sid)
        summary = self.agent.end_call()

        call_record["summary"] = summary
        logger.info(f"Call {call_sid} ended. Summary: {summary}")

        return call_record
