"""The reasons Clara calls: the "for" field of a call request.

Kept free of other imports so the call-request Azure Function can use it without the model libraries.
"""

import re
from dataclasses import dataclass
from typing import Optional

DEFAULT_CALL_REASON = "diabetes management"
MAX_REASON_CHARS = 60


@dataclass(frozen=True)
class CallReason:
    """Why the care team asked for the call: the "for" field of a call request."""
    label: str     # the care team's name for it, e.g. "likelihood of high cost" (never said to the patient)
    purpose: str   # how Clara tells the patient why she's calling: "I'm calling to <purpose>."
    question: str  # her first question once the patient is on the line
    focus: str     # what the model should explore on the call


# Known reasons get wording written for patients. The label is the care team's own term and can be
# blunt ("likelihood of high cost"), so Clara never says it: she says the purpose instead.
CALL_REASONS = {reason.label: reason for reason in (
    CallReason(
        "diabetes management",
        "check in on how you're doing with your diabetes management",
        "How have you been feeling lately?",
        "Understand how managing their diabetes is going day to day and what gets in the way: medication "
        "and refills, checking blood sugar, appointments, cost, food, stress or support at home."),
    CallReason(
        "likelihood of high cost",
        "check in on your health and see whether anything is making it harder to get the care you need",
        "How have things been going for you lately?",
        "The care team expects this patient may soon need a lot of costly care (emergency visits, hospital "
        "stays, conditions getting worse). Understand what is behind that: trouble affording medication or "
        "visits, not having a regular doctor, transport, using the emergency room for routine care, or "
        "feeling overwhelmed. Never mention cost predictions, risk or scores, or suggest they cost too much."),
    CallReason(
        "medication adherence",
        "check in on how things are going with your medications",
        "How has it been going keeping up with them?",
        "Understand whether they are able to take their medications as prescribed and what gets in the way: "
        "cost, refills and pharmacy access, side effects, a confusing schedule, forgetting, or doubts about "
        "needing them. Side effects and doubts go to their doctor or pharmacist."),
    CallReason(
        "readmission risk",
        "check in on how you've been doing since your recent hospital stay",
        "How have you been feeling since you got home?",
        "The patient was recently in hospital and could end up back there. Understand how recovery is going: "
        "whether they understood their discharge instructions, have their medications, have a follow-up "
        "visit booked, and have help at home. Never mention readmission or risk."),
    CallReason(
        "care gaps",
        "check in about some routine checkups and screenings that may be due",
        "How have you been doing lately?",
        "The patient is overdue for routine care such as checkups, screenings or lab tests. Understand what "
        "has kept them from getting it: cost, transport, time, not knowing it was due, or worry about it."),
)}
ALIASES = {
    "diabetes": "diabetes management", "diabetes care": "diabetes management",
    "high cost": "likelihood of high cost", "high cost risk": "likelihood of high cost",
    "likelihood of high costs": "likelihood of high cost",
    "medication non adherence": "medication adherence", "medication nonadherence": "medication adherence",
    "readmission": "readmission risk", "hospital readmission": "readmission risk",
    "likelihood of readmission": "readmission risk",
    "care gap": "care gaps", "gaps in care": "care gaps", "preventive care": "care gaps",
}


def call_reason(value: Optional[str] = None) -> CallReason:
    """The reason for a call, from a request's "for" value. Without one, it's diabetes management.

    A value that isn't in CALL_REASONS still works: Clara opens with a general check-in and the
    model is told the care team's reason."""
    label = re.sub(r"[\s_-]+", " ", value or "").strip()[:MAX_REASON_CHARS]
    key = label.lower()
    key = ALIASES.get(key, key)
    if not key:
        return CALL_REASONS[DEFAULT_CALL_REASON]
    if key in CALL_REASONS:
        return CALL_REASONS[key]
    return CallReason(
        label,
        "check in on how you're doing with your health",
        "How have you been feeling lately?",
        "Understand how the patient is doing in this area and what is getting in the way of their care: "
        "cost, access, medication, appointments, stress or support at home.")
