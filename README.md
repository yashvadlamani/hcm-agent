# HCM-Agent: Healthcare Voice Outreach Agent

A HIPAA-compliant, AI-powered voice outreach system designed to engage high-risk patients with personalized healthcare guidance, powered by an ML model that identifies at-risk individuals and flags key health drivers.

## Overview

**HCM-Agent** is a production-grade system that:

- 🎯 **Triggers on ML Predictions:** Flags high-risk diabetes patients with their top 5 health drivers
- 🗣️ **Conducts Real-Time Voice Conversations:** Uses streaming ASR/TTS for natural, low-latency interactions
- 📚 **Retrieves Approved Guidance:** RAG-powered system ensures all recommendations come from pre-approved company documents
- 🔐 **Maintains HIPAA Compliance:** End-to-end encryption, audit logging, and strict access controls
- 🤝 **Escalates Intelligently:** Routes complex cases to care managers, pharmacists, or emergency services as needed
- 📞 **Respects Patient Preferences:** Automatic Do-Not-Call (TCPA) compliance and preference management
- 🔧 **Executes Business Logic:** Schedules appointments, routes to PBMs, creates care tasks, and updates patient records

## Documentation

**[→ View the complete System Design & Implementation Guide →](./DESIGN.md)**

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

### Prerequisites
- Python 3.9+
- PostgreSQL 13+
- Redis 6.0+
- Twilio/Vonage account with HIPAA BAA
- API keys: Claude, Deepgram, Pinecone

### Installation
```bash
# Clone the repository
git clone https://github.com/yashvadlamani/hcm-agent.git
cd hcm-agent

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys and HIPAA settings
```

### Running the Agent
```bash
# Start the voice server
python -m hcm_agent.voice_server

# Queue an ML flag for processing
python -m hcm_agent.cli queue_patient --patient_id PT_123456 --risk_score 0.87
```

## Compliance & Security

⚠️ **Important:** This system handles Protected Health Information (PHI). Before deploying:

- [ ] Conduct HIPAA risk assessment
- [ ] Review with legal and compliance teams
- [ ] Implement encryption (TLS 1.2+, AES-256)
- [ ] Set up audit logging and breach detection
- [ ] Establish consent management workflows
- [ ] Configure DNC/TCPA compliance checks
- [ ] Test emergency escalation flows

See [DESIGN.md](./DESIGN.md#hipaa--compliance-checklist) for the full compliance checklist.

## Code Examples

### Ingesting an ML Flag
```python
from hcm_agent.ml_pipeline import ingestMLFlag

flag = {
    "patient_id": "PT_123456",
    "risk_score": 0.87,
    "top_5_drivers": [
        {"driver": "HbA1c > 7.5%", "impact": 0.32},
        {"driver": "BP > 140/90", "impact": 0.21},
        # ...
    ]
}

result = await ingestMLFlag(flag)
# Output: {"status": "queued", "session_id": "sess_..."}
```

### Building the System Prompt
```python
from hcm_agent.prompts import build_system_prompt

prompt = build_system_prompt(
    patient_context=patient,
    risk_drivers=flag["top_5_drivers"],
    approved_docs=retrieved_documents
)
```

### RAG Retrieval
```python
from hcm_agent.rag import RAGRetriever

retriever = RAGRetriever(vector_db, document_store)
docs = await retriever.retrieve_safe(
    query="diabetes management",
    patient_risk_drivers=risk_drivers,
    max_docs=5
)
```

## Testing

```bash
# Run unit tests
pytest tests/unit

# Run integration tests (requires test DB)
pytest tests/integration

# Test compliance checks
pytest tests/compliance

# Load test the voice pipeline
python -m hcm_agent.stress_test --concurrent_calls 10 --duration 5m
```

## Monitoring & Alerts

The system includes built-in monitoring for:

- **Call Latency:** Alert if round-trip > 2s
- **Escalation Rate:** Track % of calls requiring human intervention
- **Patient Satisfaction:** Monitor CSAT scores
- **Compliance:** Daily checks for encryption, DNC updates, audit log integrity
- **Error Rates:** Alert on tool execution failures

See the deployment guide for Datadog/New Relic integration.

## Contributing

Before contributing, review:
1. [DESIGN.md](./DESIGN.md) for architecture
2. HIPAA compliance guidelines
3. The prompt engineering section for safety considerations

## License

Proprietary – Healthcare Confidential

## Support

For technical questions or issues:
- Review the [full design guide](./DESIGN.md)
- Check existing issues on GitHub
- Contact the development team

---

**Built with** ❤️ **for patient health and safety.**
