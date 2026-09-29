#!/usr/bin/env python3
"""Place an outbound Twilio call that talks to the Guppy phone server.

Usage:
    python phone_call.py --url https://<your-ngrok-domain> --to +17044305315 --name Yash
"""

import argparse
import os
from urllib.parse import urlencode

from dotenv import load_dotenv
from twilio.rest import Client

from simple_call import to_e164

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Call a patient and connect them to Guppy.")
    parser.add_argument("--url", required=True, help="Public https base URL from ngrok")
    parser.add_argument("--to", required=True, help="Number to call (must be verified on a trial account)")
    parser.add_argument("--name", default="there", help="Patient's first name for the greeting")
    args = parser.parse_args()

    client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
    key = os.environ["PHONE_WEBHOOK_KEY"]
    webhook = f"{args.url.rstrip('/')}/t/{key}/voice?{urlencode({'name': args.name})}"

    # Trial accounts reject any call parameters beyond to/from/url.
    call = client.calls.create(
        to=to_e164(args.to),
        from_=to_e164(os.environ["TWILIO_PHONE_NUMBER"]),
        url=webhook,
    )
    print(f"Calling {args.to} ... (call SID {call.sid}, status {call.status})")


if __name__ == "__main__":
    main()
