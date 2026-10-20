# Clara: AI voice outreach for care management

[![CI](https://github.com/yashvadlamani/hcm-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/yashvadlamani/hcm-agent/actions/workflows/ci.yml)
[![Deploy Clara server](https://github.com/yashvadlamani/hcm-agent/actions/workflows/deploy-server.yml/badge.svg)](https://github.com/yashvadlamani/hcm-agent/actions/workflows/deploy-server.yml)
[![Deploy call-request function](https://github.com/yashvadlamani/hcm-agent/actions/workflows/deploy-function.yml/badge.svg)](https://github.com/yashvadlamani/hcm-agent/actions/workflows/deploy-function.yml)
![Status: prototype](https://img.shields.io/badge/status-prototype-orange)

**Clara** is an AI voice assistant that phones patients on behalf of their health insurance care team. She checks in on how they're managing their diabetes, listens, and responds naturally. She never gives medical advice, and she routes emergencies to 911.

> ⚠️ **Prototype.** Clara runs end to end on Azure with test data. It is **not yet HIPAA-compliant** and must not be used with real patient data. See the [roadmap](./docs/roadmap.md#path-to-real-patient-calls) for the path to production.

## How it works

![How Clara works in eight layers: a JSON upload starts the call; the Clara server handles speech; the conversation moves through pre-call policy, identity check and per-turn checks; LangGraph runs a security guard, a safety guard, the care model and its tools; every tool call passes the tool gateway; tools read the plan document, playbook and provider directory; guardrails check each reply and emergencies are escalated; the care team watches on the live dashboard.](./docs/workflow.svg)

Clara is built in eight layers. Each patient turn moves down through them, and Clara's reply goes back up to the phone.

| # | Layer | What happens | Where |
|---|---|---|---|
| 1 | **Start a call** | The care team uploads a small JSON file (number, name, reason for the call, risk drivers). An Azure Function checks the allow-list, the format and the hourly limit, then asks Azure Communication Services to dial. | `azure_functions/` |
| 2 | **Call** | The Clara server on App Service receives call events. Azure AI Speech turns the patient's speech into text and Clara's replies into speech. The local test chat replaces the phone with a typed call in the browser. | `telephony/` |
| 3 | **Conversation** | A call has three phases. **Agents 1–2** (outreach, communication) check consent, do-not-call and calling hours before dialing. **Agent 3** (identity) confirms the name, then the date of birth, before anything health-related. In the care phase, every turn first gets an emergency keyword check, a prompt-injection check and context minimizing, so the model sees only what it needs. | `agent/conversation.py`, `workflows/outreach.py` |
| 4 | **LangGraph agents** | Each turn runs through a graph: **8 · Security guard** (prompt injection), **7 · Safety guard** (a model-based emergency check), then the **care model** (Azure OpenAI `gpt-5-mini`, JSON replies). The care model can call **tools 4 · 5 · 6** (care context, knowledge and policy, navigation). After each tool call the graph goes back through both guards. | `workflows/graph.py`, `tools/tools.py` |
| 5 | **Tool gateway** | Every tool call is checked against an allow-list, limited to the current member, rate-limited, protected by a circuit breaker and written to the audit log. Lookup results are checked against registered sources, and instruction-like text is removed before the model reads them. | `tools/gateway.py`, `tools/security.py` |
| 6 | **Data** | The tools search the plan document and the diabetes playbook (Chroma with BGE-small embeddings, local), the fictional provider directory, and demo member and schedule data. | `tools/policy.py`, `tools/playbook.py`, `data/` |
| 7 | **Reply or escalate** | Guardrails check every reply for diagnoses, medical advice and medication changes before Clara speaks. An emergency from any layer (keywords, the safety guard or Azure's content filter) gets the fixed 911 or 988 message, and the **safety tools** record an urgent alert, a clinical review task and a follow-up for the care team. | `agent/guardrails.py`, `tools/safety.py` |
| 8 | **Watch and run** | The care team watches calls on a password-protected live dashboard: the transcript, tools used on each turn, satisfaction, response times, and blocked-attempt and emergency cards. Transcripts, the audit log and escalation records are kept; OpenTelemetry traces the agents and tools. Secrets live in Key Vault; GitHub Actions tests and deploys. | `telephony/static/live.html` |

**The eight agents and their tools**

| Agent | Tools | Status |
|---|---|---|
| 1 · Outreach | Eligibility, consent and do-not-call, calling hours, contact check, call authorization, call attempt record | Reference implementation |
| 2 · Communication | Language, accessibility and contact preferences, voice settings, interpreter, starting the call | Reference implementation |
| 3 · Identity | `verify_full_name`, `verify_dob` (live); one-time code, low speech confidence, authorized representative, failure record | Name and date of birth live; others reference |
| 4 · Care context | `get_safe_outreach_brief`, `get_approved_goals` | Live (demo content) |
| 5 · Knowledge and policy | `search_diabetes_playbook`, `lookup_policy` | Live (draft content) |
| 6 · Navigation | `provider_directory_search`, `request_appointment` | Demo data, not booked for real |
| 7 · Safety and escalation | `assess_emergency`, `route_member_distress`, `create_urgent_alert`, `create_clinical_review_task`, `create_safety_follow_up`, `get_911_or_988_script` | Live; records not yet sent to a care-team system |
| 8 · Security and audit | Prompt-injection detection, redaction, context minimizing, source checks, cleaning search results, allow-list, member scope, rate limits, circuit breaker, audit log (13 of 17) | Working drafts |

More detail: [Architecture](./docs/architecture.md) and [Workflow and tools](./docs/architecture/workflow-and-tools.md).

## Capabilities

| Capability | Status |
|---|---|
| Live two-way phone conversations (Azure Communication Services, Azure AI Speech) | ✅ Live |
| Replies personalized to the patient: their own words, the reason for the call and their risk drivers (Azure OpenAI or Claude) | ✅ Live |
| Safety guardrails: no diagnoses, no medical advice, no medication changes (promises: prompt instruction only) | ✅ Live |
| Emergency detection: keywords, a model-based safety check every turn, and Azure's content filter; 911 or the 988 crisis line | ✅ Live |
| Emergency escalation records for the care team: urgent alert, clinical review task, safety follow-up | ✅ Recorded (not yet sent to a care-team system) |
| Identity check (name and date of birth) before anything health-related | ✅ Live |
| LangGraph capability agents with typed tools behind a permission and audit gateway | ✅ Live |
| Security checks: prompt-injection blocking, personal-data redaction, context minimizing, audit log, rate limits, checked and cleaned search results (13 of 17 security tools) | ✅ Working drafts |
| Natural call endings ("anything else?") with a feedback-form opt-in | ✅ Live |
| Live score (0–1) of how satisfied the patient seems with the call, on the dashboard | ✅ Live |
| Start calls by uploading a JSON file (Azure Functions + Event Grid) | ✅ Live |
| Live call dashboard with tools per turn, response times, guardrail, security and emergency cards | ✅ Live |
| Local test chat in the browser: a full typed call with no phone or call minutes | ✅ Live |
| On-demand automated PR review (comment `/review`) | ✅ Live |
| Secrets in Azure Key Vault; automated tests and deploys (GitHub Actions) | ✅ Live |
| Policy-gated outreach workflow (consent, DNC, calling hours, authorization) | ✅ Reference implementation |
| Answers from the plan document and diabetes playbook (local search) | ✅ Demo content |
| Delivering escalations and follow-up tasks to a care-team system | 🚧 Planned |
| Answers grounded in clinically approved content | 🚧 Planned |
| HIPAA-ready production environment (BAA, purchased number, audit logging) | 🚧 Planned |

## Technology

| Layer | Technology |
|---|---|
| Phone calls, speech-to-text, text-to-speech | Azure Communication Services · Azure AI Speech |
| Conversation | Azure OpenAI (`gpt-5-mini`) or Anthropic Claude, with rule-based guardrails |
| Agents and tools | LangChain · LangGraph |
| Search | Chroma with FastEmbed (BGE-small) embeddings, local |
| Observability | OpenTelemetry tracing of agents and tools |
| Application | Python 3.12 · Flask on Azure App Service |
| Call requests | Azure Functions (Flex Consumption) · Blob Storage · Event Grid |
| Security | Azure Key Vault · managed identities |
| Delivery | GitHub Actions: lint, tests and automatic deploys on merge to `main` |

## Quick start

```bash
git clone https://github.com/yashvadlamani/hcm-agent.git && cd hcm-agent
python -m pip install -e ".[dev]"     # app, test tools and the clara-* commands
cp config/.env.example .env           # fill in your keys and phone settings
pytest                                # no keys or network needed
clara-chat demo                       # a sample conversation in the terminal
clara-interactive-chat                # a full typed call in the browser (needs model settings)
```

To set up Azure and place your first real call, follow [Setup and deployment](./docs/setup.md).

## Documentation

| Document | What's in it |
|---|---|
| [Architecture](./docs/architecture.md) | How Clara works: components, call flow, guardrails, security model, key decisions |
| [Workflow and tools](./docs/architecture/workflow-and-tools.md) | Native LangChain/LangGraph agents, eight tool families, and member-scoped tool execution |
| [Setup and deployment](./docs/setup.md) | Install, phone number, deploy to Azure, automatic deploys, placing calls |
| [Operations](./docs/operations.md) | Health checks, on/off, logs, keys, phone numbers, costs, troubleshooting |
| [Roadmap](./docs/roadmap.md) | What's next, the path to real patient calls, project history |
| [Contributing and security](./docs/contributing.md) | Branch and PR workflow, standards, handling secrets |
| [Target design](./docs/target-design.md) | The long-term product vision |

## Repository layout

```
hcm-agent/
├── hcm_agent/              # Everything Clara runs on
│   ├── agent/              #   Conversation: prompts, model backends, guardrails, identity check
│   ├── workflows/          #   LangGraph: capability-agent graph, pre-call policy, member care
│   ├── tools/              #   Tool gateway, tool catalog, safety and security tools, search
│   ├── telephony/          #   Calls: ACS event server, outbound calls, live dashboard, transcripts
│   ├── cli/                #   clara-chat, clara-interactive-chat and clara-call
│   ├── azure_functions/    #   Azure Function: JSON upload → phone call
│   └── deploy/             #   Deploy, start and stop scripts for Azure
├── tests/                  # Automated tests
├── config/                 # .env.example: every setting, documented
├── data/                   # Demo members, plan document, playbook, provider directory, test-call transcripts
├── docs/                   # Architecture, setup, operations, roadmap and more (see above)
└── .github/                # CI, automatic deploys, on-demand PR review, PR template
```

## Contributing and security

Work happens on branches, through pull requests into `main`, and merging deploys automatically. Never commit secrets. Both are covered in [Contributing and security](./docs/contributing.md).

## License

Proprietary and confidential. See [LICENSE](./LICENSE).
