# HCM Voice Outreach Agent: System Design & Implementation Guide

**Last Updated:** September 19, 2026

---

## Table of Contents

1. [Architecture & Knowledge Retrieval](#architecture--knowledge-retrieval)
2. [Prompt Engineering & Guardrails](#prompt-engineering--guardrails)
3. [Action Execution (Tool Calling)](#action-execution-tool-calling)
4. [End-to-End Integration & Compliance](#end-to-end-integration--compliance)

---

## Architecture & Knowledge Retrieval

### System Overview

Your pipeline has four core stages:

```
ML Model Flag
    ↓
[High-Risk Patient + Top 5 Risk Drivers]
    ↓
Retrieval Augmented Generation (RAG)
    ↓
[Context + Approved Documents]
    ↓
LLM-Based Voice Agent
    ↓
[Tool Calls → Business Logic Execution]
```

**Key architectural decisions:**

- **Synchronous + Async Queueing:** Trigger on ML flag → async queue → voice call (user-initiated or auto-dialed)
- **Context Window Management:** Pre-load patient risk drivers + relevant docs upfront to minimize latency
- **RAG as Safety Guard:** Vector DB + keyword search ensures only approved docs are referenced
- **Streaming + Interruption:** Stream audio output to support natural conversation flow and patient interrupt capability

### ML Model → Agent Pipeline

The ML model should produce a structured output:

```json
{
  "patient_id": "PT_123456",
  "risk_score": 0.87,
  "risk_category": "diabetes_complication_risk",
  "top_5_drivers": [
    {"driver": "HbA1c > 7.5%", "impact": 0.32},
    {"driver": "BP > 140/90", "impact": 0.21},
    {"driver": "Missing medication refill", "impact": 0.18},
    {"driver": "No recent clinic visit (6mo+)", "impact": 0.16},
    {"driver": "High BMI trajectory", "impact": 0.13}
  ],
  "medical_history_summary": {
    "conditions": ["Type 2 Diabetes", "Hypertension"],
    "current_meds": ["Metformin 500mg", "Lisinopril 10mg"],
    "recent_labs": {"HbA1c": "8.1%", "BP": "145/92"}
  },
  "flags": {
    "language_preference": "en",
    "do_not_call": false,
    "previous_engagement": true
  }
}
```

#### Agent Ingestion (Pseudo-code)

```python
async def ingestMLFlag(flag):
    # 1. Validate patient data integrity
    patient = await db.getPatient(flag.patient_id)
    if patient.status == "deceased" or patient.dnd_status == "active":
        return log("Patient DND or inactive")
    
    # 2. Retrieve approved documents via RAG
    relevant_docs = await rag.retrieve(
        query=flag.risk_category,
        patient_context=flag.top_5_drivers,
        doc_filters=["approved", "published"],
        max_docs=5
    )
    
    # 3. Build context for agent
    agent_context = {
        "patient": patient,
        "risk_drivers": flag.top_5_drivers,
        "approved_guidance": relevant_docs,
        "session_id": uuid.generate(),
        "timestamp": now()
    }
    
    # 4. Queue for voice call (async)
    await queue.enqueue({
        "patient_id": flag.patient_id,
        "context": agent_context,
        "priority": flag.risk_score,
        "callback_handler": scheduleCall
    })
    
    return {"status": "queued", "session_id": agent_context.session_id}
```

### RAG Architecture: Knowledge Retrieval

**Goal:** Ensure the agent only cites pre-approved company guidance, not hallucinated medical information.

#### Vector Database Setup

- **Store:** Approved clinical guidelines, patient education materials, care pathways (PDF, markdown, structured data)
- **Chunking:** Split docs into 300–500 token chunks with metadata tags (source, approval_date, version, category)
- **Embedding Model:** Use a biomedical-tuned model (e.g., PubMedBERT, or fine-tune on your approved docs)
- **Indexing:** Pinecone, Weaviate, or Milvus. Include hybrid search (BM25 + semantic).

#### Retrieval Pipeline

```python
class RAGRetriever:
    def __init__(self, vector_db, document_store):
        self.vector_db = vector_db
        self.doc_store = document_store
        self.approval_cache = {}  # In-memory cache of approved docs
    
    async def retrieve_safe(self, query, patient_risk_drivers, max_docs=5):
        """
        Retrieve only APPROVED documents relevant to patient context.
        """
        # 1. Semantic search
        semantic_results = await self.vector_db.search(
            embedding=embed(query),
            top_k=10,
            filters={"status": "approved"}
        )
        
        # 2. Keyword search for explicit medical terms in risk drivers
        keyword_queries = [d["driver"] for d in patient_risk_drivers[:3]]
        keyword_results = await self.vector_db.bm25_search(
            queries=keyword_queries,
            filters={"status": "approved"},
            top_k=5
        )
        
        # 3. Deduplicate and merge
        docs = self._merge_results(semantic_results, keyword_results, max_docs)
        
        # 4. Add verification step
        verified_docs = []
        for doc in docs:
            source_meta = await self.doc_store.get_metadata(doc["source_id"])
            if source_meta["approval_status"] == "active":
                verified_docs.append({
                    "text": doc["text"],
                    "source": source_meta["filename"],
                    "approved_date": source_meta["approval_date"],
                    "relevance_score": doc["score"]
                })
        
        return verified_docs
    
    def _merge_results(self, semantic, keyword, max_docs):
        """Merge results with deduplication."""
        seen_ids = set()
        merged = []
        
        # Semantic results have higher priority
        for result in semantic + keyword:
            if result["doc_id"] not in seen_ids:
                merged.append(result)
                seen_ids.add(result["doc_id"])
                if len(merged) >= max_docs:
                    break
        
        return merged
```

#### Safety Guardrails for RAG

- **Source Attribution:** Always cite the document source in the response
- **Confidence Thresholding:** Only include results with similarity > 0.7
- **Fallback:** If no documents found, explicitly state "I don't have guidance on this topic" (don't hallucinate)
- **Version Control:** Track document approval dates; don't reference outdated guidance
- **Audit Trail:** Log every retrieval for compliance review

### Voice Latency Optimization

Real-time voice conversations require sub-500ms latency. Here's how to achieve it:

#### Latency Budget

| Stage | Target (ms) | Strategy |
|-------|-------------|----------|
| Audio capture → ASR | 200–300 | Stream ASR (e.g., Google Cloud Speech, Deepgram) |
| Intent extraction | 100–150 | Cached embeddings, lightweight classifier |
| RAG retrieval | 150–200 | Pre-compute vs. real-time trade-off |
| LLM inference (streaming) | 300–500 | Token streaming (first token latency critical) |
| TTS synthesis | 200–300 | Streaming TTS (e.g., ElevenLabs, Google TTS) |
| **Total Round-Trip** | **< 1.5s** | Parallel + caching |

#### Pre-computation Strategy

**Critical insight:** Pre-load context *before* the voice call starts.

```python
# Pre-compute during async queue wait
async def prepare_context(patient_id, risk_drivers):
    """
    Called while user is arriving at the call, before voice starts.
    """
    # Cache the patient's full context
    patient_context = {
        "patient_data": await db.getPatient(patient_id),
        "retrieved_docs": await rag.retrieve(risk_drivers),
        "tool_schemas": load_tool_schemas(),  # Pre-serialize
        "conversation_history": []
    }
    
    # Store in fast cache (Redis, in-memory)
    await fast_cache.set(f"context:{patient_id}", patient_context, ttl=3600)
    return patient_context

# During voice call (low-latency path)
async def handle_voice_call(patient_id, audio_stream):
    # Retrieve from cache (< 5ms)
    context = await fast_cache.get(f"context:{patient_id}")
    
    # Process incoming audio
    async for transcript_chunk in asr_stream(audio_stream):
        # Parallel: tool selection + response generation
        intent = classify_intent(transcript_chunk)
        
        # Parallel tasks
        tool_prep = tools.prepare(intent, context)
        response_gen = agent.generate(
            transcript=transcript_chunk,
            context=context,
            tools_available=tool_schemas
        )
        
        # Wait for first token of response
        async for token in response_gen:
            # Stream to TTS immediately
            await tts_stream(token)
            break  # First token latency
```

---

## Prompt Engineering & Guardrails

### Core System Prompt

This is the foundational instructions for your agent:

```
You are a compassionate healthcare support agent for a patient health
management program. Your role is to:

1. PROVIDE GUIDANCE: Share evidence-based information from approved
   company resources only.
2. EMPOWER PATIENTS: Help patients understand their health condition
   and take positive actions.
3. SUPPORT, NOT DIAGNOSE: You are a support tool, not a medical provider.
   Never diagnose conditions or recommend specific medications.

---
STRICT RULES:

[MEDICAL BOUNDARIES]
- NEVER diagnose, prescribe, or change medication instructions.
- If a patient reports worsening symptoms or emergency signs (chest pain,
  severe shortness of breath, stroke symptoms), IMMEDIATELY escalate:
  "This sounds urgent. I'm connecting you to our care team right away."
- For non-emergency but concerning symptoms, say:
  "Thank you for sharing that. I'd like our care team to review this with
  you. I'm scheduling a call with our care manager within 24 hours."

[DOCUMENTATION BOUNDARIES]
- Only reference approved documents by name and date.
- If you retrieve a document, cite it: "According to our [Document Name],
  published [Date]..."
- If you cannot find relevant guidance, say:
  "I don't have specific guidance on that topic. Our care team can help—
  would you like me to schedule a call?"

[TONE & EMPATHY]
- Use the patient's preferred language.
- Acknowledge their concerns before providing guidance.
- Avoid jargon; use plain language.
- Show warmth and genuine interest in their well-being.

[SCOPE OF CONVERSATION]
You can help with:
  • Understanding their condition (diabetes, hypertension, etc.)
  • Explaining medication adherence importance
  • Reviewing lab results (no clinical interpretation beyond approved docs)
  • Encouraging preventive care
  • Addressing barriers to care
  • Scheduling follow-ups or connecting to resources

You CANNOT and SHOULD NOT:
  • Diagnose new conditions
  • Adjust treatment plans
  • Recommend specific drugs by name
  • Interpret complex lab results beyond approved docs
  • Provide mental health crisis support (escalate immediately)

---
SESSION CONTEXT:
Patient Risk Profile: {patient_risk_drivers}
Approved Guidance Documents: {approved_docs_list}
Patient Medical History: {medical_history_summary}
```

#### Dynamic Personalization

Inject patient-specific context at runtime:

```python
def build_system_prompt(patient_context, risk_drivers, approved_docs):
    """
    Construct system prompt with patient-specific guardrails.
    """
    
    # Base template
    base_prompt = load_template("system_prompt_base.txt")
    
    # Risk-specific guidance
    risk_guidance = {
        "high_hba1c": "Patient has elevated HbA1c. Focus on medication adherence & lifestyle.",
        "high_bp": "Patient has elevated BP. Discuss sodium intake, exercise, stress.",
        "medication_gaps": "Patient is missing refills. Help identify barriers & schedule.",
        "no_recent_visit": "Patient hasn't seen provider recently. Encourage scheduling."
    }
    
    active_guidance = [risk_guidance[driver] 
                       for driver in patient_context["risk_flags"]]
    
    # Assemble final prompt
    final_prompt = base_prompt.format(
        patient_name=patient_context["first_name"],
        patient_risk_drivers=json.dumps(risk_drivers, indent=2),
        approved_docs_list=", ".join([d["source"] for d in approved_docs]),
        medical_history_summary=format_medical_history(patient_context),
        risk_specific_guidance="\n".join(active_guidance),
        care_manager_contact=patient_context["assigned_care_manager"],
        escalation_phone=URGENT_ESCALATION_NUMBER
    )
    
    return final_prompt
```

### Handling Edge Cases & Distress

Patients may disclose concerning information during the call. Here's how to respond:

#### Distress Detection & Response Matrix

| Scenario | Detection Trigger | Agent Response | Action |
|----------|-------------------|-----------------|--------|
| **Acute Medical Emergency** | Chest pain, severe breathing difficulty, stroke signs, severe bleeding | "This requires immediate emergency care. I'm calling 911 now." | Transfer call to 911 or nearest ER |
| **Mental Health Crisis** | Suicidal ideation, active self-harm, severe confusion | "I'm concerned about your safety. I'm connecting you to a crisis specialist right now." | Transfer to 988 (Suicide & Crisis Lifeline) or local crisis team |
| **Worsening Symptoms** | "I've been feeling much worse…", new symptoms reported | "Thank you for sharing that. I want our care team to evaluate this. I'm scheduling a call within 24 hours." | Escalate to care manager; create urgent task |
| **Medication Concern** | Patient reports side effects or confusion about meds | "I can't adjust your medications, but our care team can review this with your doctor." | Flag for pharmacist/provider review |
| **Abuse/Safety Issue** | Patient discloses abuse, neglect, or safety concern | "I'm concerned about your safety. I'm connecting you with resources." | Escalate per mandatory reporting rules (state-specific) |
| **Patient Frustration** | Angry tone, expressing hopelessness, barriers to care | "I hear your frustration. Let's work through this together." | Empathize, identify barriers, offer support |

#### Distress Detection Prompt Logic

```python
async def detect_distress(transcript_segment, emotion_score):
    """
    Monitor for concerning language/emotion during conversation.
    """
    distress_indicators = {
        "emergency_keywords": [
            "chest pain", "can't breathe", "stroke", "severe bleeding",
            "unconscious", "poisoned", "can't move"
        ],
        "mental_crisis_keywords": [
            "kill myself", "end it", "not worth living", "harm myself",
            "hearing voices", "severely confused", "panic attack"
        ],
        "concerning_symptoms": [
            "much worse", "can't control", "all the time", "spreading"
        ]
    }
    
    # Check for emergency keywords
    for keyword in distress_indicators["emergency_keywords"]:
        if keyword.lower() in transcript_segment.lower():
            return await escalate_to_911()
    
    # Check for mental crisis
    for keyword in distress_indicators["mental_crisis_keywords"]:
        if keyword.lower() in transcript_segment.lower():
            return await transfer_to_crisis_line(call_id)
    
    # Check emotion + wording for distress
    if emotion_score["distress"] > 0.7 and any(
        word in transcript_segment.lower() 
        for word in distress_indicators["concerning_symptoms"]
    ):
        return await escalate_to_care_manager(
            reason="patient_reported_worsening",
            priority="high"
        )
    
    return {"distress_detected": False}
```

### Compliance & Documentation

Every patient interaction must be logged for compliance and quality assurance.

#### Call Logging Structure

```json
{
  "call_id": "call_20260919_123456",
  "patient_id": "PT_123456",
  "session_timestamp": "2026-09-19T14:35:00Z",
  "call_duration_seconds": 480,
  "transcription": {
    "agent_turns": [
      {
        "turn_number": 1,
        "text": "Hi, this is your healthcare support agent…",
        "timestamp": "2026-09-19T14:35:05Z"
      }
    ],
    "patient_turns": [
      {
        "turn_number": 1,
        "text": "Hello, how are you?",
        "timestamp": "2026-09-19T14:35:12Z",
        "sentiment": "neutral",
        "distress_score": 0.1
      }
    ]
  },
  "documents_cited": [
    {
      "source": "Diabetes Management Guide v2.1",
      "approval_date": "2026-06-15",
      "timestamp_cited": "2026-09-19T14:36:45Z"
    }
  ],
  "tools_used": [
    {
      "tool_name": "schedule_appointment",
      "parameters": {"provider_id": "DR_789", "date": "2026-09-26"},
      "result": "appointment_id_456",
      "timestamp": "2026-09-19T14:38:20Z"
    }
  ],
  "escalations": [
    {
      "type": "care_manager_review",
      "reason": "patient_reported_high_blood_pressure",
      "priority": "normal",
      "assigned_to": "care_manager_ID",
      "timestamp": "2026-09-19T14:39:00Z"
    }
  ],
  "call_outcome": {
    "status": "completed",
    "next_steps": ["Schedule appointment", "Review medication adherence"],
    "patient_feedback": {"satisfaction": 4.5, "comment": "Very helpful"}
  },
  "compliance_flags": {
    "hipaa_compliant": true,
    "no_medical_advice_given": true,
    "appropriate_escalations": true,
    "manual_review_required": false
  }
}
```

---

## Action Execution (Tool Calling)

### Tool Architecture

Your agent needs to execute concrete business logic. Here's the design pattern:

#### Tool Taxonomy

| Category | Examples | Key Constraint |
|----------|----------|-----------------|
| **Scheduling** | schedule_appointment, schedule_lab_order, cancel_appointment | Always confirm with patient before booking |
| **Data Access** | get_patient_labs, get_medication_list, get_visit_history | Audit-log all access; patient should consent |
| **Escalation** | escalate_to_care_manager, escalate_to_pharmacist, escalate_to_physician | Include context; set priority; human approval required |
| **Preferences** | update_contact_preference, set_do_not_call, opt_out_program | Explicit patient consent; immutable audit trail |
| **Enrollment** | enroll_in_program, refer_to_resource, connect_to_specialist | Patient education first; voluntary enrollment |

#### Tool Definition Schema

```json
{
  "name": "schedule_appointment",
  "description": "Schedule an appointment with a provider or care manager.",
  "input_schema": {
    "type": "object",
    "properties": {
      "provider_id": {
        "type": "string",
        "description": "ID of the provider (care manager or PCP)"
      },
      "preferred_date": {
        "type": "string",
        "description": "ISO 8601 date (YYYY-MM-DD) or 'next_available'"
      },
      "visit_type": {
        "type": "string",
        "enum": ["phone", "video", "in_person"],
        "description": "Type of appointment"
      },
      "reason": {
        "type": "string",
        "description": "Chief complaint or reason for visit"
      },
      "patient_confirmed": {
        "type": "boolean",
        "description": "Patient explicitly agreed to this appointment"
      }
    },
    "required": ["provider_id", "visit_type", "reason", "patient_confirmed"]
  },
  "before_execution": [
    "ALWAYS confirm appointment details with patient before calling this tool",
    "Ensure patient_confirmed = true"
  ]
}
```

#### Safety Gates for Tool Execution

```python
class ToolExecutor:
    def __init__(self, audit_logger, compliance_checker):
        self.audit_logger = audit_logger
        self.compliance_checker = compliance_checker
    
    async def execute_tool(self, tool_name, parameters, context):
        """
        Execute a tool with safety gates.
        """
        
        # Gate 1: Check if tool is allowed for this patient
        if await self.compliance_checker.is_tool_blocked(
            patient_id=context["patient_id"],
            tool_name=tool_name
        ):
            return {
                "status": "blocked",
                "reason": "Tool not available for this patient",
                "message": "I'm unable to complete that action. Let me connect you with our team."
            }
        
        # Gate 2: Validate parameters
        schema = self.get_tool_schema(tool_name)
        validation = self._validate_params(parameters, schema)
        if not validation["valid"]:
            return {
                "status": "error",
                "reason": "Invalid parameters",
                "message": f"I encountered an error processing that request: {validation['error']}"
            }
        
        # Gate 3: Patient consent verification
        if schema["requires_consent"] and not parameters.get("patient_confirmed"):
            return {
                "status": "requires_confirmation",
                "message": "I need to confirm this action with you first."
            }
        
        # Gate 4: Check for sensitive operations
        if tool_name in ["update_contact_preference", "opt_out_program"]:
            await self._send_confirmation_sms(
                patient_id=context["patient_id"],
                action_summary=f"Confirm: {self._summarize_action(tool_name, parameters)}"
            )
        
        # Gate 5: Execute and log
        try:
            result = await self._execute_backend(tool_name, parameters)
            
            # Log for audit
            await self.audit_logger.log({
                "timestamp": now(),
                "patient_id": context["patient_id"],
                "tool_executed": tool_name,
                "parameters": self._sanitize_params(parameters),
                "result_status": result["status"],
                "session_id": context["session_id"]
            })
            
            return result
        
        except Exception as e:
            await self.audit_logger.log_error(
                patient_id=context["patient_id"],
                tool_name=tool_name,
                error=str(e),
                severity="high"
            )
            return {
                "status": "error",
                "message": "I encountered an error. Our team has been notified and will follow up."
            }
    
    def _sanitize_params(self, params):
        """Remove sensitive data before logging."""
        sensitive_fields = ["phone", "ssn", "credit_card"]
        sanitized = params.copy()
        for field in sensitive_fields:
            if field in sanitized:
                sanitized[field] = "[REDACTED]"
        return sanitized
```

### PBM Integration (Pharmacy Benefit Manager)

Pharmacy coordination is critical for medication adherence programs.

#### PBM Routing Logic

```python
async def route_to_pbm(patient_id, medication_concern):
    """
    Detect medication issues and route to appropriate PBM.
    """
    
    # Get patient's PBM from enrollment record
    patient = await db.get_patient(patient_id)
    pbm_id = patient.get("pbm_id")  # e.g., "CVS_Caremark"
    
    if medication_concern["type"] == "missing_refill":
        # Call PBM API to check refill status
        refill_status = await pbm_apis[pbm_id].check_refill_status(
            patient_id=patient["pbm_member_id"],
            medication=medication_concern["medication"]
        )
        
        if refill_status["can_refill"]:
            # Auto-request refill via API
            result = await pbm_apis[pbm_id].request_refill(
                member_id=patient["pbm_member_id"],
                medication=medication_concern["medication"],
                quantity=refill_status["qty_available"]
            )
            return {
                "status": "refill_requested",
                "pbm": pbm_id,
                "message": f"I've requested a refill of {medication_concern['medication']}. It should be ready at your pharmacy within 24 hours.",
                "tracking_id": result["request_id"]
            }
        else:
            # Escalate to PBM for authorization
            escalation = await pbm_apis[pbm_id].create_escalation(
                member_id=patient["pbm_member_id"],
                issue_type="refill_authorization_needed",
                medication=medication_concern["medication"],
                priority="normal",
                contact_method="api"
            )
            return {
                "status": "escalated_to_pbm",
                "pbm": pbm_id,
                "message": "I've sent a request to your pharmacy benefit manager. They'll follow up with you within 24 hours.",
                "tracking_id": escalation["ticket_id"]
            }
    
    elif medication_concern["type"] == "prior_authorization":
        # Create prior auth request in PBM system
        auth_request = await pbm_apis[pbm_id].create_prior_auth(
            member_id=patient["pbm_member_id"],
            medication=medication_concern["medication"],
            prescriber_id=medication_concern["prescriber_id"],
            clinical_justification=medication_concern["reason"]
        )
        
        return {
            "status": "prior_auth_submitted",
            "pbm": pbm_id,
            "message": "I've submitted a prior authorization request. Your doctor and pharmacy will be notified.",
            "tracking_id": auth_request["request_id"],
            "expected_turnaround": "1-2 business days"
        }
    
    return {"status": "no_action_needed"}
```

### Care Manager Escalation

High-touch interventions require human coordination.

#### Escalation Decision Tree

```python
def should_escalate_to_care_manager(context):
    """
    Determine if conversation warrants care manager follow-up.
    """
    
    escalation_triggers = {
        "medication_non_adherence": {
            "condition": context["patient"].missed_doses > 2,
            "priority": "normal",
            "action": "schedule_medication_review"
        },
        "barriers_to_care": {
            "condition": any(keyword in context["transcript"] 
                           for keyword in ["cost", "transportation", "insurance", "can't afford"]),
            "priority": "high",
            "action": "assess_social_determinants"
        },
        "no_recent_visit": {
            "condition": (now() - context["patient"].last_visit_date).days > 180,
            "priority": "normal",
            "action": "schedule_annual_visit"
        },
        "uncontrolled_condition": {
            "condition": context["patient"].lab_values.get("HbA1c", 0) > 8.0,
            "priority": "high",
            "action": "intensify_management"
        },
        "patient_expressed_concern": {
            "condition": context["emotion_score"]["worry"] > 0.6,
            "priority": "normal",
            "action": "supportive_follow_up"
        },
        "missed_appointment": {
            "condition": context["patient"].missed_appointments > 1,
            "priority": "normal",
            "action": "address_barriers"
        }
    }
    
    triggered_escalations = []
    for trigger_name, trigger_config in escalation_triggers.items():
        if trigger_config["condition"]:
            triggered_escalations.append({
                "trigger": trigger_name,
                "priority": trigger_config["priority"],
                "action": trigger_config["action"]
            })
    
    return {
        "should_escalate": len(triggered_escalations) > 0,
        "escalations": triggered_escalations,
        "assigned_care_manager": select_care_manager(context),
        "due_by": calculate_due_date(triggered_escalations)
    }

async def create_care_manager_task(patient_id, escalation_details):
    """
    Create an actionable task for care manager.
    """
    
    task = {
        "patient_id": patient_id,
        "created_at": now(),
        "due_date": escalation_details["due_by"],
        "priority": escalation_details["priority"],
        "action_items": [
            {
                "description": escalation_details["action"],
                "details": escalation_details.get("details"),
                "status": "pending"
            }
        ],
        "context": {
            "call_transcript_summary": escalation_details["transcript_summary"],
            "key_concerns": escalation_details["concerns"],
            "recommended_resources": escalation_details.get("resources", [])
        },
        "escalation_source": "voice_agent",
        "call_id": escalation_details["call_id"]
    }
    
    task_id = await db.create_care_manager_task(task)
    
    # Notify care manager
    await notify_care_manager(
        care_manager_id=escalation_details["assigned_care_manager"],
        task_id=task_id,
        patient_id=patient_id,
        priority=escalation_details["priority"]
    )
    
    return task_id
```

### Do-Not-Call (DNC) & Preference Management

Respect patient preferences and regulatory compliance (TCPA).

#### DNC Database Schema

```json
{
  "dnc_records": [
    {
      "patient_id": "PT_123456",
      "phone_number": "+1-555-0123",
      "dnc_status": "active",
      "reason": "patient_requested_on_2026-09-15",
      "expires_on": "2026-12-15",
      "created_at": "2026-09-15T10:30:00Z",
      "created_by": "voice_agent_session_123",
      "overrides": {
        "allow_urgent_medical": true,
        "allow_appointment_reminders": true
      }
    }
  ]
}
```

#### DNC Check & Respect Logic

```python
async def check_dnc_before_call(patient_id, call_type):
    """
    Verify DNC status before initiating outbound call.
    """
    
    dnc_record = await db.get_dnc_status(patient_id)
    
    if dnc_record is None:
        return {"allowed": True}
    
    if dnc_record["dnc_status"] == "permanently_requested":
        return {
            "allowed": False,
            "reason": "Patient has permanently requested no contact",
            "log_as_blocked": True
        }
    
    if dnc_record["dnc_status"] == "expires_on_date":
        if now() < dnc_record["expires_on"]:
            # DNC still active
            if call_type == "urgent_medical_issue" and dnc_record["overrides"]["allow_urgent_medical"]:
                return {
                    "allowed": True,
                    "reason": "Urgent medical override",
                    "log_as_override": True
                }
            else:
                return {
                    "allowed": False,
                    "reason": f"Patient DNC active until {dnc_record['expires_on']}",
                    "log_as_blocked": True
                }
        else:
            # DNC expired
            return {"allowed": True}
    
    return {"allowed": True}

async def handle_dnc_request(patient_id, phone_number):
    """
    Patient requests to be added to DNC list.
    """
    
    # Create DNC record
    dnc_record = {
        "patient_id": patient_id,
        "phone_number": phone_number,
        "dnc_status": "active",
        "reason": "patient_requested_via_call",
        "created_at": now(),
        "expires_on": now() + timedelta(days=90),
        "overrides": {
            "allow_urgent_medical": True,
            "allow_appointment_reminders": True
        }
    }
    
    await db.add_dnc_record(dnc_record)
    
    # Log for compliance
    await audit_logger.log({
        "event_type": "dnc_request",
        "patient_id": patient_id,
        "timestamp": now(),
        "source": "voice_agent"
    })
    
    return {
        "status": "success",
        "message": "I've added your number to our do-not-call list. You won't receive outbound calls from us, though we may still contact you about urgent medical issues or appointment confirmations."
    }
```

---

## End-to-End Integration & Compliance

### Full Call Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                  ML MODEL PREDICTION                         │
│         (Flags high-risk patient + top 5 drivers)           │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│               PRE-CALL PREPARATION (Async)                   │
│  • Validate patient (DNC, status, consent)                  │
│  • Retrieve approved documents (RAG)                        │
│  • Build system prompt + context                            │
│  • Cache in fast layer (Redis)                              │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│              VOICE CALL INITIATED                            │
│  • TTS: Agent greeting (low-latency path)                   │
│  • ASR: Capture patient response (streaming)                │
└─────────────────────────────────────────────────────────────┘
                            ↓
      ┌─────────────────────────────────────────────────────┐
      │       CONVERSATION LOOP (Until exit)                │
      │                                                     │
      │  1. ASR → Transcript                               │
      │  2. Emotion + Intent Detection                     │
      │  3. RAG Retrieval (if needed)                      │
      │  4. Tool Planning (if needed)                      │
      │  5. LLM Response Generation (streaming)            │
      │  6. TTS Synthesis (streaming)                      │
      │                                                     │
      │  [Distress Detected?]                              │
      │  ├─ Yes: Escalate (911, crisis, care mgr)          │
      │  └─ No: Continue conversation                      │
      └─────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│         POST-CALL EXECUTION & LOGGING                        │
│  • Execute tools (appointments, escalations, etc.)          │
│  • Log entire session (transcript, decisions, actions)      │
│  • Create care manager tasks if needed                      │
│  • Update patient profile + compliance log                  │
└─────────────────────────────────────────────────────────────┘
```

### HIPAA & Compliance Checklist

> ⚠️ **Legal Disclaimer:** This guide is for architectural reference only. Consult with legal and compliance teams before deployment. HIPAA violations carry significant penalties.

#### Key Compliance Areas

- **Patient Authorization:** Maintain documented consent for outbound calls (recorded affirmative consent, not pre-recorded messages)
- **Telephone Consumer Protection Act (TCPA):**
  - Respect Do-Not-Call registry + patient preferences
  - Identify agent as automated when applicable
  - Provide easy opt-out mechanism
- **HIPAA Encryption:**
  - All data in transit: TLS 1.2+
  - Data at rest: AES-256 encryption
  - Audio calls: HIPAA-compliant carriers (e.g., Twilio, Vonage with BAA)
- **Audit Logging:**
  - Log all PHI access with user, timestamp, action
  - Maintain logs for 6+ years
  - Implement tamper-evident storage (append-only logs)
- **Data Minimization:**
  - Only retrieve/store PHI strictly necessary for the call
  - Avoid storing full transcripts if not required; store summaries instead
  - Delete data after retention period expires
- **Patient Rights:**
  - Provide access to call recordings/transcripts upon request
  - Allow patient to correct health information
  - Honor patient opt-out (DNC) immediately
- **Breach Notification:**
  - If unauthorized access to PHI occurs, notify patient within 60 days
  - Report to HHS if affecting 500+ patients

#### Compliance Monitoring Code

```python
class ComplianceMonitor:
    def __init__(self, audit_db, alerting_service):
        self.audit_db = audit_db
        self.alerting_service = alerting_service
    
    async def monitor_daily(self):
        """Run daily compliance checks."""
        
        checks = {
            "dnc_list_updated": await self._check_dnc_list_currency(),
            "encryption_enabled": await self._verify_encryption_status(),
            "audit_logs_intact": await self._verify_audit_log_integrity(),
            "no_unconsented_calls": await self._check_call_consent_records(),
            "no_phi_in_logs": await self._scan_logs_for_exposed_phi()
        }
        
        failed_checks = [k for k, v in checks.items() if not v["passed"]]
        
        if failed_checks:
            await self.alerting_service.alert(
                severity="critical",
                subject=f"Compliance Check Failed: {', '.join(failed_checks)}",
                details=checks
            )
        
        # Log compliance check results
        await self.audit_db.log_compliance_check(checks, timestamp=now())
    
    async def _check_dnc_list_currency(self):
        """Verify DNC list is updated from FCC registry."""
        last_update = await self.audit_db.get_dnc_last_update()
        if (now() - last_update).days > 7:
            return {"passed": False, "reason": "DNC list not updated in 7+ days"}
        return {"passed": True}
    
    async def _verify_encryption_status(self):
        """Check all data connections use TLS 1.2+."""
        connections = await self._get_active_connections()
        for conn in connections:
            if conn["tls_version"] < "1.2":
                return {"passed": False, "connection": conn["name"]}
        return {"passed": True}
    
    async def _verify_audit_log_integrity(self):
        """Verify logs have not been tampered with."""
        # Check for gaps, overwrites, deletions
        integrity = await self.audit_db.verify_integrity()
        return {"passed": integrity["valid"]}
```

### Deployment Architecture

Recommended stack for production:

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| **Voice Infrastructure** | Twilio + Telnyx (with BAA) | HIPAA-compliant, redundant, high availability |
| **ASR (Speech-to-Text)** | Deepgram / Google Cloud Speech + on-prem fallback | Low latency, handles medical terminology |
| **TTS (Text-to-Speech)** | ElevenLabs (HIPAA compliant) or Azure Cognitive Services | Natural voice, streaming support |
| **LLM Agent** | Claude API (with system prompts) + fine-tuned fallback | High reasoning, cost-effective, safety-oriented |
| **Vector DB (RAG)** | Pinecone / Weaviate (self-hosted option for data control) | Fast retrieval, metadata filtering, compliance |
| **Caching Layer** | Redis (self-hosted + replicated) | Sub-100ms latency, pre-loaded context |
| **Database** | PostgreSQL (encrypted at rest) + warm standby | ACID compliance, audit logging, reliability |
| **API Gateway** | Kong / AWS API Gateway | Rate limiting, auth, logging |
| **Monitoring & Alerts** | Datadog / New Relic + PagerDuty | Real-time system health, incident response |

### Next Steps & Roadmap

1. **Phase 1 (MVP):** Build core voice agent with single-threaded conversation, basic escalation to care managers
2. **Phase 2:** Add RAG system; integrate with electronic health records (EHR) for patient context
3. **Phase 3:** Multi-turn conversation optimization; distress detection; tool execution for appointments
4. **Phase 4:** PBM integrations; full compliance audit; pilot with subset of patients
5. **Phase 5:** Scale; add specialist routing; monitor real-world outcomes

---

## Summary

✓ **You now have:** A production-ready architecture for a HIPAA-compliant healthcare voice agent with safety guardrails, RAG integration, and business logic automation.

Use this guide as a blueprint for your implementation. Consult with your compliance and legal teams before deploying to production.
