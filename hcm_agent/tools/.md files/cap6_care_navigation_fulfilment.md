# Capability 6 — Care navigation & fulfilment

Last reviewed: 2026-10-08

After identity verification, the care-management LLM can select these typed LangChain tools.
LangGraph runs selected tools through its `ToolNode` and scoped gateway, then returns results to the
LLM to review. See [`catalog.py`](catalog.py) and
[`member_care.py`](../workflows/member_care.py).

| Tool | Service and current status | Definition and implementation |
|---|---|---|
| `provider_directory_search` | Filters four fictional Chicago-area sample entries by specialty/location and returns clearly labeled demo addresses, ratings, and the next three currently unbooked fictional weekday slots. These are not real providers, patient ratings, availability, or care-navigation recommendations. | Handler: [`domains.py`](../domains.py); family/schema: [`catalog.py`](../catalog.py); directory filtering: [`providers.py`](../providers.py); sample data: [`provider_directory.json`](../../data/provider_directory.json) |
| `request_appointment` | In local CLI demo mode, checks and simulates bookings against six daily weekday slots (09:00, 10:00, 11:00, 13:00, 14:00, 15:00 America/Chicago). It returns dated alternatives for weekends or unavailable slots. The in-memory simulation does not contact a clinic or create a real appointment; phone calls remain `not_configured`. | Handler: [`domains.py:221`](domains.py#L221); registration: [`domains.py:314`](domains.py#L314); family/schema: [`catalog.py:29`](catalog.py#L29), [`catalog.py:103`](catalog.py#L103); schedule/booking logic: [`scheduling.py:68`](scheduling.py#L68); slot list: [`scheduling.py:12`](scheduling.py#L12) |

## Provider directory examples

The records in [`data/provider_directory.json`](../../data/provider_directory.json) are fabricated
test data. Their names, specialties, addresses, availability, and ratings do not represent real
providers or patient reviews. Clara must identify them as fictional examples and must not suggest
contacting or visiting them.

| Patient asks Clara | What the tool can return |
|---|---|
| “Do you have a diabetes specialist in Schaumburg?” | The fictional Schaumburg endocrinology/diabetes-care demo entry and its next three available fictional weekday slots. |
| “Can you show me an endocrinology example near downtown Chicago?” | The fictional Downtown Chicago entry and its sample fields. |
| “Is there a diabetes-care example in Naperville?” | The fictional Naperville entry, including its next three currently unbooked fictional slots. |
| “What sample diabetes providers are listed near Buffalo Grove?” | The fictional Buffalo Grove entry and its clearly labeled sample rating/address. |

## Appointment scheduling demo

The demo checks the provider ID against the fictional directory, excludes weekends and past times,
and prevents double-booking a provider/time slot during the current process. Daily slots are
09:00, 10:00, 11:00, 13:00, 14:00, and 15:00 America/Chicago, Monday through Friday. If no date is
given, Clara offers the nearest available options. If Saturday or Sunday is requested, the tool
returns the next weekday slots with full dates; Clara should read those choices and ask which one the
patient prefers. It books only after the patient selects a returned slot. A successful result is a
simulated demo booking, not an appointment with a real provider. The phone-call path stays disabled
until a real scheduling adapter is connected.

## Boundaries

- Capability 6 contains only `provider_directory_search` and `request_appointment`.
- The LLM interprets the request and reviews tool output. Python checks provider membership, dates,
  weekday/time availability, past times, and duplicate bookings deterministically.
- No clinic is contacted; the demo schedule and booking state are in process memory only.
- Capabilities 1–5 and 7–8 remain intact.

## LangGraph integration

`build_tools` creates decorated tools with `ProviderSearch` and `AppointmentRequest` schemas in
[`catalog.py:153`](catalog.py#L153) and [`catalog.py:205`](catalog.py#L205). The care workflow puts
the current profile and tools into graph runtime state in [`member_care.py:54`](../workflows/member_care.py#L54).
The local interactive CLI marks demo
context in [`chat_demo.py:107`](../cli/chat_demo.py#L107); `conversation.py` binds that to
`local_demo_mode` at [`conversation.py:188`](../agent/conversation.py#L188). The prompt explains the
demo-only schedule and current Chicago date at [`prompts.py:23`](../agent/prompts.py#L23). The shared
LangGraph model/tool loop is in [`graph.py:14`](../workflows/graph.py#L14), with model binding at
[`graph.py:28`](../workflows/graph.py#L28) and actual tool execution via `ToolNode` at
[`graph.py:34`](../workflows/graph.py#L34).
