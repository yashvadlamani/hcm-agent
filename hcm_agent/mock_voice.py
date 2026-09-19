"""Mock voice interface for testing without real voice infrastructure."""

import json
from typing import Dict, Any


class MockVoiceInterface:
    """Simulates voice call interface for testing."""

    def __init__(self, agent):
        self.agent = agent

    def start_call(self, patient_context: Dict[str, Any]):
        """Start a simulated voice call."""
        self.agent.initialize_call(patient_context)
        print("\n" + "="*70)
        print(f"📞 VOICE CALL STARTED")
        print(f"Patient: {patient_context.get('name', 'Unknown')}")
        print(f"Risk Drivers: {', '.join(patient_context.get('risk_drivers', []))}")
        print("="*70 + "\n")

    def send_message(self, message: str):
        """Send patient message and get agent response."""
        print(f"🗣️  Patient: {message}")
        response = self.agent.generate_response(message)
        print(f"🤖 Agent: {response}\n")
        return response

    def end_call(self):
        """End call and display summary."""
        summary = self.agent.end_call()

        print("\n" + "="*70)
        print("📊 CALL SUMMARY")
        print("="*70)
        print(f"Patient: {summary['patient']}")
        print(f"Call Duration: {summary['call_duration_turns']} turns")
        print(f"Emergency Detected: {summary['emergency_detected']}")
        print(f"Escalation Reason: {summary['escalation_reason']}")
        print(f"Requires Care Manager Followup: {summary['requires_care_manager_followup']}")
        print("\n📋 TRANSCRIPT:")
        print(self.agent.get_conversation_transcript())
        print("="*70 + "\n")

        return summary


def run_interactive_call(agent):
    """Run an interactive voice call session."""
    print("\n🏥 HCM VOICE AGENT - INTERACTIVE TEST\n")

    # Get patient info
    patient_name = input("Patient name: ").strip() or "John Smith"
    risk_drivers = input("Risk drivers (comma-separated): ").strip()
    risk_drivers = [d.strip() for d in risk_drivers.split(",")] if risk_drivers else ["HbA1c > 7.5%", "Blood pressure elevated"]

    patient_context = {
        "name": patient_name,
        "risk_drivers": risk_drivers
    }

    # Start call
    voice = MockVoiceInterface(agent)
    voice.start_call(patient_context)

    # Interactive conversation
    print("Type 'end' to finish the call.\n")
    while True:
        message = input("You: ").strip()

        if message.lower() == "end":
            break

        if message:
            voice.send_message(message)

    # End call
    return voice.end_call()
