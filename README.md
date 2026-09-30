# HCM-Agent: Healthcare Voice Outreach Agent

An AI-powered voice outreach system designed to engage high-risk patients with personalized healthcare guidance, powered by an ML model that identifies at-risk individuals and flags key health drivers.

## What it does today

Meet **Clara**, a virtual assistant that calls patients on behalf of their health insurance care team. The current prototype can:

- 📞 **Hold a live phone conversation.** Clara calls a patient via Twilio, greets them, listens, and responds naturally, turn by turn.
- 🧠 **Generate replies with Claude** (`claude-opus-5`) based on the patient's name and risk drivers.
- 🛡️ **Enforce safety guardrails.** Clara never diagnoses, gives medical advice, or suggests medication changes; risky replies are replaced with a safe referral to the patient's doctor or care team.
- 🚨 **Handle emergencies.** Phrases like "chest pain" trigger an immediate 911 message and end the call.
- 👀 **Show calls live.** A local page at `http://localhost:5000/live` shows each call as it happens: what the patient said (with speech-confidence warnings), Clara's replies and response times, blocked replies, and emergencies.
- 💬 **Run without a phone.** Text-only test modes let you chat with Clara or check the guardrails from the terminal.

**[→ Getting Started: setup and your first test call →](./docs/GETTING_STARTED.md)**

> ⚠️ This is a development prototype. It is **not yet HIPAA-compliant** and must not be used with real patient data. The capabilities below describe the target design.

## Overview

**HCM-Agent** is designed to be a production-grade system that:

- 🎯 **Triggers on ML Predictions:** Flags high-risk diabetes patients with their top 5 health drivers
- 🗣️ **Conducts Real-Time Voice Conversations:** Uses streaming ASR/TTS for natural, low-latency interactions
- 📚 **Retrieves Approved Guidance:** RAG-powered system ensures all recommendations come from pre-approved company documents
- 🔐 **Maintains HIPAA Compliance:** End-to-end encryption, audit logging, and strict access controls
- 🤝 **Escalates Intelligently:** Routes complex cases to care managers, pharmacists, or emergency services as needed
- 📞 **Respects Patient Preferences:** Automatic Do-Not-Call (TCPA) compliance and preference management
- 🔧 **Executes Business Logic:** Schedules appointments, routes to PBMs, creates care tasks, and updates patient records

## Documentation

**[→ View the complete System Design & Implementation Guide →](./docs/DESIGN.md)**

The guide covers three major areas:

### 1. Architecture & Knowledge Retrieval
- ML model → agent pipeline
- RAG architecture for retrieving pre-approved documents
- Voice latency optimization (sub-1.5s round-trip)
- Context pre-computation and caching strategies

### 2. Prompt Engineering & Guardrails
- Core system prompt with strict medical boundaries
- "No medical opinions" enforcement
- Distress detection and emergency escalation
- HIPAA-compliant call logging and compliance documentation

### 3. Action Execution (Tool Calling)
- Tool taxonomy and design patterns
- Safety gates for all tool execution
- PBM (Pharmacy Benefit Manager) integration
- Care manager escalation decision trees
- Do-Not-Call (DNC) database and TCPA compliance

## Key Architecture Decisions

```
ML Model Flag (high-risk + top 5 drivers)
          ↓
Pre-Call Context Preparation (async)
          ↓
Voice Call Initiated (streaming ASR/TTS)
          ↓
Conversation Loop (RAG + Tool Planning + LLM)
          ↓
Post-Call Execution (tools, escalations, logging)
```

### Core Technologies

| Component | Recommended Stack |
|-----------|-------------------|
| **Voice Infrastructure** | Twilio / Telnyx (with BAA) |
| **Speech Recognition** | Deepgram / Google Cloud Speech |
| **Text-to-Speech** | ElevenLabs / Azure Cognitive Services |
| **LLM Agent** | Claude API |
| **Vector DB (RAG)** | Pinecone / Weaviate |
| **Caching** | Redis |
| **Database** | PostgreSQL + encrypted storage |

## Development Roadmap

### Phase 1 (MVP)
- Core voice agent with single-threaded conversation
- Basic escalation to care managers
- System prompt with medical boundaries

### Phase 2
- RAG system integration
- EHR context retrieval
- Document approval workflow

### Phase 3
- Multi-turn conversation optimization
- Distress detection and emergency routing
- Tool execution for appointments/escalations

### Phase 4
- PBM integrations (refill requests, prior auth)
- Full compliance audit
- Pilot with patient subset

### Phase 5
- Scale to production
- Specialist routing
- Real-world outcome monitoring

## Getting Started

**[→ Setup and test-call guide →](./docs/GETTING_STARTED.md)**

The guide covers what works today, how a call flows through the app, setting up Claude, Twilio and ngrok, and placing your first test call.

### Quick reference

```bash
pip install -r requirements.txt
cp .env.example .env                           # then fill in your keys

python -m hcm_agent.chat_demo interactive      # chat with Clara in the terminal
python -m hcm_agent.phone_server               # start the phone server (then run: ngrok http 5000)
python -m hcm_agent.place_call --url https://<ngrok-address> --to +1XXXXXXXXXX --name <FirstName>
```

## Project Structure

```
hcm-agent/
├── hcm_agent/              # Application package
│   ├── agent.py            # Conversation logic and the Claude call
│   ├── guardrails.py       # Safety checks (diagnosis, advice, medication changes, emergencies)
│   ├── prompts.py          # System prompts
│   ├── phone_server.py     # Twilio webhook server for live calls (+ the /live page)
│   ├── live_feed.py        # In-memory event feed behind the live call view
│   ├── static/live.html    # Live call view (local only)
│   ├── place_call.py       # Places an outbound test call
│   ├── chat_demo.py        # Terminal chat with Clara (no phone needed)
│   └── mock_voice.py       # Terminal "call" interface used by chat_demo
├── tests/                  # Automated tests (no API calls or phone needed)
├── docs/
│   ├── GETTING_STARTED.md  # Setup and test-call guide
│   └── DESIGN.md           # Full target architecture
├── requirements.txt
└── .env.example            # Template for keys and settings
```

## Testing

```bash
python -m pytest
```

The tests cover the guardrails and the phone server's call flow. They use a stand-in for Claude, so they run in seconds and cost nothing.

## Compliance & Security

⚠️ **Important:** This system handles Protected Health Information (PHI). Before deploying:

- [ ] Conduct HIPAA risk assessment
- [ ] Review with legal and compliance teams
- [ ] Implement encryption (TLS 1.2+, AES-256)
- [ ] Set up audit logging and breach detection
- [ ] Establish consent management workflows
- [ ] Configure DNC/TCPA compliance checks
- [ ] Test emergency escalation flows

See [DESIGN.md](./docs/DESIGN.md#hipaa--compliance-checklist) for the full compliance checklist.

## Contributing

Before contributing, review:
1. [DESIGN.md](./docs/DESIGN.md) for architecture
2. HIPAA compliance guidelines
3. The prompt engineering section for safety considerations

Run `python -m pytest` before opening a pull request.

## License

Proprietary – Healthcare Confidential

## Support

For technical questions or issues:
- Review the [full design guide](./docs/DESIGN.md)
- Check existing issues on GitHub
- Contact the development team

---

**Built with** ❤️ **for patient health and safety.**
