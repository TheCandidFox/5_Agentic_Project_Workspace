# VALUE_ARCHITECTURE

## 1. Executive Recommendation

Adopt a **small, direct-API, provider-neutral agent control plane** built around OpenAI and Anthropic, with a durable application-owned workflow ledger, deterministic acceptance checks, and cascade-first routing.

The value architecture is intentionally not a universal multi-provider mesh. At an approximately **$150/month API-spend ceiling**, the best quality-per-dollar result comes from concentrating normal production traffic on two mandated core providers, using cheaper tiers for bounded routine work, reserving premium tiers for difficult work, and adding a third provider only after a measured workload-specific win justifies its operational and security cost.

### Recommended launch posture

| Area | Value-architecture decision |
|---|---|
| Core model providers | **OpenAI direct API** and **Anthropic direct API** |
| Default routing strategy | Cheap eligible tier → deterministic verification → mid/flagship escalation only when required |
| Third providers | Benchmark-gated; not in the default production path at launch |
| Research/web access | Native provider web tools and/or a sandboxed browser worker; no Perplexity default dependency |
| Durable state | Application-owned Postgres ledger and object storage; never provider conversations/files as canonical state |
| Long-running work | One durable orchestrator with checkpoints, idempotency, budget reservations, and recovery logic |
| Deployment | One canonical cloud host, one active scheduler/worker, Postgres, object storage, private GitHub |
| Current data posture | Public/Internal non-sensitive data only; default-deny for Confidential/Regulated data |
| Monthly API ceiling | Hard cap: **$150**; infrastructure is budgeted separately at roughly $10–20/month planning range |
| Human authority | Human approval is mandatory for primary-goal changes, external effects, financial actions, credential changes, production changes, and sensitive-data access |

This design favors **measured escalation over assumed model superiority**. The research supports the cascade pattern, but does not prove that any named provider or model is best for this user’s coding, automation, or research tasks. Therefore, the architecture begins with a simple rule-based routing baseline and uses an empirical evaluation harness to refine model bindings.

### Conservative resolution of conflicting infrastructure guidance

Research tracks differ on whether SQLite is sufficient for the deployed value architecture. SQLite is reasonable for a local, single-worker prototype, but the master goal explicitly requires multi-machine access, multi-day continuity, and resilience across restarts. Therefore:

- **Use SQLite only for local development or a disposable prototype.**
- **Use a single-host Postgres deployment for the practical value architecture.**
- Do not deploy high availability, multi-region replication, Temporal, or a managed durable-workflow platform at launch.
- Maintain one active orchestrator/worker writer at a time; local machines interact through the control API rather than accessing the database directly.

This costs somewhat more than a bare SQLite file, but avoids creating a fragile prototype that cannot safely satisfy the stated persistence requirements.

---

## 2. Core Architecture and Topology

The architecture is a compact control plane with explicit boundaries between policy, orchestration, model access, tools, and durable storage.

```text
Windows/macOS clients / later PWA
              |
              v
      Authenticated Control API
              |
              v
  Policy + Task Contract Validator
  - goal-version rules
  - data classification
  - effect authority
  - provider allowlist
  - budget reservation
              |
              v
      Durable Orchestrator
  - task graph / state machine
  - routing and escalation
  - leases / retries / reconciliation
  - acceptance and stopping rules
              |
     +--------+---------+----------------+
     |                  |                |
     v                  v                v
OpenAI adapter    Anthropic adapter   Tool adapters
direct API        direct API          browser / code /
                                     retrieval / integrations
     |                  |                |
     +------------------+----------------+
                        |
                        v
          Postgres task and cost ledger
                        |
                        v
     S3-compatible object storage for artifacts,
       source snapshots, test logs, and backups
```

### Required application-owned records

Every model, tool, or human action operates on a durable task contract. At minimum, each contract records:

- immutable objective and scope boundaries;
- `goal_version` and `contract_version`;
- task type: coding, automation, research, data, document, strategy, or image;
- data classification;
- importance band;
- effect-class ceiling;
- acceptance criteria and required evidence;
- allowed provider/model classes;
- maximum budget and escalation depth;
- approval state;
- idempotency key and parent/child task relationships;
- artifacts, source snapshots, test results, and reviewer outcomes.

The system’s Postgres ledger is the source of truth. Provider conversation state, OpenAI Responses/Conversations, Anthropic files, provider caches, vector stores, batch files, and managed-agent sessions are disposable accelerators only.

### Goal and scope governance

The orchestrator may investigate relevant omissions, edge cases, and bounded stretch work that improves the current objective. It may not alter the user’s primary goal.

Changes to the primary goal always require explicit human approval. Changes to an approved task’s objective, scope, acceptance criteria, data classification, effect ceiling, or budget ceiling must be submitted as a structured change request rather than silently applied.

A narrower scope, stricter acceptance criteria, lower effect class, or lower budget may be accepted automatically and logged. Any broader scope, higher-risk effect class, larger budget, or changed goal requires approval. After approval, the system creates a new contract version and re-validates in-flight routing decisions before they continue.

---

## 3. Provider and Model Strategy

### 3.1 Production providers at launch

The production value architecture starts with **two direct providers only**.

| Provider | Value role | Why included | Constraints |
|---|---|---|---|
| Anthropic direct API | Cheap triage, default substantive work, coding/review candidate, escalation | Mandatory core provider; verified tiered pricing and caching/batch mechanics support a three-lane design | Model quality by workload remains empirical; feature-level retention must be checked before sensitive data |
| OpenAI direct API | Alternate substantive work, structured extraction, web/tool-enabled research, flagship escalation candidate | Mandatory core provider; Background mode, Batch, file search, web tools, and tiered family support are useful primitives | Economy-tier pricing conflict must be resolved by a billed test before it is used for budget assumptions |

Use direct APIs for both core providers. Routing core traffic through an aggregator would add cost, an extra data-processing hop, and a reliability dependency without adding sufficient value.

### 3.2 Model lanes

The router refers to **capability lanes**, not hardcoded names. Exact model IDs, prices, context limits, tools, and availability are loaded from a dated provider registry and refreshed at least weekly.

| Lane | Typical work | Initial binding principle |
|---|---|---|
| Economy | Classification, extraction, metadata tagging, short summaries, schema repair, simple transformations | Cheapest eligible current model from a core provider |
| Standard | Normal coding tasks, automation design, research synthesis, structured-data analysis, document drafting | Anthropic Sonnet-class or current OpenAI mid-tier, selected by measured task performance |
| Premium | Multi-file code changes, difficult debugging, agent planning, conflicting-source synthesis, high-value review | Current OpenAI flagship or Anthropic Opus-class model |
| Rare escalation | Critical bounded reasoning after lower tiers fail objective checks | Highest eligible core tier, with a strict task budget and independent acceptance evidence |

Anthropic’s verified pricing supports Haiku-class, Sonnet-class, and Opus-class planning lanes. OpenAI’s current family identifiers and economy prices require a live registry refresh and a billed test because official-source pricing evidence conflicts for the lowest tier. The system must not assume a particular economy model is cheap until the actual account invoice confirms its effective rate.

### 3.3 Third-party providers: benchmark gates, not launch dependencies

| Provider/service | Launch decision | Reconsider only if |
|---|---|---|
| Gemini | Benchmark-only lane | It beats the core-provider baseline by a meaningful quality-adjusted-cost margin on triage, multimodal, data, or long-context tasks |
| xAI/Grok | Do not add at launch | It demonstrates a sustained win on agentic coding or research after modeling long-context repricing behavior |
| DeepSeek | Do not add at launch | A non-sensitive workload benchmark demonstrates material savings or quality value, and official pricing plus supplier/data-flow review are completed |
| Perplexity | Do not add as a default dependency | Native web research proves materially weaker on citation quality or cost per accepted memo |
| OpenRouter/aggregators | No primary routing | A long-tail model is needed and direct access is unavailable; provider pinning, fee, and data-policy controls are verified |
| Local/open-weight models | Defer | Actual hardware or rental economics beat hosted APIs for a sustained, privacy-appropriate workload |
| Specialist image/OCR/speech/video vendors | Defer | A measurable quality failure triggers a dedicated, sourced evaluation |

This is intentionally conservative. A cheaper provider is not automatically better value once orchestration, governance, policy maintenance, testing, and data-path complexity are included.

---

## 4. Routing, Escalation, and Acceptance

### 4.1 Decision sequence

Routing must happen in this order:

1. **Validate task contract.**
2. **Apply data-classification and authority policy.**
3. **Reserve the maximum allowed budget.**
4. **Select the lowest-cost eligible model lane.**
5. **Run deterministic acceptance checks.**
6. **Escalate only on evidence of failure, ambiguity, or importance.**
7. **Stop, accept, defer, or request human review according to the contract.**

Cost optimization never precedes the data-classification gate. A model is eligible only if the provider, endpoint, feature, region, and retention profile are allowed for the task’s classification.

### 4.2 Importance bands

| Band | Typical task | Routing and review rule |
|---|---|---|
| 0 — Exploratory | Reversible brainstorming, rough classification, non-binding summaries | Economy lane; no independent review required |
| 1 — Standard | Routine code explanation, extraction, internal draft, reversible transformation | Economy first; deterministic validation; one escalation maximum by default |
| 2 — High-value | Work that feeds other tasks, substantial code change, evidence-bearing research memo | Standard or premium lane; deterministic validation; sampled cross-provider review |
| 3 — Critical | External communication, production change, credentials, money, sensitive-data-adjacent work | Premium lane; deterministic verification plus mandatory independent review; human approval before execution |

The system may automatically raise an importance band when new evidence reveals greater consequence. It may not lower a band without approval.

### 4.3 Acceptance checks by workload

| Workload | Primary acceptance evidence |
|---|---|
| Coding/software | Tests, lint/type checks, build output, diff review, dependency/security scan where applicable |
| Automation/integrations | Sandbox or dry-run result, schema validation, idempotency test, expected API response, rollback plan |
| Research/web investigation | Source URLs, source snapshots, publication dates, claim-to-citation mapping, primary-source rate |
| Structured data/spreadsheets | Schema checks, numeric reconciliation, formulas/transformations rerun from source, exception report |
| Documents | Required-section validation, source/citation checks, factual-review sample, rendering check |
| Strategy | Assumption ledger, alternatives considered, decision criteria, clearly labeled uncertainty |
| Images | Human or agreed evaluator quality bar; no specialist escalation unless a defined trigger is met |

Self-reported model confidence is not an acceptance signal by itself. It may become a secondary routing feature only after calibration tests show a useful relationship to correctness for a particular model and task class.

### 4.4 Escalation ladder

For normal value-tier work:

1. Economy model produces a bounded artifact.
2. Deterministic verifier runs.
3. If verification passes, accept.
4. If verification fails or evidence is incomplete, repair once in the same lane if the failure is mechanical.
5. Escalate to standard lane for reasoning, code repair, synthesis, or complex tool use.
6. Escalate to premium lane only for Band 2–3 tasks or repeated objective failure.
7. Use cross-provider review only when required by importance, effect class, or a failed verifier.
8. Halt for human review after the configured escalation depth, budget cap, or disagreement threshold.

The default maximum escalation depth is **three paid model attempts**, excluding deterministic local checks. Repeated reviewer disagreement is not a reason to continue indefinitely; it produces a human-review task with the evidence packet attached.

---

## 5. Cost and Budget Controls

### 5.1 Monthly API budget

The value architecture targets a **hard $150/month API ceiling**. This is a control budget, not a prediction of exact consumption. Specific list prices remain volatile and must be refreshed from official provider documentation before implementation.

| Budget envelope | Monthly cap | Purpose |
|---|---:|---|
| Anthropic direct API | $55 | Economy, standard, and capped premium work |
| OpenAI direct API | $45 | Alternate work, escalation, selected tools/background calls |
| Core-provider premium reserve | $30 | Band 2–3 escalations and high-value recovery |
| Controlled evaluation/research lane | $10 | Gemini, Perplexity, or other benchmark experiments only |
| Tool and non-token charges | $10 | Web-search calls, file-search calls/storage, containers, or similar metered tools |
| **Total** | **$150** | Hard monthly API ceiling |

The evaluation lane is not permission to add providers permanently. A provider that does not demonstrate measurable value is removed from the registry after the evaluation period.

Infrastructure is separate from API spend. Plan for approximately **$10–20/month** for a small host, database storage, and object storage, subject to a real pilot invoice. This keeps total operating cost near, but not necessarily below, $170/month.

### 5.2 Spend thresholds

| Monthly spend state | System behavior |
|---|---|
| $0–105 | Normal routing within per-task reservations |
| $105–125 | Disable nonessential experimentation and discretionary reviewer passes |
| $125–150 | Reserve spend for Band 2–3 work; pause deferrable work; require approval for premium exceptions |
| $150+ | Hard stop for new paid dispatches except an explicitly approved emergency override |

Each dispatch reserves worst-case cost before submission, including maximum input/output, expected tool calls, retry allowance, and required reviewer work. On completion, actual observed usage reconciles against the reservation and unused reserve is released.

### 5.3 Cost accounting requirements

The ledger records, per call and per task:

- provider, model ID, model-registry version, and endpoint;
- uncached input, cache-write, cache-read, output, and reasoning tokens where exposed;
- tool calls, search-context fees, file-storage charges, container/runtime charges, and embeddings;
- retries, failures, latency, rate-limit events, and cancellation;
- reserved cost, actual cost, and budget variance;
- verifier result, escalation reason, and acceptance status.

Batch discounts and cache discounts are treated as measured savings, not assumed savings. Prompt caching is enabled only for prefixes that show positive return after cache-write cost and TTL behavior are measured.

### 5.4 Required verification before budget lock

The following items need empirical or live-account confirmation:

- OpenAI economy-tier billed price and model availability;
- current rate limits, concurrency, and account tier;
- actual cache-hit rate by task template;
- reasoning-token billing fields and overhead;
- web/file/tool non-token charges;
- Anthropic Sonnet standard pricing after any promotional period;
- whether a third provider improves accepted-output-per-dollar;
- whether independent review reduces false acceptance enough to justify its cost.

---

## 6. Context, Retrieval, and Memory

The value architecture uses a **minimal layered retrieval approach** rather than building a general knowledge platform.

### Coding and software retrieval

1. File and lexical search.
2. AST/symbol lookup for definitions, references, call paths, and imports.
3. Selective semantic retrieval over documentation, architecture decisions, issues, and comments only when deterministic lookup is insufficient.
4. Open specific files and bounded excerpts rather than injecting a whole repository.

Graphify is not adopted at launch. It may be piloted on real repositories only after verifying its retrieval accuracy, local-only behavior in code mode, configured backends, and performance against a grep-plus-AST baseline.

### Documents and research

- Store source documents and source snapshots in object storage.
- Use provider-native file search only as a task-scoped, disposable serving cache.
- Require retrieval citations in the model output for evidence-required tasks.
- For web research, save source URL, timestamp, excerpt/hash, and claim linkage.
- Do not deploy a vector database or GraphRAG at launch.
- Do not use GraphRAG unless a large, stable corpus fails a simpler hybrid retrieval baseline on genuinely global or multi-hop questions.

### Working memory

The agent receives a compact context packet containing:

- current task contract;
- current plan and checkpoint;
- accepted decisions and constraints;
- relevant artifact pointers and retrieval results;
- budget and escalation state;
- recent tool outcomes;
- explicit unresolved questions.

Raw transcripts, source files, full tool logs, and prior artifacts remain external. Context compaction creates a new structured summary but never replaces raw evidence. Stable prompt material is placed before volatile material so it can be measured for caching eligibility.

---

## 7. Long-Running Work, Checkpoints, and Recovery

Long-running work is a workflow-engine responsibility, not a provider feature.

### Execution model

- The orchestrator uses a durable state machine in Postgres.
- Each task step receives a generated `step_id`, request hash, idempotency key, budget reservation, and lease.
- Before dispatch, the system writes a `dispatch_intent`.
- If the provider accepts work but the client loses the response, the step enters `submitted_unknown`, not “retry immediately.”
- Reconciliation checks the canonical provider resource where possible before retrying.
- Tool actions use their own idempotency keys and compensating/rollback behavior where available.

### Asynchronous provider primitives

- Use **OpenAI Background mode** for individual long-running responses expected to take minutes when the task’s data classification allows it.
- Use OpenAI webhooks as a completion signal, but reconcile webhook events against the provider resource because delivery may be duplicated.
- Use bounded adaptive polling for Anthropic batch work where no confirmed first-party batch-completion webhook is available.
- Use native Batch APIs only for independent, non-interactive, non-sensitive map-stage work: corpus processing, extraction, evaluation, embeddings, or independent reviewer opinions.
- Do not put multi-turn agent loops, tool-dependent sequences, or side-effecting workflows into Batch.

### Checkpoint rules

Checkpoint after:

- plan acceptance;
- each completed model step;
- each tool invocation;
- each artifact write;
- each external approval;
- each verifier result;
- each budget change;
- each provider error or rate-limit response.

A provider failover may occur only at a checkpoint with a portable context packet and no unresolved external side-effect ambiguity. The system must never blindly switch providers in the middle of a tool action.

---

## 8. Deployment and Cloud Footprint

Deploy one canonical Linux host using Docker Compose or an equivalent simple deployment package:

- control API;
- orchestrator/scheduler;
- one active worker;
- Postgres;
- optional isolated tool-worker container;
- private GitHub repository for code, schemas, prompts, migrations, and infrastructure configuration;
- S3-compatible object storage, preferably Cloudflare R2 or equivalent, for artifacts and backups.

Windows and macOS machines are clients and development environments, not competing workflow hosts. Use a devcontainer or Docker-based development contract with the same bootstrap, test, migration, and deployment commands across operating systems.

### Value-tier resilience posture

- One active orchestrator/worker at a time.
- Daily encrypted database backup and object-storage backup/sync.
- Rolling 30-day backup retention.
- Initial recovery targets: **RPO ≤24 hours** and **RTO ≤8 hours**.
- Manual failover only: isolate or terminate the old host, revoke its write-capable credentials, restore the replacement, then promote it as the sole writer.
- Do not enable automated failover until a real fencing-token design passes host-loss and partition drills.

---

## 9. What Not to Build at Launch

Do not build the following before evidence or workload scale requires them:

- a Temporal-class workflow platform;
- active-active workers, automated failover, or multi-region deployment;
- a general vector database;
- GraphRAG or a broad knowledge graph;
- Graphify as a required dependency;
- a permanent provider-managed memory store;
- OpenRouter as a core-provider path or silent fallback;
- DeepSeek, xAI, Gemini, or Perplexity as permanent production dependencies;
- local GPU hosting;
- managed provider agents as the system of record;
- a multi-tenant product surface;
- specialist image, OCR, speech, or video provider integrations;
- a PWA/mobile runtime.

A later PWA may provide status, notifications, and approval actions. It must remain a thin authenticated client; all scheduling, budget expiry, authorization, and workflow state remain server-side.

The value architecture succeeds by keeping the provider set, infrastructure, and state model deliberately small while retaining the ability to add measured capabilities behind adapters and policy gates.

<!-- ARTIFACT_COMPLETE -->
