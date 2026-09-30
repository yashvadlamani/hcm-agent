"""Place an outbound Twilio call that talks to the Clara phone server.

Usage:
    clara-call --url https://<your-app>.azurewebsites.net --to +1XXXXXXXXXX --name <FirstName>
"""

import argparse

from .. import config
from ..telephony.outbound import CallNotAllowed, place_call


def main() -> None:
    parser = argparse.ArgumentParser(description="Call a patient and connect them to Clara.")
    parser.add_argument("--url", help="The app's public https address, e.g. https://<your-app>.azurewebsites.net "
                                       "(defaults to CLARA_BASE_URL)")
    parser.add_argument("--to", required=True, help="Number to call (must be verified on a trial account)")
    parser.add_argument("--name", default="there", help="Patient's first name for the greeting")
    args = parser.parse_args()

    settings = config.load()
    base_url = args.url or settings.clara_base_url
    problems = config.call_problems(settings)
    if not base_url:
        problems.append("Pass --url or set CLARA_BASE_URL")
    try:
        config.require(problems)
        sid = place_call(settings, base_url, args.to, args.name,
                         on_wait=lambda: print("Waking the server (this can take up to a minute)..."))
    except (config.ConfigError, CallNotAllowed, TimeoutError) as e:
        raise SystemExit(str(e))
    print(f"Calling {args.to} ... (call SID {sid})")


if __name__ == "__main__":
    main()
