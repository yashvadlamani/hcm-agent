# Roadmap

Where Clara is today, what comes next, what's needed before calling real patients, and how the project got here.

## Where we are

**Stage: working prototype on Azure.** Clara holds real phone conversations from an Azure Communication Services number, with guardrails and emergency handling, using test data and verified test phones only.

| Area | Built | Next |
|---|---|---|
| Phone calls | ACS calls, Azure neural voice and speech recognition | Purchased number, branded caller ID |
| Conversation | Personalized replies, guardrails (including no promises), clinical emergency detection, natural endings, live sentiment | Answers grounded in approved clinical content (RAG) |
| Starting calls | JSON upload → Azure Function, allow-list, hourly limit | Patient eligibility: consent, Do-Not-Call, calling hours |
| After the call | Transcript and summary in the server log, live dashboard, feedback-form opt-in recorded | Text the feedback form (needs an SMS-capable number), stored call records, care-manager escalation |
| Platform | App Service, Functions, Key Vault, CI and automatic deploys | Always-on hosting, shared call state, monitoring and alerts |
| Compliance | Test data only | BAA, audit logging, clinical and legal review |

## Next milestones

1. **Pilot readiness**
   - **Eligibility checks** instead of the test allow-list: consent on file, internal and national Do-Not-Call lists, calling hours (8 AM to 9 PM in the patient's time zone) and frequency limits.
   - **A purchased local number** with branded caller ID, which needs a pay-as-you-go subscription. With text messaging enabled, Clara can then send the feedback form patients ask for; today their answer is only recorded.
   - **Always-on hosting** (App Service Basic or higher).
   - **Encrypted call records**, instead of only log entries.
2. **Scheduled callbacks**
   - Turn the "good time to reach the patient" that Clara notes today into a scheduled call: parse the time, respect calling hours, and place the call automatically.
3. **Care-team integration**
   - Care-manager escalation and follow-up tasks; Clara only offers these today.
   - An emergency notification to the care manager.
   - A call summary per patient.
4. **Smarter conversations**
   - Grounded answers (RAG) from approved clinical documents.
   - Streaming audio to a realtime model for faster turns.
   - Custom speech recognition for drug names and conditions.
5. **Production**
   - Compliance audit, monitoring and alerting, scale-out with shared call state.
   - The broader capabilities in the [target design](./target-design.md): ML-triggered outreach, PBM refill routing and scheduling.

## Path to real patient calls

Only the free trial number is limited to verified numbers. A purchased ACS number can call any phone. Before real patients are involved, all of these must be in place:

| Area | Required |
|---|---|
| **HIPAA** | A Business Associate Agreement (BAA) with Microsoft covering ACS, App Service, Functions, Key Vault and Azure OpenAI, on a paid subscription. A BAA with Anthropic too, if Claude is used |
| **Consent and calling rules** | Automated or AI-voice calls to cell phones generally need prior consent (TCPA), with a limited, strict healthcare exception. Compliance and legal teams must sign off |
| **Eligibility checks** | Consent, Do-Not-Call and calling-hour checks before every call (milestone 1) |
| **Security** | Validate ACS's signed event tokens; company sign-in (Microsoft Entra ID) for the dashboard; encrypted call records with audit logging |
| **Reliability** | Always-on hosting; alerts for failed calls |
| **Clinical review** | Prompts, guardrails and emergency handling reviewed by clinical and compliance teams |

## History

Notable changes, newest first.

**2026-10-02: Sentiment measures satisfaction with the call**
- The live score now tracks how satisfied the patient seems with the call at each moment. Calmly describing a hard situation is neutral; frustration with the call lowers it and feeling heard or helped raises it.

**2026-10-02: Personal conversations and a reason for each call**
- **Reason for the call:** a call request can say what the call is `for`, such as diabetes management, likelihood of high cost, medication adherence, readmission risk, care gaps or free text. It sets Clara's opening and what she explores. The care team's label is never said to the patient.
- **Personal replies:** Clara now builds each reply on what the patient just said, remembers the call, raises the patient's risk drivers one at a time in everyday words, and avoids stock sympathy lines.
- **Guardrails block less:** medical-advice and medication-change checks now fire only when Clara tells the patient what to do, not when she asks or talks about medication, food or routines.
- Clara no longer assumes default risk drivers when a request has none, and says goodbye with the first name only.
- Fixed: replies using curly apostrophes ("I’ll make sure…") could slip past the promise guardrail.

**2026-10-01: Smarter conversations**
- **No promises:** the prompt and a new guardrail stop Clara from promising to connect, transfer, schedule, send or arrange anything.
- **Emergencies from context:** the model judges every turn with clinical knowledge, such as low blood sugar, DKA, stroke or heart signs, and suicidal thoughts. Keywords stay as an instant safety net, and a self-harm block by Azure's content filter is treated as a crisis. Mental-health crises get the 988 crisis line.
- **Identity check first:** Clara asks for the patient by name and says nothing health-related until they confirm. If someone else answers, she asks for a good time to reach the patient and notes it. Wrong numbers end politely.
- **Natural endings:** "anything else?" → no → feedback-form question → goodbye. Saying goodbye leads to the same closing.
- **Feedback form opt-in:** Clara asks and records yes or no; sending the text comes later.
- **Live sentiment:** 0–1, starting neutral, updated every turn on the dashboard with a trend line.
- **Faster first turn:** a shared model connection and a warm-up while the greeting plays.
- Fixed: "Can someone help me…" was wrongly treated as an emergency keyword.

**2026-10-01: Azure Communication Services and a cleaner repository**
- Calls moved from Twilio to **Azure Communication Services**, putting the whole system in Azure and removing the Twilio-era workarounds.
- The repository was restructured: one `hcm_agent/` folder holding the app, the Azure Function and the deploy scripts, plus six focused docs.
- Added the workflow diagram and a sample call request. The `incoming/` upload folder now stays visible.

**2026-10-01: Secrets and automatic deploys**
- All deployed secrets moved to **Azure Key Vault**, read through managed identities.
- The server and the function now **deploy automatically** on merge to `main`, after lint and tests pass.
- Fixed: calls started by the function failed when risk drivers contained characters such as `%`.

**2026-09-30: Azure deployment and call requests**
- The Clara server runs on **Azure App Service**, with deploy, start and stop scripts.
- **Azure OpenAI** (`gpt-5-mini`) was added as a model option alongside Claude.
- **Call requests by file upload:** a JSON file triggers an Azure Function that validates it and places the call.
- **Live call dashboard**, an installable package with `clara-*` commands, and CI on every push.

**2026-09-28: First working phone conversations**
- Phone conversation server with guardrails on every reply and emergency detection.
- The assistant was renamed from "Guppy" to **Clara**.

**2026-09-19: Prototype**
- Conversation agent with safety guardrails, and the long-term [target design](./target-design.md).
