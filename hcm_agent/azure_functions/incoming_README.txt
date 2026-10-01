Upload call requests to this folder: one .json file per call. Each file is picked up within
seconds and moved to processed/ (call placed) or failed/ (with the reason).

Example request.json:

  {
    "to": "+1XXXXXXXXXX",
    "name": "Yash",
    "risk_drivers": ["HbA1c above 7.5% at last check"]
  }

Only "to" is required. Up to 5 risk drivers, each at most 100 characters. Only numbers in
ALLOWED_CALL_NUMBERS are called.

This README keeps the incoming/ folder visible. Leave it here; it never triggers a call.
