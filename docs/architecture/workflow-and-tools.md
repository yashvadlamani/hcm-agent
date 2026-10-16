# LangChain / LangGraph workflow and tools

Clara now uses real LangGraph and LangChain, not a local imitation of their APIs.

```mermaid
flowchart LR
    S[Start] --> SEC[8. Security guard]
    SEC --> SAFE[7. Safety guard]
    SAFE --> M[Care-model node]
    M --> C4[4. Care context tools]
    M --> C5[5. Knowledge and policy tools]
    M --> C6[6. Navigation tools]
    C4 --> SEC
    C5 --> SEC
    C6 --> SEC
    M --> R[Clara response]
    P1[1. Outreach tools] --> P2[2. Communication tools]
    P2 --> I[3. Identity tools]
    I --> S
```

## Read the implementation in this order

| File | Responsibility |
|---|---|
| `hcm_agent/workflows/graph.py` | Native `StateGraph`, named capability nodes, safety/security guard nodes, and bounded model/tool loops |
| `hcm_agent/agent/llm.py` | LangChain `ChatOpenAI` for the existing Azure v1 endpoint, or `ChatAnthropic` |
| `hcm_agent/tools/tools.py` | Readable capability-to-tool ownership and graph-stage tool availability |
| `hcm_agent/tools/catalog.py` | Eight families of typed `@tool` definitions and server-bound tool execution |
| `hcm_agent/tools/gateway.py` | Actor, scope, tenant context, member boundary, and in-memory audit checks |
| `hcm_agent/tools/domains.py` | Business rules and clearly identified reference adapters |
| `hcm_agent/tools/playbook.py` + `data/playbooks/diabetes_quick_care_playbook.md` | LangChain chunking, local Chroma vector index, open BGE-small embeddings, and LLM-expanded semantic retrieval for the diabetes support draft |
| `hcm_agent/tools/policy.py` + `data/policies/sbc-gpsd69bceiilo-il-2025.pdf` | Separate LangChain PDF loader/splitter, local Chroma index, BGE-small embeddings, and LLM-expanded retrieval with source page numbers |
| `hcm_agent/tools/providers.py` + `data/provider_directory.json` | Bounded specialty/location filtering over four clearly fictional Chicago-area demo providers |
| `hcm_agent/tools/scheduling.py` | In-memory local demo schedule: six daily weekday slots in America/Chicago, weekend closure, conflict checking, booking simulation, and dated alternatives |
| `hcm_agent/agent/conversation.py` | Call phases, approved introduction, emergency responses, and response guardrails |

## Eight families

Outreach eligibility; communication/accessibility; identity; care context/follow-up;
approved guidance; benefits/navigation/requests; safety/escalation; security/operations.

The stage gate exposes capability 1–2 only before a call, capability 3 during
identity verification, and capabilities 4–8 during a verified care conversation.
GPT selects relevant tools within the active stage and sees their actual results before responding.
The model receives question/answer schemas; the application binds expected identity, member scope,
policy inputs and source records. It cannot supply a different member ID or override expected DOB.

Reference tools are callable, but not live integrations. Policy lookup is grounded only in the
supplied PDF, whose plan-owner approval status has not been verified. Provider entries are fictional
demo data and must not be used for real care navigation. In explicit local demo mode, appointment
requests can reserve a simulated weekday slot in bounded process memory, with weekend/unavailable
dates returning actual next-slot dates. They are never sent to a clinic or booked in a real scheduler.
Phone requests report `not_configured` until a real adapter is connected, and no successful bookings
are claimed. The safety tools (urgent alert, clinical review task, safety follow-up) keep real
escalation records; see [Emergency escalation](#emergency-escalation).

The care family includes `get_safe_outreach_brief` and `get_approved_goals`. LangChain exposes both
as no-argument tools, so the model can select them but cannot provide or alter member facts. The
application binds the current call's purpose/drivers and, when the local CLI explicitly enables
demo context, the fictional care-team summary, goals-on-file examples, and follow-up plan. Those
goals report `approved: false`; an authoritative goals service is not connected. Phone calls do
not load the dataset's fictional demo context.

The complete capability 4–6 scope is six tools only: `get_safe_outreach_brief`,
`get_approved_goals`, `search_diabetes_playbook`, `lookup_policy`,
`provider_directory_search`, and `request_appointment`. Other candidates in these three
capabilities are removed from the callable catalog. Capabilities 1–3 and 7–8 remain unchanged.

The diabetes playbook is split with LangChain's Markdown and recursive character splitters
(1,400-character chunks with 200-character overlap). The chunks are embedded locally with the open
`BAAI/bge-small-en-v1.5` model through FastEmbed and persisted in the Chroma vector store under
`data/vectorstore/diabetes-playbook` by default. The index is built lazily on first retrieval; run
`clara-playbook-index --rebuild` after changing the playbook. Set `CLARA_PLAYBOOK_VECTOR_DIR` if the
default directory is not writable (for example, on a hosted deployment). Clara's configured chat
model powers LangChain's `MultiQueryRetriever` to expand the caller's question, then the same care
agent reviews the returned CDC-cited passages and writes the answer. Retrieval is local, but query
expansion uses the configured LLM and therefore adds a model call when this tool is selected.

The tool returns matched passages with CDC source links and marks the corpus as a draft pending
clinical-owner review. Clara may use it for general support and navigation only; medication advice
is prohibited in the system prompt and checked by deterministic response guardrails. The content is
not approved for production clinical use until an appropriate owner reviews it. The local Chroma
directory is ignored by Git and is not currently a managed or shared production vector database.

## Security and safety around every turn

Each conversation turn passes these checks, in order. All of them run in code through the tool gateway,
so they appear in the audit log and in the dashboard's tools-per-turn line.

| Step | Where | What happens |
|---|---|---|
| Keyword emergency check | `conversation.py` | An instant match ("chest pain") ends the turn with the emergency message, with no model call |
| `detect_prompt_injection` | `conversation.py` | An attempt gets a fixed reply, is kept out of the history, and is recorded as a policy decision |
| `minimize_prompt_context` | `conversation.py` | Twice: the prompt gets only the fields it reads, and the care tools get no identifier fields |
| Security guard | `graph.py` | `detect_prompt_injection` again, inside the graph, on every pass |
| Safety guard | `graph.py` | One model safety check per turn, validated by `assess_emergency`, which also applies the keyword list |
| `validate_rag_source` | `catalog.py` | After a playbook or policy lookup: only registered sources pass, with approval and date warnings |
| `sanitize_untrusted_content` | `catalog.py` | After care, guidance and navigation tools: instruction-like text is removed before the model reads it |
| Guardrails | `guardrails.py` | The reply is checked for diagnoses, medical advice and medication changes |

The gateway (`gateway.py`) also writes every tool call to the audit log and limits ordinary tools to
`TOOL_CALLS_PER_MINUTE` calls per call; emergency and identity tools are never limited.

## Emergency escalation

Any emergency, from any layer, ends in `HCMVoiceAgent._escalate`, which runs the safety family in a fixed
order: `assess_emergency`, `route_member_distress`, `create_urgent_alert`, `create_clinical_review_task`,
`create_safety_follow_up`, then `get_911_or_988_script` for Clara's fixed words. Records go to the
escalation log in `tools/safety.py`. A recording failure never blocks the emergency message. When the
model calls these tools itself, the kind and reason come from a prior `assess_emergency` result.
Details: [`tools/safety.md`](../../hcm_agent/tools/safety.md).

## Structured replies

Each care turn must come back as one JSON object: Clara's reply, the emergency assessment, the
satisfaction score and the conversation state. Azure OpenAI requests ask for JSON mode on every model
call (conversation, safety check, identity and pre-call checks). It is sent as `extra_body`, because
LangChain's own `response_format` option refuses requests that offer tools unless every tool is strict.
If the model still writes its reply in front of the JSON, the parser speaks the text and never the JSON.

## Live identity verification

Clara introduces herself and asks for a name. GPT invokes the name tool through LangGraph, then reviews
the result. First-name answers and bounded phonetic variants can pass the name step.
Clara then requests DOB; GPT normalizes the spoken date and invokes the DOB tool.
A failed tool result cannot be overridden by GPT. Missing records and mismatches end the call politely;
model/service errors get the separate unavailable message. Identity answers are masked in stored transcripts.

The phone server selects the expected member by phone number; terminal chat selects the configured
member before the simulated call. Records come from `MEMBER_DATA_PATH` or `data/demo_members.json`.
Both server and Function deployment packages include the default demo dataset.

## Outbound calls

CLI and Azure Function use `place_member_call`:
1. GPT invokes the mandatory preflight tool, which evaluates stored consent, DNC, frequency, local time and contact.
2. GPT reviews the result; approval alone cannot bypass a failed check.
3. GPT invokes the authorized ACS call tool once and reviews the actual result.

The low-level `place_call` function remains an ACS adapter, not the application entry point.
Policies stay deterministic; model interpretation never substitutes for consent.

## Usage and verification

Identity uses one tool round plus model review. General care allows at most three tool rounds,
then a final response. Agents and tools are traced with OpenTelemetry (`hcm_agent/observability.py`);
no checkpointer is enabled. LangChain model clients use a 15-second timeout with no automatic retry,
matching the phone server's 15-second response deadline.

The full offline suite runs in CI (`pytest -q`). `tests/test_tool_scenario.py` runs one scripted call
through the server, graph and gateway and checks that all 19 safety and security tools run. Typed calls
have been run against the real model in the local test chat; a real phone call and an Azure deployment
of this version have not.

Framework references: [LangGraph workflows](https://docs.langchain.com/oss/python/langgraph/workflows-agents),
[LangChain tools](https://docs.langchain.com/oss/python/langchain/tools),
[ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai).
