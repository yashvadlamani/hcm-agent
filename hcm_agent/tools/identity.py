"""Deterministic identity comparisons; spoken answers never determine expected values."""

import re
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().replace("’", "'")
    value = re.sub(r"^(?:(?:yes|hello|hi)[,.]?\s+)?(?:my (?:full )?name is|this is|i am|i'm|it's)\s+", "", value)
    return " ".join(value.strip(" .!?,").split())


def verify_full_name(arguments: dict) -> dict:
    expected = normalize_name(str(arguments.get("expected_name", "")))
    provided = normalize_name(str(arguments.get("provided_name", "")))
    mode = arguments.get("match_type", "exact")
    if "spoken_answer" in arguments:
        spoken = normalize_name(arguments["spoken_answer"])
        if not provided or provided not in spoken:
            return {"verified": False, "match_type": "mismatch"}
    expected_parts, provided_parts = expected.split(), provided.split()
    matches = bool(expected_parts and provided_parts) and provided == expected
    if arguments.get("allow_first_name") and len(provided_parts) == 1 and expected_parts:
        matches = provided_parts[0] == expected_parts[0]
    if mode == "phonetic" and expected_parts and provided_parts:
        same_length = len(provided_parts) == len(expected_parts)
        first_only = arguments.get("allow_first_name") and len(provided_parts) == 1
        matches = bool(same_length or first_only) and all(
            a[:1] == b[:1] and SequenceMatcher(None, a, b).ratio() >= 0.75
            for a, b in zip(provided_parts, expected_parts)
        )
    return {"verified": matches and mode != "mismatch", "match_type": mode}


def normalize_dob(value: str) -> str | None:
    """Accept complete ASR numeric/month-name dates; never infer a missing year."""
    value = value.strip().lower().rstrip(".! ")
    value = re.sub(r"^(?:my (?:date of birth|birthday|dob) is|i was born on|it's|it is)\s+", "", value)
    value = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", value)
    value = " ".join(value.replace(",", " ").split())
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m %d %Y", "%B %d %Y", "%b %d %Y", "%d %B %Y"):
        try:
            parsed = datetime.strptime(value, fmt).date()
        except ValueError:
            continue
        if 1900 <= parsed.year and parsed <= date.today():
            return parsed.isoformat()
    return None


def verify_dob(arguments: dict) -> dict:
    expected = normalize_dob(str(arguments.get("expected_dob", "")))
    provided = normalize_dob(str(arguments.get("provided_dob", "")))
    return {"verified": expected is not None and provided == expected, "assurance": "knowledge_based"}
