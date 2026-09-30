"""Place an outbound Twilio call that talks to the Clara phone server.

Usage:
    python -m hcm_agent.place_call --url https://<ngrok-or-azure-address> --to +1XXXXXXXXXX --name <FirstName>
"""

import argparse
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

WAKE_TIMEOUT_SECONDS = 120


def to_e164(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 10:
        digits = "1" + digits
    return "+" + digits


def wake_server(base_url: str) -> None:
    """Wait until the server answers, so a sleeping host (e.g. Azure Free tier) is awake
    before Twilio's first webhook, which a trial account gives only ~5 seconds."""
    deadline = time.monotonic() + WAKE_TIMEOUT_SECONDS
    announced = False
    while True:
        try:
            with urllib.request.urlopen(base_url, timeout=15) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        if time.monotonic() > deadline:
            raise SystemExit(f"{base_url} didn't respond within {WAKE_TIMEOUT_SECONDS}s. Is the server running?")
        if not announced:
            print("Waking the server (this can take up to a minute)...")
            announced = True
        time.sleep(3)


def main():
    parser = argparse.ArgumentParser(description="Call a patient and connect them to Clara.")
    parser.add_argument("--url", required=True, help="Public https base URL (ngrok or Azure)")
    parser.add_argument("--to", required=True, help="Number to call (must be verified on a trial account)")
    parser.add_argument("--name", default="there", help="Patient's first name for the greeting")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    wake_server(base_url + "/")

    client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
    key = os.environ["PHONE_WEBHOOK_KEY"]
    webhook = f"{base_url}/t/{key}/voice?{urlencode({'name': args.name})}"

    # Trial accounts reject any call parameters beyond to/from/url.
    call = client.calls.create(
        to=to_e164(args.to),
        from_=to_e164(os.environ["TWILIO_PHONE_NUMBER"]),
        url=webhook,
    )
    print(f"Calling {args.to} ... (call SID {call.sid}, status {call.status})")


if __name__ == "__main__":
    main()
