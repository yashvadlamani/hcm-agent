#!/usr/bin/env python3
"""Make a test call using Vonage."""

import os
from dotenv import load_dotenv
from hcm_agent.vonage_service import VonageVoiceService

load_dotenv()


def make_vonage_call(to_number: str, patient_name: str = "Test Patient"):
    """Make a test call using Vonage."""

    try:
        service = VonageVoiceService()

        print(f"\n📞 Making Vonage voice call...")
        print(f"From: {service.phone_number}")
        print(f"To: {to_number}")
        print(f"Patient: {patient_name}\n")

        # Make the call
        call_uuid = service.make_call(to_number, patient_name)

        if call_uuid:
            print(f"✅ Call initiated successfully!")
            print(f"Call UUID: {call_uuid}")
            print(f"\nYou should receive a call at {to_number} shortly.")
            print(f"The agent will greet you with a test message.")
            return call_uuid
        else:
            print(f"❌ Failed to initiate call")
            return None

    except Exception as e:
        print(f"❌ Error: {e}")
        return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        phone = sys.argv[1]
    else:
        phone = input("Enter phone number to call (e.g., +1-469-588-4441): ").strip()
        if not phone:
            phone = "+1-469-588-4441"

    name = input("Patient name (press Enter for 'Test Patient'): ").strip()
    if not name:
        name = "Test Patient"

    make_vonage_call(phone, name)
