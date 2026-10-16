"""Test a full Clara call in the browser, typing as the patient. No phone and no ACS minutes.

Usage:
    clara-interactive-chat            # opens the test chat in your browser
    python -m hcm_agent.cli.interactive_chat   # the same, if Windows blocks the clara-* commands

The call runs through the same code as a phone call: identity verification, the conversation and
its tools, guardrails, emergency escalation and the live dashboard. Only the phone line is
replaced: you choose a member from the member data, type what the patient says, and Clara's
replies appear on the page (and can be read aloud). It needs the model settings in .env
(LLM_PROVIDER and its key) and nothing else. For a quick chat in the terminal, use clara-chat.
"""

import argparse
import threading
import webbrowser

from .. import config


def main() -> None:
    parser = argparse.ArgumentParser(description="Test a Clara call locally by typing as the patient.")
    parser.add_argument("--port", type=int, default=5050, help="Local port to serve the chat on (default: 5050)")
    parser.add_argument("--no-browser", action="store_true", help="Don't open the browser automatically")
    args = parser.parse_args()

    from ..telephony import server  # imported late: it reads the settings and builds the app

    url = f"http://127.0.0.1:{args.port}/live"
    print(f"Clara test chat: {url}   (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    try:
        server.run_local_chat(args.port)
    except config.ConfigError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
