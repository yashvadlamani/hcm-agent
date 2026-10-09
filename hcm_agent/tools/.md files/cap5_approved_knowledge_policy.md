# Capability 5 — Approved knowledge & policy

Last reviewed: 2026-10-08

After identity verification, the care-management LLM can select these typed LangChain tools.
LangGraph runs selected tools through its `ToolNode` and scoped gateway; the LLM reviews retrieval
results before answering. See [`catalog.py`](catalog.py) and
[`member_care.py`](../workflows/member_care.py).

| Tool | Service and current status | Definition and retrieval implementation |
|---|---|---|
| `search_diabetes_playbook` | Active local RAG prototype. Clara's LLM selects the tool and forms the query; LangChain retrieves relevant Chroma chunks. Optional extra LLM query expansion is disabled by default for phone-call latency. The playbook is a draft pending clinical review, not an approved protocol. Medication advice is prohibited. | Handler: [`domains.py`](../domains.py); family: [`catalog.py`](../catalog.py); RAG retrieval: [`playbook.py`](../playbook.py) |
| `lookup_policy` | LangChain PDF retrieval over the supplied 2025 PDF using FastEmbed embeddings and Chroma. For out-of-pocket-limit questions, the tool extracts returned table values into a source-bound exact-answer field, so Clara does not improvise figures. Optional extra LLM query expansion is disabled by default for phone-call latency. | Handler: [`domains.py`](../domains.py); family: [`catalog.py`](../catalog.py); PDF loading/chunking: [`policy.py`](../policy.py) |

## Diabetes playbook RAG

The playbook at [`data/playbooks/diabetes_quick_care_playbook.md`](../../data/playbooks/diabetes_quick_care_playbook.md)
is chunked with LangChain's Markdown and recursive character splitters (1,400 characters with
200-character overlap). FastEmbed creates local `BAAI/bge-small-en-v1.5` embeddings; Chroma stores
the persistent vector index under `data/vectorstore/diabetes-playbook` by default. Rebuild after
editing it with `clara-playbook-index --rebuild`; set `CLARA_PLAYBOOK_VECTOR_DIR` for another
location. Embeddings run locally. The graph LLM selects the tool and supplies its retrieval query;
set `CLARA_RAG_QUERY_EXPANSION=1` only when an additional MultiQueryRetriever model call is worth
the added latency. Retrieved
passages include CDC source links. The playbook is a draft, not an approved clinical protocol.

## Policy PDF RAG

The separate policy index uses [`data/policies/sbc-gpsd69bceiilo-il-2025.pdf`](../../data/policies/sbc-gpsd69bceiilo-il-2025.pdf)
directly (no manifest). It uses LangChain `PyPDFLoader` and a recursive splitter with 1,400-character
chunks and 200-character overlap. FastEmbed creates local `BAAI/bge-small-en-v1.5` embeddings; Chroma
stores the index in `data/vectorstore/plan-policy`. Run `clara-policy-index --rebuild` after replacing
or updating the PDF; set `CLARA_POLICY_VECTOR_DIR` to change the index directory. Retrieved answers
should cite the source page. Set `CLARA_RAG_QUERY_EXPANSION=1` only to enable a second LLM-based
query-expansion request. The application does not establish whether the PDF is approved by the
plan owner.

The uploaded PDF is a Blue Cross and Blue Shield of Illinois Summary of Benefits for Blue Choice
Preferred Gold PPO 901, covering 2025-01-01 through 2025-12-31. Clara must not assume the caller is
enrolled in that plan or present its 2025 terms as current coverage. If no relevant passage is
retrieved, Clara should say she cannot confirm the answer from this document and direct the caller to
their plan.

## Example questions for `lookup_policy`

| Patient asks Clara | What Clara can do with the retrieved passage |
|---|---|
| “What deductible does this plan summary list?” | Summarize the listed deductible amounts and cite the PDF page; clarify that the document covers 2025. |
| “What does the summary say I pay for a specialist visit?” | Look up the specialist-visit cost-sharing entry and explain only what the passage says. |
| “Does this summary say anything about an emergency room visit?” | Retrieve the emergency-room section and summarize its stated cost-sharing and conditions. |
| “Where can I get the full details of this coverage?” | Retrieve the instructions for finding complete plan terms; don’t treat the summary as the full contract. |

## Boundaries

- Capability 5 contains only `search_diabetes_playbook` and `lookup_policy`.
- The playbook and policy PDF use separate indexes and must not be treated as interchangeable sources.
- Never invent missing policy facts, guarantee coverage, or provide medication advice.
- Capabilities 1–4 and 6–8 remain intact.

## LangGraph integration

`build_tools` creates the decorated tools in [`catalog.py`](../catalog.py); their execution
receives the LLM-selected query through LangGraph runtime state. Optional query expansion is
explicitly enabled only with `CLARA_RAG_QUERY_EXPANSION=1`.
The care workflow passes tools and server-bound state in [`member_care.py:54`](../workflows/member_care.py#L54);
`LangChainLLM` starts the graph in [`llm.py:39`](../agent/llm.py#L39). Graph state is declared at
[`graph.py:14`](../workflows/graph.py#L14), the model binds tools at [`graph.py:28`](../workflows/graph.py#L28),
and `ToolNode` executes calls at [`graph.py:34`](../workflows/graph.py#L34).
