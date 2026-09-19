"""Vonage (Nexmo) integration for phone calls."""

import os
import logging
import requests

logger = logging.getLogger(__name__)


class VonageVoiceService:
    """
    Vonage integration for making voice calls using REST API.

    Vonage (formerly Nexmo) provides affordable voice infrastructure
    with a free tier for testing.
    """

    def __init__(self, api_key: str = None, api_secret: str = None, phone_number: str = None):
        self.api_key = api_key or os.getenv("VONAGE_API_KEY")
        self.api_secret = api_secret or os.getenv("VONAGE_API_SECRET")
        self.phone_number = phone_number or os.getenv("VONAGE_PHONE_NUMBER")

        if not all([self.api_key, self.api_secret, self.phone_number]):
            raise ValueError("Vonage credentials not configured. Check .env file.")

        logger.info("Vonage voice service initialized")

    def make_call(self, to_number: str, patient_name: str = "Patient") -> str:
        """
        Make an outbound call to a patient.

        Args:
            to_number: Phone number to call (e.g., "+1-469-588-4441")
            patient_name: Patient's name for greeting

        Returns:
            Call UUID for tracking
        """
        try:
            # Format phone numbers
            to_number = self._format_phone(to_number)
            from_number = self._format_phone(self.phone_number)

            logger.info(f"Making call from {from_number} to {to_number}")

            # Vonage Voice API endpoint
            url = "https://api.vonage.com/v1/calls"

            # NCCO (Nexmo Call Control Objects) - defines the call flow
            ncco = [
                {
                    "action": "talk",
                    "text": f"Hello {patient_name}, this is a call from the Healthcare Management Voice Agent. Thank you for answering. You can now hang up.",
                    "language": "en-US",
                    "style": 1
                }
            ]

            headers = {
                "Content-Type": "application/json"
            }

            # Use simpler query parameter authentication
            params = {
                "api_key": self.api_key,
                "api_secret": self.api_secret
            }

            payload = {
                "to": [{"type": "phone", "number": to_number}],
                "from": {"type": "phone", "number": from_number},
                "ncco": ncco
            }

            response = requests.post(url, json=payload, headers=headers, params=params, timeout=10)

            if response.status_code in [200, 201]:
                data = response.json()
                if "uuid" in data:
                    call_uuid = data["uuid"]
                    logger.info(f"Call initiated. UUID: {call_uuid}")
                    return call_uuid
                else:
                    logger.error(f"No UUID in response: {data}")
                    return None
            else:
                logger.error(f"Vonage API error: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Failed to make call: {e}")
            raise

    def _format_phone(self, phone: str) -> str:
        """Format phone number for Vonage (remove dashes, add +1 if US number)."""
        # Remove dashes and spaces
        phone = phone.replace("-", "").replace(" ", "").replace("(", "").replace(")", "")

        # Add +1 if 10-digit US number
        if len(phone) == 10 and not phone.startswith("+"):
            phone = "+1" + phone
        elif len(phone) == 11 and phone.startswith("1") and not phone.startswith("+"):
            phone = "+" + phone
        elif not phone.startswith("+"):
            phone = "+" + phone

        return phone

    def get_call_status(self, call_uuid: str) -> dict:
        """Get the status of a call."""
        try:
            url = f"https://api.vonage.com/v1/calls/{call_uuid}"
            params = {
                "api_key": self.api_key,
                "api_secret": self.api_secret
            }

            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get call status: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Failed to get call status: {e}")
            return None

    def hangup_call(self, call_uuid: str) -> bool:
        """Hangup an active call."""
        try:
            url = f"https://api.vonage.com/v1/calls/{call_uuid}"
            params = {
                "api_key": self.api_key,
                "api_secret": self.api_secret
            }

            payload = {"action": "hangup"}

            response = requests.put(url, json=payload, params=params, timeout=10)

            if response.status_code in [200, 204]:
                logger.info(f"Call {call_uuid} hung up")
                return True
            else:
                logger.error(f"Failed to hangup call: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"Failed to hangup call: {e}")
            return False
