# Identity verification: current flow and test plan

## Current matching behavior

The live flow is **LLM-assisted extraction and classification, followed by deterministic
credential checks**. GPT does not make the final name-match decision today.

1. Clara passes the caller's answer to `verify_identity_turn` in `hcm_agent/agent/identity.py`.
2. GPT receives the spoken answer and, for the name step, the expected name from the
   server-selected member record. The prompt asks GPT to extract only what was said and
   classify it as `exact`, `first_name`, `phonetic`, or `mismatch`.
3. LangChain wraps the identity verifier as a tool; LangGraph requires the tool call and
   then asks GPT to review the result (`hcm_agent/agent/llm.py` and
   `hcm_agent/workflows/graph.py`).
4. The expected name/DOB is bound server-side in `verify_identity_turn`; it is not accepted
   from model-generated tool arguments. `hcm_agent/tools/identity.py` makes the actual
   deterministic decision. The call proceeds only if both the tool and model review pass.

### Name rules

- Names are Unicode-normalized, case-folded, and stripped of a few common spoken prefixes.
- `exact`: normalized provided name must equal the normalized stored name.
- `first_name`: a single provided name is allowed for the name step if it exactly equals
  the stored first name; DOB is still required afterward.
- `phonetic`: GPT must select this mode. The Python tool then requires the same number of
  name parts (or an allowed first-name-only answer), the same first letter for each part,
  and `difflib.SequenceMatcher` similarity of at least **0.75 (75%)** for every part.
- A mismatch, contradictory answer, invented extraction, or failed DOB check ends the call.

This boundary was chosen to stop an LLM from overriding failed verification, not mainly
to reduce latency. The tradeoff is that the fixed 75% string heuristic can reject plausible
ASR spellings, and it does not measure pronunciation. The plan is LLM-assisted name
adjudication with structured output and adversarial tests, while keeping the member record
server-bound and retaining deterministic exact DOB comparison. The LLM must not invent
unstated name parts or override a failed credential/policy check.

### DOB rules

GPT extracts a complete date and returns it as `YYYY-MM-DD`. The verifier accepts several
numeric and month-name formats, normalizes them to ISO form, requires a valid date from
1900 through today, and compares it exactly with the stored DOB. Missing/unclear date
components are not guessed; fuzzy DOB matching is not used.

## Relevant code

- `hcm_agent/agent/conversation.py`: starts name verification, then DOB, and ends the call
  when a step fails.
- `hcm_agent/agent/identity.py`: GPT instructions, server-side binding of expected values,
  and combined tool/model pass decision.
- `hcm_agent/agent/llm.py`: converts the verifier to a LangChain tool and runs tool/review.
- `hcm_agent/workflows/graph.py`: bounded LangGraph model → tool → model loop.
- `hcm_agent/tools/identity.py`: normalization and deterministic name/DOB rules, including
  the 0.75 phonetic threshold.
- `hcm_agent/workflows/member_data.py`: selects a member record before the call.
- `data/demo_members.json`: local demo dataset; it contains a record named Himanshu Gupta
  and is classified in the file as synthetic demo data with one user-provided profile.

## Suggested test sequence

Start offline and do not place an ACS call:

1. Run the five focused LangGraph migration checks:
   `.venv/bin/python -m pytest tests/test_langgraph.py -q`
   These use a scripted local model, not Azure/OpenAI API calls.
2. If changing identity logic, select no more than five focused cases from
   `tests/test_identity.py`: exact name, first-name-only then mandatory DOB, valid
   phonetic spelling, invented/contradictory name rejection, and wrong DOB rejected even
   when the model approves. Keep parameterized expansions within the five-case project
   test limit.
3. For a manual terminal check, use `clara-chat interactive` with a synthetic-only test
   member, and confirm the transcript masks the spoken name/DOB. Test a correct name then DOB,
   a wrong DOB, a first-name-only answer, and an ambiguous name. The CLI uses the configured
   LLM provider for these turns, so it can consume Azure/model quota; do not use a real
   phone call or real member record for exploratory tests.
4. Only after offline results look right, consider a controlled ACS call to an explicitly
   authorized test number, with consent and a test record. ACS calls and live-model turns
   can incur charges and should not be part of routine tests.

The local demo data includes a matching name record, but treat it as test data—not proof
of identity. Avoid copying its DOB/phone into transcripts, screenshots, or logs.
