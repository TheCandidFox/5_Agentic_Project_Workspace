# CONTEXT_AND_MEMORY.md

## 1. Purpose, Scope, and Governing Decisions

This module defines the practical context, retrieval, and durable-memory architecture for the multi-model agent system. It covers:

- durable state and memory,
- context assembly and compaction,
- code-aware retrieval and Graphify,
- RAG, vectors, embeddings, and provider-native file retrieval,
- graph retrieval and GraphRAG,
- MCP as a tool-access protocol,
- prompt caching,
- workload-specific retrieval enforcement and verification.

The system’s primary goal remains immutable unless the user explicitly approves a goal change. Retrieval and memory may support relevant edge-case investigation, scope clarification, and follow-on work only when those actions improve the existing approved goal.

### Core decisions

1. **The application-owned database and artifact store are the system of record.** Provider conversations, file stores, vector stores, prompt caches, managed-agent sessions, and model memories are disposable accelerators, not canonical state.

2. **Retrieval is workload-specific.** Code should not be retrieved like research documents; spreadsheets should not be retrieved like prose; live integrations should generally be queried through governed tools rather than copied into a vector database.

3. **Retrieval use is enforced by workflow policy, not trusted to model discretion.** A model may be capable of invoking a search tool, but evidence-required tasks must not be accepted unless the required retrieval evidence is present and verified.

4. **The value architecture does not deploy a permanent vector database or GraphRAG system by default.** Those are optional additions that need measured specialty value.

5. **Graphify is a pilot, not a default dependency.** It is promising for code graph navigation, but its benefits, egress behavior, and accuracy must be replicated on the user’s repositories.

6. **MCP standardizes access to tools; it is neither a retrieval algorithm nor a security boundary.** All MCP servers operate behind the system’s policy gateway.

---

## 2. Durable Memory and Context Model

### 2.1 Canonical memory layers

The system maintains four distinct layers. They must not be conflated.

| Layer | Purpose | Canonical location | Retention behavior |
|---|---|---|---|
| **Authoritative task state** | Goals, task graph, approvals, budgets, status, dependencies, acceptance criteria, stop conditions | Postgres-backed task ledger | Retained according to project lifecycle policy |
| **Immutable artifacts** | Source files, tool outputs, code patches, research captures, generated documents, test reports, spreadsheet extracts | Encrypted object storage or versioned project storage | Versioned and linked by content hash |
| **Working context** | Current task packet supplied to a model | Constructed per call; optionally provider-cached | Ephemeral; never canonical |
| **Derived memory/indexes** | Summaries, embeddings, AST indexes, Graphify graph artifacts, vector indexes, entity graphs | Rebuildable index store or project artifact store | Must reference source version/hash and be deletable/rebuildable |

For deployed multi-machine operation, the authoritative ledger is Postgres-class storage, with object storage for large artifacts. SQLite plus structured local files is permitted only for local, single-worker development. This resolves the apparent prototype convenience of SQLite against the stronger multi-day, multi-machine requirement: SQLite is a development implementation, not the deployed architecture.

### 2.2 Memory record types

Each project should maintain structured records rather than a single opaque “memory” prompt:

- **Goal record:** approved goal text, goal version, owner, constraints, and human approval history.
- **Task record:** task description, parent task, status, acceptance criteria, stopping conditions, retrieval policy, sensitivity class, and budget.
- **Decision record:** decision, alternatives considered, evidence references, confidence, owner, and reversal conditions.
- **Artifact record:** object URI, content hash, source/provider/tool, timestamp, sensitivity class, and parent task.
- **Evidence record:** source URL or artifact hash, retrieved excerpt/range, retrieval method, freshness date, and claim linkage.
- **Run summary:** compact factual state for resumption: completed work, unresolved questions, failed attempts, current next action, constraints, and artifact pointers.
- **Operational record:** model/provider/version requested, effective model if available, token/tool usage, cost estimate and actuals, error class, retry state, and cache status.

Model-generated summaries are useful derived memory but are never allowed to overwrite the goal, approval state, raw artifacts, or evidence ledger.

### 2.3 Context packet construction

Every model call receives a bounded, versioned context packet rather than an unbounded conversation history.

Recommended packet order:

1. Stable system policy and role instructions.
2. Approved goal and non-negotiable constraints.
3. Current task, acceptance criteria, stopping condition, and budget envelope.
4. Relevant structured state: decisions, unresolved issues, prior failures, and tool permissions.
5. Retrieval evidence selected for this task.
6. Compact run summary.
7. Recent turn/tool trace only when necessary.
8. Explicit required output schema.

The packet must include artifact IDs, source hashes, and retrieval provenance rather than copying large raw material repeatedly. A model may request further retrieval through approved tools, but it must not infer that omitted material has been read.

### 2.4 Context budget hierarchy

When context approaches a model or budget limit, preserve information in this order:

1. Approved goal, safety policy, acceptance criteria, and approval constraints.
2. Current task and side-effect status.
3. Structured decisions and evidence references.
4. Exact code spans, spreadsheet ranges, or source excerpts necessary for the active task.
5. Recent tool outputs.
6. Narrative discussion history.

Raw artifacts remain externally available. Compaction may remove prose from the packet, but it must retain references to the original artifacts and the fact that the omitted detail remains retrievable.

---

## 3. Retrieval Architecture by Workload

### 3.1 Retrieval policy classes

Every task receives one of the following retrieval policies at planning time:

| Policy | Use case | Required evidence |
|---|---|---|
| `NONE` | Pure transformation of supplied content; isolated code formatting; internal planning | No external evidence required |
| `OPTIONAL` | Brainstorming, low-risk drafting, non-factual ideation | Retrieval may help but is not required |
| `GROUNDED` | Document generation, code modification, spreadsheet analysis, internal knowledge questions | Relevant artifacts or source ranges required |
| `CITATION_REQUIRED` | Web research, factual comparison, policy/security claims, vendor evaluation | Source URLs/artifact references and claim linkage required |
| `LIVE_TOOL_REQUIRED` | Automations, current system state, account/configuration checks | Governed tool result required; cached or remembered values are insufficient |

The planner sets the policy. A downstream model cannot downgrade it.

### 3.2 Coding and software retrieval

Coding is the highest-priority workload and uses a layered retrieval path:

1. **Tier 1 — deterministic retrieval:** repository file search, lexical search, symbol lookup, AST parsing, dependency metadata, test discovery, and version-control history.
2. **Tier 2 — code graph traversal:** call paths, imports, references, inheritance relationships, and source-derived dependencies.
3. **Tier 3 — semantic retrieval:** architecture decision records, READMEs, issues, comments, design documents, and natural-language code explanations.
4. **Tier 4 — live verification:** tests, linting, type checking, build execution, runtime inspection, and targeted tool output.

For code changes, “retrieval complete” is not sufficient by itself. The acceptance gate must require:

- identified files and symbols,
- source-derived evidence for the claimed change location,
- applicable tests or an explicit reason tests cannot be run,
- resulting patch artifact,
- test/build results where tooling is available.

A code model must not claim that a symbol, call path, or behavior exists solely from a semantic embedding match when deterministic source inspection is available.

### 3.3 Research and web investigation retrieval

Research tasks use a source-first workflow:

1. Create a claim list from the task.
2. Retrieve primary sources where practical: official documentation, original studies, official pricing pages, vendor terms, product specifications, or direct filings.
3. Store URLs, capture timestamps, relevant excerpts, and source confidence.
4. Distinguish:
   - provider claim,
   - independently corroborated fact,
   - inference,
   - unresolved uncertainty.
5. Require cited evidence for every material externally verifiable claim in the final output.

Research outputs must include a source/evidence manifest. If sources conflict, the model must describe the conflict rather than average it into a false certainty. Time-sensitive pricing, data-retention, rate-limit, and product-availability claims require implementation-time re-verification before becoming production controls.

### 3.4 Spreadsheet and structured-data retrieval

Spreadsheet and structured-data tasks should prefer direct, inspectable access over text chunking:

- retrieve workbook/sheet metadata,
- inspect relevant table ranges, headers, formulas, named ranges, and data types,
- use SQL, dataframe, or spreadsheet tooling for calculations,
- preserve exact cell/range references for findings,
- store derived tables and calculation scripts as artifacts.

Embedding rows from a spreadsheet is not the default method for answering numerical or formula questions. Vector retrieval may help locate explanatory notes or comments, but calculations and factual values must come from structured tool output.

### 3.5 Document generation and document-grounded work

For document generation, use retrieval based on the nature of the source set:

- small, stable source set: attach selected documents directly or use a temporary provider-managed file-search store;
- larger document corpus: use owned semantic retrieval only after the need is demonstrated;
- sensitive or portable corpus: retain originals and metadata in the owned artifact store, treating provider storage as a disposable serving cache.

Document-grounded output must identify which source artifacts supported important assertions. For legal, policy, financial, or externally distributed documents, unsupported factual claims fail acceptance.

---

## 4. RAG, Vector Retrieval, and Embeddings

### 4.1 Baseline RAG design

RAG is an optional retrieval mechanism, not a mandatory memory layer. Its role is to select relevant unstructured content that cannot be efficiently found through deterministic code, database, or file operations.

A valid RAG result must preserve:

- source artifact ID and version/hash,
- chunk boundaries and parent document,
- section/page/location metadata where available,
- access-control/sensitivity metadata,
- retrieval score and method,
- optional reranker score,
- retrieved timestamp.

Embedding similarity alone is insufficient evidence. The model must receive the actual retrieved excerpt or structured source range, not merely a vector similarity score.

### 4.2 Value architecture: minimal vector use

For the approximately $150/month value architecture:

- do **not** run a permanent, separately hosted vector database by default;
- use lexical search, AST/symbol indexing, and direct structured tools first;
- use temporary provider-native file retrieval for bounded document tasks where permitted by the data policy;
- use a small local or project-scoped semantic index only if the empirical evaluation proves repeated document retrieval value;
- expire or rebuild provider-managed indexes rather than treating them as durable memory.

OpenAI’s managed vector stores and `file_search` provide managed semantic search with chunking and metadata controls, but are provider-specific and must be treated as disposable caches. Research indicates the model may decide whether to invoke hosted file search, so required retrieval must be invoked deterministically or verified after the call.

Anthropic’s Files API should not be treated as equivalent managed semantic retrieval. It is a persistent file-reference mechanism; semantic retrieval should be supplied externally through retrieved content, including supported `search_result`-style citation blocks where applicable.

### 4.3 Quality-max architecture: owned retrieval index

The quality-max architecture may add an owned vector index, such as a Postgres/pgvector-class or dedicated vector service, when the evaluation demonstrates a material gain for research or document workloads.

The owned index must be built from canonical source artifacts and maintain:

- source-to-chunk lineage,
- deletion propagation by source ID,
- embedding-model version,
- chunking-policy version,
- ACL/tenant metadata,
- evaluation dataset and retrieval metrics.

The raw corpus is portable; the working index is not fully portable. Migration requires rebuilding embeddings, chunking, metadata rules, reranking configuration, and access controls. This operational cost is why an owned index is deferred in the value architecture.

### 4.4 Embedding model selection

Embeddings are implementation details chosen by empirical retrieval quality and operating cost, not by generic benchmark claims. The evaluation should compare:

- lexical baseline,
- lexical plus AST/symbol search for code,
- semantic retrieval,
- hybrid lexical + semantic retrieval,
- optional reranking.

Measure recall of required evidence, precision of returned evidence, downstream acceptance rate, latency, and cost. A higher embedding benchmark does not automatically improve the user’s code or research tasks.

---

## 5. Graphify, Graphs, and GraphRAG

### 5.1 Graphify decision

Graphify is a real, active, code-focused local-first CLI/skill that uses Tree-sitter AST parsing to build queryable code graph artifacts. It supports coding-agent environments and can operate through MCP. Its core code parsing path is deterministic and local.

However, Graphify is **not adopted as default infrastructure yet**.

Reasons:

- its benchmark evidence is project-authored and based on a small sample;
- more than one project uses the Graphify name, creating version/name ambiguity;
- its non-code semantic pipeline may invoke an LLM or embedding backend;
- headless operation may auto-detect credentials unless the backend is explicitly pinned;
- inferred graph edges are useful hypotheses, not source-level proof.

### 5.2 Graphify pilot requirements

Before Graphify is used on non-public repositories:

1. Pin the exact repository, commit, release, parser version, and configuration.
2. Enforce code-only mode unless semantic processing is explicitly approved.
3. Pin any LLM/embedding backend; disable credential auto-detection.
4. Perform network monitoring or equivalent logging to verify that code-only mode makes no unexpected external calls.
5. Compare Graphify against:
   - grep/file search,
   - AST/symbol lookup,
   - direct file reading,
   - optionally a semantic code/document layer.
6. Measure precision, recall, developer acceptance, indexing time, query latency, and maintenance cost on 2–3 representative repositories.

Graphify may be adopted for large, repeatedly queried repositories only if it improves accepted coding-task outcomes enough to justify its integration and maintenance cost.

### 5.3 Knowledge graphs and GraphRAG

GraphRAG is excluded from the value architecture by default.

It is suitable only when all of the following are true:

- the corpus is large and relatively stable;
- the questions are genuinely global, thematic, or multi-hop;
- baseline hybrid retrieval has demonstrably missed the required answer quality;
- graph extraction cost is explicitly budgeted;
- source-to-entity and source-to-summary provenance are retained;
- deletion propagation can remove derived graph data when source material is deleted.

Microsoft’s GraphRAG documentation frames graph approaches around aggregate and multi-hop questions, not as a universal replacement for standard retrieval. Its graph extraction process also adds substantial indexing cost. Therefore, GraphRAG is an opt-in quality-max capability for bounded research corpora, usually built in a background or batch process, not a per-query default.

For code, AST/call graphs are more appropriate than LLM-extracted knowledge graphs for source-level relationships. For research, entity graphs may help synthesis but must preserve the distinction between extracted source facts and inferred relationships.

---

## 6. MCP Retrieval and Tooling Controls

MCP is adopted as the interoperability protocol for retrieval and tool access, not as a trust boundary.

Every MCP server must be registered in a policy-controlled inventory containing:

- server identity, owner, version, and pinned endpoint;
- first-party versus third-party status;
- authentication method and credential scope;
- read, write, destructive, and external-communication capabilities;
- data-retention policy;
- allowed sensitivity classes;
- egress destinations;
- approval requirements.

The policy gateway enforces:

- server allowlists,
- per-tool scopes,
- scoped credentials from a vault or environment-specific secret store,
- tenant/workspace restrictions,
- read/write/destructive action classification,
- request logging and idempotency keys where tools support them,
- human approval for irreversible actions, external publication, credential changes, purchases, and sensitive-data exports.

Retrieved MCP output is untrusted input. It can contain prompt injection, malicious instructions, or misleading content. The model must treat tool output as data, not authority to change policies, goals, or credentials.

---

## 7. Prompt Caching, Compaction, and Cost Control

### 7.1 Prompt caching

Prompt caching is conditionally adopted. It is useful only when a stable prefix is reused frequently enough within the provider’s applicable cache window.

Stable cache candidates:

- system policy,
- output schemas,
- tool schemas,
- repository map summaries,
- repeated project constraints,
- static evaluation rubrics.

Volatile content should remain outside the cached prefix:

- current task state,
- recent tool results,
- retrieved web content,
- timestamps,
- variable user data,
- dynamic tool availability.

Both OpenAI and Anthropic document cache-read discounts, but also document cache-write costs and TTL constraints. The exact economics differ by provider/model and can be negative for low-reuse prompts. The router must record per template:

- uncached input tokens,
- cache-write tokens,
- cache-read/hit tokens,
- hit ratio,
- measured cost with and without caching,
- latency impact,
- invalidation cause.

Caching becomes default for a template only after measured positive ROI. It is an optimization, never a dependency for correctness.

### 7.2 Compaction

Compaction is required for multi-hour and multi-day work, but must be reversible through artifact pointers.

At each checkpoint, create:

- a concise factual run summary,
- unresolved questions and next-action list,
- decisions with evidence references,
- artifact references and hashes,
- side-effect status,
- budget status,
- retrieval gaps.

Never compact away:

- approved goal text,
- approval state,
- acceptance criteria,
- tool side-effect records,
- raw evidence references,
- unresolved conflicts.

If a summary is later suspected of omitting a relevant detail, the agent retrieves the original artifact rather than relying on reconstruction from memory.

---

## 8. Retrieval Enforcement and Verification Gates

### 8.1 Enforcement mechanism

Every task must carry a machine-readable `retrieval_policy`. Before a model result can transition to `accepted`, the orchestrator verifies a corresponding evidence manifest.

Minimum gates:

| Task type | Required verification |
|---|---|
| Code change | Files/symbols inspected, patch artifact, test/build result or explicit exception |
| Web research | Source URLs, excerpts, capture timestamps, claim-to-source mapping |
| Automation/integration | Live tool result, action logs, idempotency record, approval if external side effect |
| Spreadsheet analysis | Workbook/sheet/range references, calculation artifact, output validation |
| Document generation | Source-artifact references for factual claims; citation checks where required |
| Internal planning | Decision record and explicit uncertainty labeling if no retrieval was required |

A task requiring retrieval fails closed when:

- the evidence manifest is absent;
- citations reference sources not actually retrieved;
- retrieved evidence is stale beyond the task’s freshness threshold;
- source permissions do not permit use;
- the model claims tool use that is absent from logs;
- a required live-system value is replaced by remembered or cached information.

The model may return “insufficient evidence” or request more retrieval. That is preferable to fabricated grounding.

### 8.2 Independent verification

For high-value outputs, verification is independent from generation:

- code: tests, lint, type checks, and optionally a second-model review;
- research: citation validation and cross-source contradiction check;
- spreadsheet: deterministic recalculation and range validation;
- documents: schema/template checks plus factual-source validation.

Independent cross-provider review is not always enabled. Its benefit must be measured in the empirical evaluation plan against additional cost, latency, and orchestration complexity.

---

## 9. Implementation Sequence and Empirical Gates

### Immediate implementation

1. Create the Postgres task/evidence/decision schema and object-store artifact registry.
2. Build versioned context packets from structured state rather than provider conversation history.
3. Implement `retrieval_policy` and evidence-manifest acceptance gates.
4. Add deterministic code retrieval: file search, AST/symbol lookup, test discovery.
5. Add governed web/document retrieval with source capture and citation manifests.
6. Instrument prompt-cache usage and compaction events.
7. Register MCP servers through the policy gateway only.
8. Use provider file retrieval only as a per-task, disposable cache subject to data classification.

### Deferred until empirical evidence supports adoption

- Graphify default deployment;
- permanent owned vector database in the value architecture;
- GraphRAG;
- broad semantic code retrieval beyond the hybrid benchmark result;
- provider-native managed memory as canonical state;
- remote MCP access to non-public data without a reviewed server inventory.

### Required empirical verification

1. **Graphify replication:** compare against grep + AST + direct reading on representative repositories.
2. **Graphify egress test:** verify zero unintended external calls in code-only mode.
3. **Hybrid retrieval benchmark:** lexical/AST versus semantic versus hybrid retrieval for code, research, documents, and spreadsheets.
4. **Cache ROI test:** measure actual cache hit rate and net cost by prompt template.
5. **Compaction recovery test:** induce context rollover and confirm original facts remain recoverable from artifacts.
6. **Retrieval-enforcement test:** intentionally omit evidence and verify acceptance gates reject the output.
7. **GraphRAG gate:** build standard hybrid RAG first; only evaluate GraphRAG if global/thematic question accuracy misses the defined target.
8. **Provider feature verification:** re-check current provider file-search, cache, retention, vector-store, and Files API behavior before locking cost or sensitive-data controls.

<!-- ARTIFACT_COMPLETE -->
