# LONG_RUNNING_WORK.md

## Purpose and Scope

This module specifies how a single goal survives from initial decomposition through hours or days of execution across restarts, crashes, provider outages, rate limits, context-window rollovers, and multi-day human pauses — without losing state, duplicating side effects, or running away on cost or time. It defines the **queue and dependency model**, the **checkpoint/resume mechanism**, **idempotency and retry discipline**, **rate/usage-limit handling**, **event-driven handoffs**, **stop conditions**, and the **human-approval boundaries** that bound autonomous execution. It assumes the task-contract schema, importance-band table, and effect-class taxonomy defined in the routing track (`MODEL_ROUTING_MATRIX`) as an upstream input, and does not redefine routing logic — only how work is queued, persisted, and safely resumed once routed.

This applies to both the VALUE and QUALITY-MAX architectures; differences are called out per section. Both tiers share one non-negotiable premise, carried from the routing and infrastructure research: **provider-side conversation state, batch jobs, background responses, and webhooks are accelerators, never the system of record.** The system of record is this module's own durable ledger.

---

## Execution Model: Ledger, Queue, and Dependencies

The durable unit of work is the **task contract** (defined in `MODEL_ROUTING_MATRIX`), and the durable structure holding many contracts is a **task/step ledger** in a shared database — Postgres for any deployed instance, SQLite permitted only for local single-worker development. A single always-on orchestrator process (value tier) or a small set of role-separated workers (quality-max: scheduler, tool workers, optional local-inference workers) claim work from this ledger.

Work is organized as a **DAG of tasks**, not a flat FIFO queue: a task may declare `depends_on: [task_id, ...]` and is not eligible for dispatch until all dependencies reach a terminal success state. Dependency edges are stored in the ledger, not inferred from conversation order, so the DAG survives restarts intact. A task's `importance_band` (0–3) and `effect_class_ceiling` — inherited from its contract — determine dispatch priority ordering within the eligible set, but do not bypass dependency ordering.

**Task claiming uses lease-based ownership**, not a mutex on the whole queue: a worker claims a task by writing `worker_id`, `lease_expires_at`, and incrementing a `claim_version`; other workers may not act on that task until the lease expires. This allows multiple workers (quality-max) or a single worker restarting after a crash (value tier) to safely re-claim orphaned work without double-execution, provided the idempotency controls in the next section are also honored — a lease alone prevents two *simultaneous* claims but does not by itself prevent a *stale* worker from resuming a side-effecting action after its lease has already expired (see fencing risk, DEPLOYMENT module).

Sub-task decomposition is itself an event recorded in the ledger: when a planner expands a task into children, the children are written transactionally alongside a `decomposition_of` pointer, so a crash between "plan produced" and "children durably queued" cannot silently lose part of the plan.

---

## Checkpoints and Resume

A **checkpoint** is a durable snapshot of everything needed to resume a task without repeating already-paid-for work. At minimum, each checkpoint record captures: the task's current step index, the accumulated evidence/artifact references (not full blobs — pointers into object storage), the token/cost spend consumed so far against that task's budget reservation, the last successfully completed tool call's result hash, and the model/provider/tier that produced the last completed step. Checkpoints are written **after** each step is durably confirmed complete (verifier passed, artifact stored, evidence recorded) — never before, and never based on an unconfirmed in-flight model response.

Resume logic on worker startup (or after lease expiry / restart / multi-day pause) is: (1) read the last durable checkpoint for the task, (2) reconcile against any pending provider-side operation (was a batch job or background response in flight when the process died?), (3) determine whether that operation completed, failed, or is unknown, and (4) only then resume forward — re-attempting the unresolved step rather than the whole task. This reconciliation step is why an idempotency ledger (next section) is mandatory infrastructure rather than a convenience: without it, "was that already done?" has no reliable answer after a crash.

Context-window rollover is treated as an ordinary checkpoint boundary, not a special case: when accumulated context approaches a task's usable limit, the orchestrator triggers a compaction/summarization step (per `CONTEXT_AND_MEMORY`), writes the resulting compact state as a new checkpoint, and continues — the checkpoint schema is agnostic to *why* a resume is needed (crash, rate limit, multi-day pause, or context rollover all resume identically).

Multi-day pauses (e.g., awaiting human approval per §Human Approval Boundaries, or a paused project) are not distinguished from short pauses at the mechanism level — a task sitting in `awaiting_approval` or `blocked_on_dependency` for six hours or six days resumes through the same checkpoint-read path once unblocked.

---

## Idempotency and Retry/Backoff

Neither OpenAI's nor Anthropic's synchronous inference endpoints are documented to guarantee exactly-once semantics on retried requests, and batch `custom_id` fields are correlation keys, not cross-submission dedup guarantees (verified against current provider docs; re-check at implementation time, as this is the kind of detail that can change). The system must therefore own idempotency itself:

- Every dispatched unit of work is assigned a `step_id` (UUID) **before** dispatch, persisted with a hash of the exact request payload.
- Before dispatch, the worker checks the ledger for an existing `step_id` with that request hash in a non-terminal or successful state; if found, it does not re-dispatch — it either awaits the in-flight result or reuses the stored one.
- A dispatch passes through an explicit `submitted_unknown` state between "request sent" and "response confirmed." A crash, network loss, or ambiguous timeout leaves the step in `submitted_unknown`, which on resume triggers a **reconciliation check** (poll the provider resource, e.g., a batch/background job ID, if one exists) before any retry — never a blind resend for side-effecting tool calls.
- Tool wrappers for side-effecting actions (file writes, code execution, external API calls, sends) must independently support idempotent replay (e.g., a provided idempotency key, a pre-check for "does this effect already exist," or a compensating action) — this is verified per tool at implementation time, not assumed.

**Retry and backoff** follow provider-documented signals where available: honor `Retry-After` headers, apply exponential backoff with jitter, and cap retries at a per-step `retry_limit` from the task contract (default: 2). Application-level retry logic must not stack blindly on top of SDK-level auto-retry for rate-limit errors — the retry budget is counted once, at the orchestrator level, so a step cannot silently consume 6x its intended retry budget through two overlapping retry layers. Exhausting `retry_limit` transitions the step to `failed`, which surfaces to the task's escalation/disagreement handling (per `MODEL_ROUTING_MATRIX` §3) rather than looping indefinitely.

---

## Rate and Usage Limits

Rate limits are multi-dimensional (RPM and TPM, scoped per org/project/model, sometimes shared across a model family) and are **not stable numbers** — both major providers state these change without notice. The orchestrator maintains a local, provider-and-model-scoped token/request budget tracker, updated live from response headers where exposed, falling back to a conservative static configuration where header data isn't available (e.g., Anthropic's Rate Limits API requires Admin-tier access not assumed present). Admission control checks this tracker **before** dispatch, alongside the cost-budget reservation (below) — a request that would exceed either the token-rate budget or the dollar budget is queued, deferred, or downgraded to a cheaper tier, not fired and left to 429.

**Budget is reserved before dispatch, not just logged after.** Each step's worst-case cost (model tier, max output, expected tool calls, retry allowance) is reserved atomically against task, run, and monthly ceilings at claim time; unused reservation is released on completion. When remaining monthly budget cannot cover the cheapest eligible model for a step, dispatch halts and the task moves to `blocked_on_budget`, which is a human-visible state, not a silent stall.

---

## Event-Driven Handoffs

Where a provider offers first-class, signature-verifiable, at-least-once webhook delivery (confirmed for OpenAI batch/background completion), the orchestrator subscribes to it and treats the webhook as a **wake-up signal that triggers reconciliation against the canonical resource** — not as the authoritative state transition itself, since webhook delivery can duplicate or (per Anthropic's own documentation for its beta managed-agent webhooks) arrive out of order or be dropped. Where no reliable webhook exists (Anthropic Message Batches, as currently documented), the orchestrator uses **bounded adaptive polling** — short intervals early, backing off geometrically, capped at a maximum interval — plus a periodic reconciliation sweep that checks all `submitted_unknown` and in-flight steps regardless of whether a webhook was expected. Dedup on webhook receipt uses the provider's delivery ID; a duplicate delivery for an already-reconciled step is a no-op logged for observability, not reprocessed.

---

## Stop Conditions and Anti-Loop Controls

Long-running autonomy fails unsafely when it lacks hard ceilings, not just soft heuristics. The following caps are configuration, externally tunable, but always present and enforced by the orchestrator rather than trusted to model self-restraint:

- **Escalation-depth cap** (default 3 tiers) per task, per the routing track's cascade design — a task cannot escalate indefinitely chasing a passing verdict.
- **Disagreement-repeat cap** (default 1 retry after a resolvable disagreement) — repeated generator/reviewer conflict on the same sub-task routes to human review rather than re-litigating.
- **Re-plan cap after an approved goal/scope change** (default 1 automatic re-plan) — prevents a change triggering an unbounded replanning cascade.
- **Wall-clock and step-count ceilings per task and per run** — independent of budget, since a runaway loop can be cheap-per-call but unbounded in iteration count (e.g., a research loop that never converges). A task exceeding its step-count or wall-clock ceiling is halted and moved to `stopped_for_review`, not silently killed and forgotten — the ledger retains full state for inspection and manual resume.
- **Budget exhaustion** (task, run, or monthly) halts dispatch and creates a human-visible blocked state, per §Rate and Usage Limits.

All caps write a structured stop-reason to the ledger (`escalation_cap_hit`, `disagreement_cap_hit`, `budget_exhausted`, `step_cap_hit`, `wall_clock_cap_hit`) so that recurring stop causes are visible in aggregate, not just per-incident — this is the primary signal for tuning the caps themselves, which the routing track flags as requiring empirical retuning rather than being treated as final.

---

## Human Approval Boundaries

Approval gates are structural, not advisory, and are enforced at the effect-class and importance-band layer defined in `MODEL_ROUTING_MATRIX`, not re-derived here. This module's responsibility is ensuring approval integrates cleanly with the queue/resume model:

- A task requiring approval (any `effect_class_ceiling` above `SANDBOX_WRITE`, any Importance Band 3 task, any goal/scope change beyond a narrowing, any disagreement touching irreversible/external/financial/credential/sensitive-data actions) transitions to `awaiting_approval` and is **removed from active dispatch** — it does not consume worker time or budget while waiting, and it does not block sibling tasks unless they declare a dependency on it.
- Approval is a discrete, logged ledger event (approver identity, timestamp, rationale, contract version) — never inferred from elapsed time, prior conversation tone, or lack of objection. A task cannot silently "time out into approved."
- An `awaiting_approval` task that exceeds a configurable staleness threshold (e.g., 7 days) surfaces as a reminder/notification (email, or eventually the PWA surface) but does not auto-approve or auto-reject; it remains blocked until an explicit decision.
- On approval, the task re-enters the queue at its checkpointed state and is re-validated against the current contract version before dispatch resumes (per the goal-change governance and re-validation rule in `MODEL_ROUTING_MATRIX` §5.1) — an approval granted under a stale contract version does not silently authorize execution under a newer one.
- Rejection is terminal for that contract version and requires either a human-authored replacement task or an explicit re-proposal cycle; it is not retried automatically.

---

## Failure-Mode Coverage and Required Fault-Injection Testing

The mechanisms above are design intent, not proven reliability. Per the long-running-workloads research track, the following must be validated via fault injection before this module's guarantees are trusted in production, and are called out here as the authoritative test list for this module specifically:

1. Crash immediately before vs. after a dispatch-intent commit (does `submitted_unknown` reconciliation correctly avoid duplicate side effects?).
2. Network loss after provider acceptance but before response receipt (same check, provider-response side).
3. Worker death mid-tool-call, verifying lease expiry and safe re-claim without double execution.
4. Duplicate, delayed, and out-of-order webhook delivery (confirming dedup-by-delivery-ID and reconciliation-not-trust behavior).
5. Provider 429/5xx/timeout under active budget reservation (confirming backoff doesn't double-count against retry/budget caps).
6. Expired-lease double-claim by two workers (quality-max multi-worker scenario).
7. Context/checkpoint rollover mid-task, confirming resume reconstructs equivalent working state.
8. Mid-plan budget exhaustion, confirming graceful `blocked_on_budget` rather than partial silent execution.
9. Approval granted after an intervening contract-version change, confirming re-validation blocks stale-version execution.
10. A deliberately induced disagreement loop and a deliberately induced runaway step-count, confirming both anti-loop caps trigger and produce a human-reviewable stop reason.

Until this suite passes against the actual Postgres ledger implementation, the checkpoint/resume/idempotency design in this module should be treated as **specified but unverified** — consistent with the broader research finding that no off-the-shelf provider primitive (batch, background mode, or beta managed-agent sessions) substitutes for this application-owned durability layer.

<!-- ARTIFACT_COMPLETE -->
