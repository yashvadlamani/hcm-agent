"""Lookup against an explicitly configured provider-directory snapshot."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_DIRECTORY = Path(__file__).resolve().parents[2] / "data" / "provider_directory.json"


def search_provider_directory(arguments: dict[str, Any]) -> dict[str, Any]:
    """Filter an active directory snapshot by LLM-extracted specialty and location."""
    directory = Path(os.environ.get("CLARA_PROVIDER_DIRECTORY_PATH", str(DEFAULT_DIRECTORY)))
    if not directory.is_file():
        return {"status": "not_configured", "options": [], "source": "provider_directory"}
    try:
        source = json.loads(directory.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "unavailable", "options": [], "source": "provider_directory"}
    if not isinstance(source, dict):
        return {"status": "unavailable", "options": [], "source": "provider_directory"}
    providers = source.get("providers", [])
    if source.get("source_status") != "active" or not isinstance(providers, list) or not providers:
        return {"status": "not_configured", "options": [], "source": "provider_directory"}

    specialty = str(arguments.get("specialty", "")).strip().casefold()
    city = str(arguments.get("city", "")).strip().casefold()
    area = str(arguments.get("area", "")).strip().casefold()
    state = str(arguments.get("state", "")).strip().casefold()
    provider_id = str(arguments.get("provider_id", "")).strip().casefold()
    accepting = arguments.get("accepting_new_patients")
    if not any((specialty, city, area, state, provider_id)):
        return {"status": "search_criteria_required", "options": [], "source": "provider_directory"}

    matches = []
    for provider in providers:
        if not isinstance(provider, dict) or provider.get("active") is not True:
            continue
        if provider_id and provider_id != str(provider.get("provider_id", "")).casefold():
            continue
        specialties = provider.get("specialties", [])
        specialties = specialties if isinstance(specialties, list) else []
        if specialty and not any(specialty in str(value).casefold() for value in specialties):
            continue
        if city and city not in str(provider.get("city", "")).casefold():
            continue
        if area and area not in str(provider.get("area", "")).casefold():
            continue
        if state and state != str(provider.get("state", "")).casefold():
            continue
        if isinstance(accepting, bool) and provider.get("accepting_new_patients") is not accepting:
            continue
        option = {key: provider[key] for key in (
            "provider_id", "display_name", "specialties", "area", "city", "state", "address",
            "rating", "rating_context", "is_fictional_demo", "phone", "accepting_new_patients",
        ) if key in provider}
        if option.get("is_fictional_demo") is True and option.get("accepting_new_patients") is True:
            # Local import avoids a module cycle: scheduling validates a selected directory entry.
            from .scheduling import next_available_demo_slots
            option["next_available_slots"] = next_available_demo_slots(option["provider_id"])
            option["availability_note"] = "Fictional demo weekday slots; not real clinic availability."
        matches.append(option)
        if len(matches) == 5:
            break
    return {"status": "results_found" if matches else "no_matches", "options": matches,
            "source": "provider_directory", "directory_note": source.get("directory_note"),
            "as_of": source.get("as_of")}
