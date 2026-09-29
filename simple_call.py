#!/usr/bin/env python3
"""Simple test call without webhooks - works with Twilio trial accounts."""

import os
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

load_dotenv()

def to_e164(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 10:
        digits = "1" + digits
    return "+" + digits


def make_simple_call(to_number: str, patient_name: str = "Test Patient"):
    """Make a simple call with basic TwiML (no webhooks needed)."""

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_PHONE_NUMBER")

    if not all([account_sid, auth_token, from_number]):
        print("❌ Error: Twilio credentials missing in .env")
        return

    client = Client(account_sid, auth_token)
    to_number = to_e164(to_number)
    from_number = to_e164(from_number)

    try:
        print(f"\n📞 Making test call...")
        print(f"From: {from_number}")
        print(f"To: {to_number}")
        print(f"Patient: {patient_name}\n")

        # Create a simple TwiML response
        response = VoiceResponse()
        response.say(f"Hi {patient_name}, this is Guppy, a virtual assistant from your health insurance care team. I'm calling to check in on how you're doing with your diabetes management. This is a test call, so you can hang up now. Goodbye!", voice="alice")

        # Make the call with TwiML (no webhook URL needed)
        call = client.calls.create(
            to=to_number,
            from_=from_number,
            twiml=str(response)
        )

        print(f"✅ Call initiated successfully!")
        print(f"Call SID: {call.sid}")
        print(f"Status: {call.status}")
        print(f"\nYou should receive a call at {to_number} shortly.")

        return call.sid

    except Exception as e:
        print(f"❌ Failed to make call:")
        print(f"Error: {e}")
        return None


if __name__ == "__main__":
    import sys

    phone = input("Enter phone number to call (e.g., +1-704-430-5315): ").strip()
    if not phone:
        phone = "+1-704-430-5315"

    name = input("Patient name (press Enter for 'Test Patient'): ").strip()
    if not name:
        name = "Test Patient"

    make_simple_call(phone, name)
