#!/usr/bin/env python3
"""
Make a real voice call using Twilio.

This script will initiate an actual phone call to a patient using Twilio.
The agent will conduct the conversation via voice.
"""

import os
import sys
import requests
import json
from dotenv import load_dotenv

load_dotenv()


def make_real_call(to_number: str, patient_name: str = None, risk_drivers: list = None):
    """
    Make a real outbound call to a patient.

    Args:
        to_number: Patient phone number (e.g., "+1-704-430-5315")
        patient_name: Patient's name
        risk_drivers: List of health risk drivers
    """

    # Validate Twilio is configured
    if not os.getenv("TWILIO_ACCOUNT_SID"):
        print("❌ Error: Twilio not configured")
        print("Please add your Twilio credentials to .env file:")
        print("  TWILIO_ACCOUNT_SID")
        print("  TWILIO_AUTH_TOKEN")
        print("  TWILIO_PHONE_NUMBER")
        return

    if not os.getenv("TWILIO_PHONE_NUMBER"):
        print("❌ Error: TWILIO_PHONE_NUMBER not set in .env")
        return

    # Build request
    server_url = os.getenv("VOICE_SERVER_URL", "http://localhost:5000")
    endpoint = f"{server_url}/call/initiate"

    payload = {
        "to_number": to_number,
        "patient_context": {
            "name": patient_name or "Valued Patient",
            "risk_drivers": risk_drivers or [
                "HbA1c > 7.5%",
                "Blood pressure elevated",
                "Medication non-adherence"
            ]
        }
    }

    try:
        print(f"\n📞 Initiating voice call...")
        print(f"To: {to_number}")
        print(f"Patient: {payload['patient_context']['name']}")
        print(f"Risk Drivers: {', '.join(payload['patient_context']['risk_drivers'])}")
        print(f"\nCalling Twilio at {endpoint}...\n")

        response = requests.post(endpoint, json=payload, timeout=10)

        if response.status_code == 200:
            result = response.json()
            print(f"✅ Call initiated successfully!")
            print(f"\nCall Details:")
            print(f"  Call SID: {result['call_sid']}")
            print(f"  Status: {result['status']}")
            print(f"  To: {result['to_number']}")
            print(f"\nThe patient should receive a call momentarily.")
            print(f"Call SID: {result['call_sid']}")

            # Offer to check status
            print(f"\nTo check call status later, use:")
            print(f"  python make_call.py --status {result['call_sid']}")

            return result['call_sid']

        else:
            print(f"❌ Failed to initiate call")
            print(f"Status: {response.status_code}")
            print(f"Response: {response.text}")
            return None

    except requests.exceptions.ConnectionError:
        print(f"❌ Could not connect to voice server at {server_url}")
        print(f"\nMake sure the server is running:")
        print(f"  python -m hcm_agent.voice_server")
        return None

    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def check_call_status(call_sid: str):
    """Check the status of an active call."""
    server_url = os.getenv("VOICE_SERVER_URL", "http://localhost:5000")
    endpoint = f"{server_url}/call/status/{call_sid}"

    try:
        response = requests.get(endpoint, timeout=5)

        if response.status_code == 200:
            status = response.json()
            print(f"\n📊 Call Status:")
            print(f"  SID: {status['sid']}")
            print(f"  Status: {status['status']}")
            print(f"  Duration: {status['duration']} seconds")
            print(f"  Start Time: {status['start_time']}")
            print(f"  End Time: {status['end_time']}")
            print(f"  Price: {status['price']}")
            return status
        else:
            print(f"❌ Call not found: {call_sid}")
            return None

    except Exception as e:
        print(f"❌ Error checking call status: {e}")
        return None


def main():
    """Main CLI."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Make a real voice call to a patient using HCM Voice Agent"
    )

    parser.add_argument(
        "--phone",
        help="Phone number to call (e.g., +1-704-430-5315)",
        default=None
    )
    parser.add_argument(
        "--name",
        help="Patient name",
        default=None
    )
    parser.add_argument(
        "--drivers",
        help="Risk drivers (comma-separated)",
        default=None
    )
    parser.add_argument(
        "--status",
        help="Check status of a call by SID",
        default=None
    )
    parser.add_argument(
        "--demo",
        help="Use demo phone number",
        action="store_true"
    )

    args = parser.parse_args()

    if args.status:
        check_call_status(args.status)
        return

    phone = args.phone
    if args.demo:
        phone = "+1-704-430-5315"

    if not phone:
        phone = input("Enter phone number to call (e.g., +1-704-430-5315): ").strip()

    if not phone.startswith("+"):
        phone = f"+1{phone.replace('-', '').replace(' ', '')}"

    patient_name = args.name or input("Patient name (press Enter for default): ").strip()

    risk_drivers = None
    if args.drivers:
        risk_drivers = [d.strip() for d in args.drivers.split(",")]

    # Make the call
    call_sid = make_real_call(phone, patient_name or None, risk_drivers)

    if call_sid:
        print(f"\n✅ Call initiated with SID: {call_sid}")


if __name__ == "__main__":
    main()
