"""In-memory weekday availability and booking simulation for the fictional provider directory."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from threading import Lock
from zoneinfo import ZoneInfo

from .providers import search_provider_directory

DEMO_TIMEZONE = ZoneInfo("America/Chicago")
DEMO_SLOT_TIMES = ("09:00", "10:00", "11:00", "13:00", "14:00", "15:00")
MAX_DEMO_APPOINTMENTS = 100
DEMO_APPOINTMENTS: list[dict] = []
_APPOINTMENT_LOCK = Lock()


def _current_time(now: datetime | None) -> datetime:
    current = now or datetime.now(DEMO_TIMEZONE)
    return current.replace(tzinfo=DEMO_TIMEZONE) if current.tzinfo is None else current.astimezone(DEMO_TIMEZONE)


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _parse_time(value: str) -> time | None:
    try:
        parsed = time.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.second == 0 and parsed.tzinfo is None else None


def _slot_options(provider_id: str, start_date: date, current: datetime, *,
                  preferred_time: str | None = None, after_time: str | None = None,
                  limit: int = 3) -> list[dict]:
    booked = {
        (item["provider_id"], item["date"], item["time"])
        for item in DEMO_APPOINTMENTS
    }
    options = []
    for offset in range(61):
        slot_date = start_date + timedelta(days=offset)
        if slot_date.weekday() >= 5:
            continue
        times = (preferred_time,) if preferred_time in DEMO_SLOT_TIMES else DEMO_SLOT_TIMES
        for slot_time in times:
            if slot_date == start_date and after_time and slot_time <= after_time:
                continue
            slot_dt = datetime.combine(slot_date, time.fromisoformat(slot_time), DEMO_TIMEZONE)
            if slot_dt <= current or (provider_id, slot_date.isoformat(), slot_time) in booked:
                continue
            options.append({
                "date": slot_date.isoformat(),
                "day": slot_date.strftime("%A"),
                "time": slot_time,
                "timezone": "America/Chicago",
            })
            if len(options) >= limit:
                return options
    return options


def next_available_demo_slots(provider_id: str, *, now: datetime | None = None, limit: int = 3) -> list[dict]:
    """Return the next bookable fictional slots so directory results can answer availability directly."""
    current = _current_time(now)
    with _APPOINTMENT_LOCK:
        return _slot_options(provider_id, current.date(), current, limit=limit)


def request_demo_appointment(arguments: dict, *, now: datetime | None = None) -> dict:
    """Offer or book one of the fictional provider's free weekday demo slots."""
    provider_id = str(arguments.get("provider_id", "")).strip()[:100]
    requested_date_text = str(arguments.get("requested_date", "")).strip()
    requested_time_text = str(arguments.get("requested_time", "")).strip()
    if not provider_id:
        return {"scheduled": False, "status": "needs_provider", "appointment_options": []}

    provider_result = search_provider_directory({"provider_id": provider_id})
    if provider_result.get("status") != "results_found":
        return {"scheduled": False, "status": "provider_not_found", "appointment_options": []}
    provider = provider_result["options"][0]
    if provider.get("is_fictional_demo") is not True:
        return {"scheduled": False, "status": "provider_not_in_demo_schedule", "appointment_options": []}
    if provider.get("accepting_new_patients") is False:
        return {"scheduled": False, "status": "not_accepting_new_patients", "provider": provider,
                "appointment_options": []}

    current = _current_time(now)
    requested_date = _parse_date(requested_date_text) if requested_date_text else None
    requested_time = _parse_time(requested_time_text) if requested_time_text else None
    if requested_date_text and requested_date is None:
        return {"scheduled": False, "status": "invalid_date", "appointment_options": []}
    if requested_time_text and requested_time is None:
        return {"scheduled": False, "status": "invalid_time", "appointment_options": []}

    # With no date, offer the nearest options instead of silently choosing a date for the caller.
    if requested_date is None:
        options = _slot_options(provider_id, current.date(), current,
                                preferred_time=requested_time.strftime("%H:%M") if requested_time else None)
        return {"scheduled": False, "status": "slots_offered", "provider": provider,
                "appointment_options": options, "demo_only": True}

    if requested_date < current.date():
        return {"scheduled": False, "status": "date_in_past", "provider": provider,
                "appointment_options": _slot_options(provider_id, current.date(), current,
                    preferred_time=requested_time.strftime("%H:%M") if requested_time else None), "demo_only": True}

    if requested_date.weekday() >= 5:
        # If a valid time was requested, prefer offering that time on future weekdays.
        options = _slot_options(provider_id, requested_date + timedelta(days=1), current,
                                preferred_time=requested_time.strftime("%H:%M") if requested_time else None)
        return {"scheduled": False, "status": "closed_weekends", "provider": provider,
                "requested_date": requested_date.isoformat(), "appointment_options": options,
                "demo_only": True}

    if requested_time is None:
        options = _slot_options(provider_id, requested_date, current)
        return {"scheduled": False, "status": "slots_offered", "provider": provider,
                "requested_date": requested_date.isoformat(), "appointment_options": options,
                "demo_only": True}

    slot_time = requested_time.strftime("%H:%M")
    if slot_time not in DEMO_SLOT_TIMES:
        return {"scheduled": False, "status": "time_unavailable", "provider": provider,
                "requested_date": requested_date.isoformat(),
                "appointment_options": _slot_options(provider_id, requested_date, current,
                    after_time=slot_time),
                "demo_only": True}

    requested_slot = datetime.combine(requested_date, requested_time, DEMO_TIMEZONE)
    if requested_slot <= current:
        return {"scheduled": False, "status": "slot_in_past", "provider": provider,
                "requested_date": requested_date.isoformat(),
                "appointment_options": _slot_options(provider_id, current.date(), current,
                    preferred_time=slot_time), "demo_only": True}

    with _APPOINTMENT_LOCK:
        if any(item["provider_id"] == provider_id and item["date"] == requested_date.isoformat()
               and item["time"] == slot_time for item in DEMO_APPOINTMENTS):
            options = _slot_options(provider_id, requested_date, current, after_time=slot_time)
            return {"scheduled": False, "status": "slot_unavailable", "provider": provider,
                    "requested_date": requested_date.isoformat(), "appointment_options": options,
                    "demo_only": True}
        if len(DEMO_APPOINTMENTS) >= MAX_DEMO_APPOINTMENTS:
            return {"scheduled": False, "status": "demo_capacity_reached", "appointment_options": []}
        appointment = {
            "appointment_id": f"demo-{len(DEMO_APPOINTMENTS) + 1:04d}",
            "provider_id": provider_id,
            "date": requested_date.isoformat(),
            "time": slot_time,
            "timezone": "America/Chicago",
            "created_at": current.isoformat(),
            "demo_only": True,
        }
        DEMO_APPOINTMENTS.append(appointment)

    return {"scheduled": True, "status": "demo_appointment_scheduled", "provider": provider,
            "appointment": appointment, "demo_only": True,
            "real_appointment_confirmed": False}
