# Capability 4 — Care-management context

Last reviewed: 2026-10-08

After identity verification, the care-management LLM can select these typed LangChain tools.
LangGraph runs selected tools through its `ToolNode` and the scoped gateway, then returns their
results to the LLM to review. See [`catalog.py`](catalog.py) and
[`member_care.py`](../workflows/member_care.py) for the graph/tool wiring.

| Tool | Service and current status | Definition and registration |
|---|---|---|
| `get_safe_outreach_brief` | Returns purpose, up to five risk drivers, a bounded care-team record summary, and up to five follow-up prompts. Wired for verified conversations; local CLI records are fictional. No live care-management source is connected. | Handler: [`domains.py:156`](domains.py#L156); registration: [`domains.py:309`](domains.py#L309); family: [`catalog.py:25`](catalog.py#L25); empty input schema: [`catalog.py:87`](catalog.py#L87) |
| `get_approved_goals` | Returns up to five server-bound goals with an approval flag. Demo `goals_on_file` return `approved: false`; no authoritative care-plan/CRM source is connected. | Handler: [`domains.py:172`](domains.py#L172); registration: [`domains.py:310`](domains.py#L310); family: [`catalog.py:25`](catalog.py#L25); empty input schema: [`catalog.py:87`](catalog.py#L87) |

Both tools have empty argument schemas so the model can choose them but cannot supply or alter
member facts. Demo context is loaded only for local interactive CLI calls that explicitly enable
it; outbound phone calls do not load fictional demo fields from the member dataset. The demo
profiles contain fictional care-team summaries, goals-on-file, and follow-up plans—not real care-team
documentation or approved plans.

## Example questions

The patient asks Clara; Clara may select a tool internally. Clara may also use retrieved context to
choose a relevant follow-up question. These are examples, not fixed prompts. Fictional demo goals
must never be described as approved or factual.

| Sample patient questions | Sample Clara questions |
|---|---|
| “Why are you calling me?” (`get_safe_outreach_brief`) | “I’m checking in about your diabetes care. How have things been going lately?” (`get_safe_outreach_brief`) |
| “What did my care team want to check in about?” (`get_safe_outreach_brief`) | “Have you been able to arrange the follow-up that’s listed as a goal?” (`get_approved_goals`; only if an authoritative result says the goal is approved) |
| “What goals are on file for me?” (`get_approved_goals`) | “Would it help to talk about anything that’s making it harder to get the care you need?” (`get_safe_outreach_brief` / `get_approved_goals`) |
| “What should I follow up on with my care team?” (`get_approved_goals`) | “Which of these approved goals would you like to focus on today?” (`get_approved_goals`; only if approved goals are returned) |

If authoritative goals are unavailable, Clara should say she cannot see approved goals in this call
and ask an open question rather than inventing one. Current demo goals return `approved: false`.

## Boundaries

- Capability 4 contains only the two tools listed above; capabilities 1–3 and 7–8 remain intact.
- The gateway binds the member ID and enforces tool scope; see [`gateway.py`](gateway.py).
- The LLM reviews tool results, but the records remain server-bound and are not model-provided.

## LangGraph integration

For both tools, the app binds verified member context in
[`conversation.py:188`](../agent/conversation.py#L188). The care workflow supplies server-bound
state in [`member_care.py:54`](../workflows/member_care.py#L54). Decorated tools read it through
`ToolRuntime` in [`catalog.py:158`](catalog.py#L158); the adapter starts the graph in
[`llm.py:39`](../agent/llm.py#L39). Graph state and tool execution are defined in
[`graph.py:14`](../workflows/graph.py#L14) and [`graph.py:34`](../workflows/graph.py#L34).
