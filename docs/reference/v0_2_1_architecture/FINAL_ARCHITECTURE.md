# Final Architecture Index and Synthesis

## Executive Recommendation

Adopt a **provider-neutral, application-owned agent control plane** with OpenAI and Anthropic direct APIs as the initial production core. The system should be designed around a durable task contract, Postgres-backed workflow ledger, object-stored artifacts, deterministic acceptance checks, budget reservations, and policy-gated tool execution.

The central architectural decision is:

> **The system owns goals, state, evidence, approvals, budgets, and recovery. Providers supply bounded model and tool capabilities; they are never the system of record.**

The recommended default is the **VALUE architecture**: a small, direct-API, cascade-first system targeting a hard **$150/month API ceiling**. It starts with the lowest-cost eligible lane that can satisfy a task, verifies results deterministically, and escalates only when evidence warrants it.

The **QUALITY-MAX architecture** shares the same ledger, governance, safety gates, and durable execution model, but starts important work at stronger tiers, uses more independent review, permits stakes-gated redundancy, and upgrades infrastructure only when reliability testing justifies it.

The architecture does **not** assume that a newer, more expensive, or third-party model is superior for this workload. Provider/model selection remains empirical and registry-driven. OpenAI and Anthropic are mandatory core providers; Gemini, xAI/Grok, Perplexity, DeepSeek, aggregators, local models, Graphify, GraphRAG, and specialists are optional additions behind measured-value and data-policy gates.

Human authority remains non-negotiable: the system may pursue bounded work that improves an approved goal, but it may not autonomously change the primary goal, broaden material scope, access sensitive data, alter credentials, make purchases, deploy to production, communicate externally, or perform irreversible actions without explicit approval.

---

## Value Architecture

The VALUE architecture is the recommended launch design because it satisfies persistence, multi-day operation, multi-machine access, provider portability, and safety requirements without prematurely building a complex distributed agent platform.

### Core topology

```text
Windows/macOS clients / later PWA
              |
              v
      Authenticated Control API
              |
              v
 Policy + Contract + Budget Validation
              |
              v
      Durable Orchestrator
      - DAG/state machine
      - routing/escalation
      - retries/reconciliation
      - approvals/stopping rules
              |
      +-------+--------+--------+
      |                |        |
      v                v        v
 OpenAI direct    Anthropic   Governed tools
 API adapter      direct API  browser/code/retrieval
              |
              v
     Postgres workflow and cost ledger
              |
              v
 S3-compatible object storage for artifacts,
 evidence captures, source snapshots, logs, backups
```

### Operating posture

- **Core providers:** OpenAI direct API and Anthropic direct API.
- **Default routing:** economy or mid lane where eligible, then deterministic verification, then evidence-driven escalation.
- **State:** Postgres is canonical in deployment; SQLite is local-development-only.
- **Artifacts:** immutable, content-hashed object storage.
- **Budget:** hard $150/month API ceiling, with separate infrastructure planning of roughly $10–20/month.
- **Provider additions:** benchmark-gated and policy-gated, never silent fallbacks.
- **Infrastructure:** one cloud host, one active scheduler/worker, manual recovery, daily backups.
- **Data posture:** Public/Internal non-sensitive work initially; unclassified tasks are fail-closed as sensitive.
- **Autonomy:** bounded investigation is allowed; goal changes and consequential actions require approval.

The value design intentionally avoids launch dependencies on Temporal-class workflow engines, active-active workers, managed agent platforms, GraphRAG, permanent vector databases, broad knowledge graphs, local GPUs, aggregators in the core path, and specialist media vendors.

---

## Quality-Max Architecture

QUALITY-MAX is not “spend more on every task.” It is a controlled increase in model floor, reviewer independence, redundancy, and recovery investment where those changes improve accepted output quality.

It retains the VALUE architecture’s core invariants:

- application-owned durable ledger and artifacts;
- task contracts, goal versions, and approval gates;
- provider-neutral adapters;
- data-classification gates before cost optimization;
- deterministic verification above model confidence;
- checkpoint-only provider failover;
- bounded retries, budgets, and anti-loop stops.

### Primary differences

| Dimension | Value architecture | Quality-max architecture |
|---|---|---|
| Default model floor | Cheapest eligible lane or mid tier depending on task | Mid/flagship for Band 1+ work |
| Coding and research | Mid first, escalate on objective failure | Flagship first for substantive high-priority tasks |
| Review | Deterministic verifier; sampled cross-provider review | Near-universal independent review for Band 2–3 initially |
| Redundancy | No default parallelism | Stakes-gated competing plans or implementations |
| Escalation depth | Initial cap: 3 paid attempts | Initial cap: 4 paid attempts; empirical ceiling up to 6 only by policy revision |
| Reviewer disagreement | Stop after one unresolved repeat | Stop after two unresolved repeats |
| Infrastructure | Single host, manual recovery | Dedicated resources, managed secrets/KMS, drill-gated standby improvements |
| Retrieval | Lexical/AST first; selective semantic retrieval | Same baseline plus owned retrieval/GraphRAG only after evidence of need |

### Explicit conflict resolution

The companion modules contain an escalation inconsistency: one routing passage describes quality-max as retaining three substantive stages, while the dedicated quality-max module specifies a starting cap of four paid attempts. The final architecture resolves this as follows:

- **VALUE:** maximum of three paid model attempts per task by default.
- **QUALITY-MAX:** maximum of four paid model attempts initially.
- **QUALITY-MAX changes beyond four:** require empirical calibration; the absolute ceiling is six only after explicit human-approved policy revision.
- Deterministic checks do not count as paid attempts.
- Repeated disagreement remains a stop signal, not a reason for indefinite debate.

Quality-max may use OpenAI flagship and Anthropic Opus-class routes when current registry and endpoint policy permit. Gemini and xAI are benchmark candidates for independent review or specialty use. Fable-class Anthropic references, DeepSeek premium routes, and Perplexity default production use remain **deferred** until live vendor verification, data-policy eligibility, and empirical benefit are established.

---

## Routing and Escalation

Routing is policy-controlled, evidence-first, and deliberately simple at launch.

### Required routing order

1. Validate goal version, task contract, scope, and approval state.
2. Apply data classification and provider/endpoint eligibility.
3. Apply action/effect-class restrictions.
4. Confirm required capabilities: context, tools, modality, structured output, retrieval.
5. Reserve worst-case budget before dispatch.
6. Select the lowest-cost eligible route consistent with importance and task type.
7. Run deterministic checks and evidence validation.
8. Escalate only on objective failure, ambiguity, or importance requirements.
9. Accept, defer, stop for review, or request human approval.

The router never changes goals, approves scope expansion, or authorizes external action.

### Initial workload routes

| Workload | Value first route | Quality-max first route | Primary acceptance evidence |
|---|---|---|---|
| Coding/software | Mid tier; economy only for isolated work | Flagship | Tests, lint, types, build, diff review |
| Automations/integrations | Mid tier | Flagship for complex flows | Sandbox, schemas, idempotency, replay |
| Research/web | Mid tier with enforced retrieval | Flagship with independent sourcing | Source manifest, citations, contradiction checks |
| Structured data | Mid tier plus deterministic computation | Flagship for complex analysis | Reconciliation, schema, formula checks |
| Documents | Economy/mid based on stakes | Mid/flagship based on impact | Required sections, citations, rendering |
| Vision/images | Core native multimodal route | Best eligible native route plus comparison if material | Field audit and source comparison |
| Strategy | Mid tier, explicitly advisory | Flagship plus independent review when consequential | Assumptions and alternatives register |

### Provider policy

- **OpenAI and Anthropic:** direct APIs, core production routes.
- **Gemini:** highest-priority third-provider benchmark candidate; adapter support may be added, but it is not a default production route until it wins representative tests.
- **xAI/Grok:** benchmark candidate for agentic coding/research; guard long-context repricing.
- **Perplexity:** narrow research-specialist candidate only; no default dependency until fee and citation-quality gates pass.
- **DeepSeek:** non-sensitive, manual/benchmark-only candidate; never a silent fallback.
- **OpenRouter/aggregators:** exception-only, pinned-provider access path; never route core traffic through an aggregator by default.
- **Local/open-weight models:** defer until air-gapped or privacy economics justify the operational cost.
- **Specialists:** trigger-gated by demonstrated core-provider failure.

The system uses logical roles—economy, mid, flagship, multimodal, research specialist—not permanently hardcoded model names. Model IDs, pricing, context limits, rate limits, retention eligibility, and tool support must come from a dated provider registry.

---

## Context / Retrieval / Memory

The system uses layered, workload-specific retrieval rather than a universal “memory” prompt or immediate vector database deployment.

### Canonical memory model

1. **Postgres ledger:** goals, contracts, approvals, budgets, task state, decisions, and operational telemetry.
2. **Object storage:** artifacts, patches, source captures, logs, screenshots, documents, test results, and backups.
3. **Per-call context packet:** compact, versioned working context built from durable records.
4. **Derived indexes:** summaries, embeddings, AST indexes, semantic indexes, and graph artifacts that remain rebuildable from canonical sources.

Provider conversations, provider file stores, provider vector stores, prompt caches, and managed-agent sessions are disposable accelerators.

### Retrieval policy

- **Code:** lexical search, AST/symbol lookup, test discovery, direct file inspection, then selective semantic retrieval.
- **Research:** source-first retrieval with URLs, timestamps, excerpts, claim mappings, and conflict labeling.
- **Data/spreadsheets:** direct workbook/table/range inspection and deterministic calculations, not embedding-first retrieval.
- **Documents:** temporary provider-native file search where permitted, but original documents and metadata remain owned artifacts.
- **Integrations:** governed live-tool access rather than copied operational data in a vector store.

Every task carries a machine-readable retrieval policy such as `NONE`, `GROUNDED`, `CITATION_REQUIRED`, or `LIVE_TOOL_REQUIRED`. Acceptance fails closed if required evidence is missing, stale, uncited, unauthorized, or falsely claimed.

### Deferred retrieval components

Graphify is a pilot only. It must be evaluated against grep, AST/symbol lookup, direct reading, and selective semantic retrieval on representative repositories. Its backend configuration and egress behavior must be verified before non-public code is used.

GraphRAG and permanent vector infrastructure are also deferred. They become candidates only if hybrid lexical/semantic retrieval demonstrably fails on large, stable, global or multi-hop knowledge workloads.

---

## Long-Running and Resume Model

Long-running work is a durable workflow problem, not a provider-session feature.

The deployed system uses a Postgres-backed DAG/state machine with task leases, dependency edges, budget reservations, checkpoints, idempotency keys, and explicit recovery states.

### Required execution controls

- Write `dispatch_intent` before every provider or tool dispatch.
- Assign a durable `step_id`, request hash, and idempotency key.
- Enter `submitted_unknown` after ambiguous network/provider outcomes.
- Reconcile provider-side resources before retrying.
- Never blindly resend a potentially accepted request or side-effecting tool action.
- Use bounded retries with jitter and provider `Retry-After` signals.
- Checkpoint after every completed model step, tool call, artifact write, verifier result, approval, budget update, error, and compaction event.
- Resume from the last durable checkpoint, not from model conversation history.

OpenAI Background mode and webhooks may improve responsiveness for long calls; webhooks are wake-up signals only and must be reconciled. Anthropic batch work uses bounded adaptive polling where reliable completion webhooks are unavailable. Batch is limited to independent, non-interactive, non-sensitive map-stage work.

The system stops rather than loops when it reaches an escalation cap, disagreement cap, retry limit, wall-clock limit, step-count limit, task budget, run budget, or monthly budget. Every stop writes a structured reason and produces a human-reviewable evidence packet.

---

## Deployment and Remote Access

Deploy one canonical Linux cloud host using Docker Compose or equivalent minimal packaging:

- authenticated control API;
- durable scheduler/router;
- one active worker;
- Postgres;
- optional isolated tool worker;
- direct provider adapters;
- S3-compatible artifact storage;
- private GitHub source and CI/CD repository.

Windows and macOS are clients and development environments, not competing state hosts. Use devcontainers/Docker tooling and canonical commands for bootstrap, tests, migrations, local run, deployment checks, and restore drills.

### Explicit deployment conflict resolution

`IMPLEMENTATION_ROADMAP.md` includes a v0.3 decision point that allows SQLite-on-VM with Litestream in some circumstances. That conflicts with the dedicated VALUE, LONG_RUNNING_WORK, and DEPLOYMENT decisions.

The final architecture resolves this conservatively:

- **SQLite is allowed only for local single-machine development and disposable prototypes.**
- **Postgres is mandatory for the deployed value architecture.**
- One active writer remains the value-tier operational model; Postgres is chosen for durable leases, idempotency, multi-machine clients, multi-day recovery, and future worker evolution—not for premature high availability.

Initial recovery targets are RPO ≤24 hours and RTO ≤8 hours, supported by encrypted daily database backups, object-storage backup copies, and a manual host-loss recovery runbook. Automated failover is prohibited until fencing-token design and partition/host-loss drills pass.

---

## Security / Privacy

The current operating stage is single-operator, non-sensitive data. The design nevertheless establishes future-sensitive and multi-tenant boundaries now.

### Mandatory initial controls

- Explicit data classification on every task.
- Fail-closed treatment for unclassified tasks.
- Versioned provider × endpoint × feature policy registry.
- Direct core-provider routes only for normal production work.
- DeepSeek, xAI, Perplexity, and aggregators restricted to explicitly non-sensitive work where enabled.
- Separate credentials for orchestrator, worker, backups, deployment, and storage.
- No provider or storage keys in browsers, PWA clients, mobile applications, source code, logs, or Git history.
- Encrypted secret handling, full-disk encryption on credential-bearing machines, key rotation, and tested revocation.
- Append-only security audit log separated from ordinary telemetry.
- Sandboxed, egress-restricted code/tool execution.
- Tenant/workspace fields and Postgres RLS prepared from Stage 0, with no runtime application credential holding table-owner or superuser privileges.

Confidential or regulated data remains out of scope until endpoint-specific provider retention, training-use, cache, background, file, and zero-data-retention eligibility are re-verified. At that stage, move to managed secrets, stronger RBAC, MFA/SSO, customer-managed keys, tenant-isolation testing, and potentially schema/database-per-tenant separation.

---

## Implementation Roadmap — Immediate Next Build

Follow **`IMPLEMENTATION_ROADMAP.md`**, beginning with **Milestone v0.2.x: Harden the Local Loop**.

The first concrete build milestone is not cloud deployment, Gemini integration, a dashboard, vector retrieval, or a workflow platform. It is:

> **Refactor the existing GPT↔Claude Python loop into a durable local system with a provider adapter, SQLite development ledger, telemetry, budget guard, deterministic two-tier router, data-classification tag, and Tier-1 code retrieval.**

Execute the v0.2.x sequence in this order:

1. Inventory the current loop and tag the repository as `v0.1-baseline`.
2. Extract OpenAI and Anthropic calls into `provider_adapter.py`.
3. Add local `ledger.db` in SQLite WAL mode for task contracts and step state.
4. Record every call’s tokens, cost estimate, model, latency, and error telemetry.
5. Add pre-dispatch daily/monthly budget reservation and denial logging.
6. Implement a deterministic two-tier cascade: cheap/mid first, one evidence-based escalation.
7. Persist data classification for every task.
8. Add lexical plus AST/symbol code retrieval.
9. Build the v0.2.x acceptance suite.
10. Prove restart recovery, budget blocking, one-step escalation, secret hygiene, and retrieval correctness before tagging `v0.2.0`.

No cloud spend or new-provider work should begin until the v0.2.x acceptance criteria pass. This is the cheapest, most reversible milestone and establishes the ledger, observability, and control boundaries required for every later feature.

---

## Empirical Evaluation / Open Questions

The architecture is decision-ready, but several claims remain deliberately empirical rather than assumed.

### Required tests before production policy lock

1. **OpenAI economy pricing:** resolve the documented price conflict with live official pricing and a billed test.
2. **Provider registry:** re-pull model IDs, limits, tools, pricing, and endpoint data policies before use.
3. **Core model bake-off:** compare OpenAI and Anthropic on representative coding, automation, research, data, and document tasks.
4. **Third-provider gates:** test Gemini, xAI, Perplexity, and DeepSeek only on eligible non-sensitive tasks and retain only measured winners.
5. **Review independence:** prove cross-provider review reduces false acceptance before making it a routine default.
6. **Retrieval benchmark:** compare lexical/AST, semantic, hybrid, provider-native retrieval, and Graphify pilot routes.
7. **Cache ROI:** enable prompt caching only where measured savings exceed write and invalidation costs.
8. **Fault injection:** prove idempotency, webhook deduplication, restart recovery, budget containment, rate-limit handling, and safe pause/resume.
9. **Security drills:** test secrets bootstrap, provider key scoping, audit-log integrity, sandbox egress controls, backup restoration, and sensitive-route blocking.
10. **Quality-max economics:** calculate cost from actual workload telemetry rather than claiming an unsupported multiplier over value mode.

The primary routing metric is not generic benchmark rank. It is **accepted-task quality, false-acceptance rate, cost per accepted task, latency, reliability, and human repair time** on this system’s representative work.

---

## Companion Deliverable Map

| Companion file | Implementation ownership |
|---|---|
| `VALUE_ARCHITECTURE.md` | Launch topology, provider posture, budget control, value-tier operating model |
| `QUALITY_MAX_ARCHITECTURE.md` | Higher-quality defaults, review/redundancy policy, staged resilience upgrades |
| `MODEL_ROUTING_MATRIX.md` | Task-type routes, logical model roles, eligibility gates, escalation and review rules |
| `COST_MODEL.md` | Cost ledger, budget caps, price uncertainty handling, spend guardrails |
| `CONTEXT_AND_MEMORY.md` | Durable memory, context packets, retrieval policies, Graphify/GraphRAG gates, MCP controls |
| `LONG_RUNNING_WORK.md` | DAG execution, checkpoints, idempotency, retries, webhooks, reconciliation, stop rules |
| `DEPLOYMENT.md` | Cloud topology, Postgres/object storage, portable development, CI/CD, backups, PWA boundary |
| `SECURITY_ROADMAP.md` | Classification, secrets, auditability, encryption, tenant separation, staged privacy controls |
| `IMPLEMENTATION_ROADMAP.md` | Ordered migration from the existing GPT↔Claude loop; begin with v0.2.x immediately |
| `EMPIRICAL_EVAL_PLAN.md` | Representative benchmark suite, routing experiments, reviewer tests, retrieval evaluation, promotion thresholds |

<!-- ARTIFACT_COMPLETE -->
