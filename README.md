# Clara: AI voice outreach for high-risk diabetes patients

[![CI](https://github.com/yashvadlamani/hcm-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/yashvadlamani/hcm-agent/actions/workflows/ci.yml)
[![Deploy Clara server](https://github.com/yashvadlamani/hcm-agent/actions/workflows/deploy-server.yml/badge.svg)](https://github.com/yashvadlamani/hcm-agent/actions/workflows/deploy-server.yml)
[![Deploy call-request function](https://github.com/yashvadlamani/hcm-agent/actions/workflows/deploy-function.yml/badge.svg)](https://github.com/yashvadlamani/hcm-agent/actions/workflows/deploy-function.yml)
![Status: prototype](https://img.shields.io/badge/status-prototype-orange)

**Clara** is an AI voice assistant that phones patients on behalf of their health insurance care team. She checks in on how they're managing their diabetes, listens, and responds naturally. She never gives medical advice, and she routes emergencies to 911.

> ⚠️ **Prototype.** Clara runs end to end on Azure with test data. It is **not yet HIPAA-compliant** and must not be used with real patient data. See the [roadmap](./docs/roadmap.md#path-to-real-patient-calls) for the path to production.

## How it works

![Current workflow: a JSON upload to Azure storage triggers an Azure Function, which asks Azure Communication Services to call the patient; the Clara server on App Service runs the conversation with Azure OpenAI and guardrails.](./docs/workflow.svg)

1. **A call request is uploaded:** a small JSON file with the patient's number, name, the reason for the call and risk drivers.
2. **An Azure Function validates it** (allow-list, format, hourly limit) and asks **Azure Communication Services** to dial.
3. **The Clara server runs the conversation.** Clara first verifies the patient's name and date of birth. Then, each turn, the patient's speech is transcribed and run through a LangGraph graph of capability agents: a security check (prompt injection) and a safety check (emergencies) come first, then the care model answers, looking up the plan document, diabetes playbook or provider directory when needed. Guardrails check the reply before Clara speaks, and any emergency is escalated to the care team.
4. **The care team watches live** on a password-protected dashboard that shows the transcript, the tools used on each turn, satisfaction, response times and any blocked attempts or escalations.

More detail: [Architecture](./docs/architecture.md).

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
