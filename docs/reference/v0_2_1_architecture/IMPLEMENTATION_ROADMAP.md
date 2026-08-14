# IMPLEMENTATION_ROADMAP.md

## 0. Scope and Ground Rules

This module defines the concrete, ordered build sequence from the currently-working Python GPT↔Claude loop to the ~$150/month VALUE architecture described elsewhere in this package, expressed as versioned milestones (v0.2.x → v0.3 → v1.0). It specifies files/components to add at each step, acceptance criteria/tests that gate progression, explicit checkpoints, and a rollback/recovery procedure for every stage. It does not redesign the router, cost model, or security policy in detail — those are owned by MODEL_ROUTING_MATRIX, COST_MODEL, and SECURITY_ROADMAP respectively — but it sequences when each is introduced and what must be true before the next step is attempted.

**Assumption about the current baseline (flag for verification):** the existing system is a single Python process that (a) accepts a goal as input, (b) alternates calls between an OpenAI model and an Anthropic model with no persistent task ledger, (c) has no cost/token tracking, no retry/backoff, no data-classification gate, and no durable state beyond an in-memory transcript or a flat log file. If the actual baseline differs (e.g., already has partial logging or a database), the v0.2.x steps below should be treated as a diff against actual current state, not a full rebuild.

**Governing principles carried through every milestone:**
- No milestone may change the user's primary goal autonomously; goal-change governance (immutable contract fields, structured change requests, human approval) is a v0.3 requirement, not deferred to v1.0, because it is cheap to build early and expensive to retrofit.
- Every new component must be justified against "favor the simplest architecture that reliably works" — a provider, service, or abstraction is added only when a specific milestone's acceptance criteria cannot be met without it.
- Every milestone ends with a working, rollback-tested system, not a half-migrated one. A milestone is not "done" until its acceptance criteria pass **and** its rollback procedure has been exercised at least once (dry-run acceptable for early milestones, live-tested by v1.0).

---

## 1. Baseline: Current State (v0.1 — "the loop")

**Component inventory (as understood, to be confirmed against actual repo):**
- `loop.py` (or equivalent) — synchronous GPT↔Claude alternation.
- Provider SDK calls made directly, no adapter layer.
- No database; state (if any) lives in a JSON/text transcript file.
- No cost tracking, no rate-limit handling, no retries.
- Secrets likely in a local `.env`, not yet verified against git-ignore hygiene.

**v0.1 exit condition (must confirm before starting v0.2.x work):**
- Locate and inventory every file that currently makes a provider call, reads/writes state, or reads a secret. Produce a one-page component map. This map becomes the input for the v0.2.x refactor plan below — do not begin building v0.2.x components until this inventory exists, since several v0.2.x steps ("extract provider calls into an adapter") are diffs against unknown current structure.

---

## 2. Milestone v0.2.x — Harden the Local Loop (single machine, single user, non-sensitive data only)

**Goal of this milestone:** turn the ad hoc loop into a durable, observable, cost-aware, single-machine system with a real (if minimal) router and a real (if minimal) task ledger — without yet introducing cloud infrastructure, additional providers, or multi-tenant concerns. This is the highest-leverage, lowest-risk step and should be completed before any cloud spend begins.

### 2.1 Files/components to add

- `secrets.env` (git-ignored) + `.gitignore` audit — confirm no secrets are committed; rotate any key found in git history.
- `ledger.db` (SQLite, WAL mode) — new local database holding a `tasks` table implementing the minimum task-contract schema (contract_version, goal_version, task_id, objective, scope_boundaries, acceptance_criteria, importance_band, effect_class_ceiling, data_classification, budget_ceiling_usd, approval_state, evidence_required, etc.).
- `provider_adapter.py` — a thin wrapper around OpenAI and Anthropic calls exposing a normalized interface (`call(model_id, messages, tools) -> response, usage`), so provider-specific quirks (reasoning tokens, cache fields) are isolated from the router.
- `router.py` — deterministic, rule-based (not LLM-based) pre-classifier that assigns a cheap/mid/flagship tier and importance band per task, plus a simple cascade-escalation function (cheap model → escalate on failed deterministic check, capped at depth 2 for v0.2.x).
- `budget_guard.py` — pre-dispatch cost reservation against a daily/monthly ceiling read from config; hard-stops dispatch when the ceiling would be breached, logs a denial event.
- `telemetry.py` — appends tokens, estimated cost, model choice, latency, and errors to a local table (`runs` or `telemetry`) per call; this satisfies the master goal's tracking requirement at local scale.
- `classification.py` — deterministic data-sensitivity tag (`public`/`internal-non-sensitive`/`sensitive`) attached to every task at creation; for v0.2.x, since no sensitive data is in scope, this exists mainly as a gate that is exercised and logged, not yet stress-tested.
- `retrieval_local.py` — Tier-1 retrieval: lexical file search + AST/symbol indexing (e.g., Tree-sitter or `ctags`-based) for the coding workload, since that is the top-priority category. No vector DB, no GraphRAG, no Graphify integration yet.
- `tests/` — acceptance test suite (see 2.3).

### 2.2 Step-by-step build sequence

1. Freeze the current loop; tag the repo state as `v0.1-baseline` for rollback reference.
2. Extract all provider calls into `provider_adapter.py`; verify the loop still produces identical output for a fixed test prompt (regression check against v0.1 behavior).
3. Introduce `ledger.db` and migrate the loop's implicit state (current goal, in-flight task) into a single row; the loop now reads/writes through the ledger instead of in-memory variables.
4. Add `telemetry.py` and wire it into every provider call; verify non-zero token/cost rows appear after a test run.
5. Add `budget_guard.py` with a conservative default daily ceiling (e.g., $5/day); verify a forced-low ceiling actually blocks dispatch and logs a denial.
6. Add `router.py` with a two-tier cascade (cheap-first, one escalation step) gated on a deterministic check (e.g., test pass/fail, schema validation, non-empty output); verify escalation triggers only on induced failure, not on every call.
7. Add `classification.py`; default every task to `internal-non-sensitive` unless explicitly tagged; verify the tag is persisted on the task row.
8. Add `retrieval_local.py` for the coding workload only; verify it returns correct symbol locations on a small test repository before wiring it into the live loop.
9. Write and run the acceptance suite (2.3); fix failures.
10. Tag the repo `v0.2.0`.

### 2.3 Acceptance criteria (v0.2.x gate)

- A task submitted through the loop produces a persisted row in `ledger.db` with a valid contract (all required fields populated).
- Every provider call produces a corresponding telemetry row with non-null token counts and an estimated dollar cost.
- Forcing the daily budget ceiling to $0 causes all dispatch to be denied and logged, with no provider call made (verified via adapter call-count assertion).
- A deliberately-broken coding task (failing test) triggers exactly one escalation to the higher-tier model, not zero and not unbounded retries (cascade depth cap verified).
- Killing the process mid-task and restarting it resumes from the last persisted task state without duplicating a completed provider call (basic idempotency: a `dispatched_at`/`completed_at` pair per step, not yet a full reconciliation state — full idempotency ledger is a v0.3 requirement).
- `git log` / secret scan confirms no API key is present in any committed file.
- Retrieval test: a query for a known function's definition location returns the correct file/line via `retrieval_local.py`, cross-checked by hand.

### 2.4 Checkpoint / Rollback for v0.2.x

**Checkpoint:** v0.2.x is complete when all acceptance criteria in 2.3 pass on a clean checkout and the system has run at least one real multi-step task (e.g., a small coding fix) end-to-end using the new ledger/router/telemetry path.

**Rollback:** because v0.2.x is entirely local (SQLite file + Python process, no cloud dependency), rollback is trivial: revert to the `v0.1-baseline` git tag and discard `ledger.db`. No data migration risk exists yet since no other system depends on this state. This is the cheapest rollback point in the entire roadmap and is the reason v0.2.x is scoped to stay local.

---

## 3. Milestone v0.3 — Cloud Deployment, Router Maturity, Security Layer, Read-Only Dashboard

**Goal of this milestone:** move the hardened loop to a single canonical cloud host with durable multi-day operation, add the goal-change governance and importance-scoring layer, add the data-classification-gated third-party provider (Gemini first, per research priority), and stand up a minimal read-only dashboard/PWA surface. This is the milestone where "hours or days with minimal human intervention" first becomes structurally supportable.

### 3.1 Files/components to add

- `infra/` — Dockerfile/devcontainer definition, deployment scripts for a single canonical VM (Fly.io or Hetzner, price-verified at provisioning time per COST_MODEL/DEPLOYMENT guidance).
- Migration of `ledger.db` (SQLite) to a managed Postgres instance (or continued SQLite-on-VM with Litestream backup, per DEPLOYMENT) — **decision point:** if concurrent workers are not yet needed, SQLite-on-one-VM with Litestream backup is acceptable and simpler; move to Postgres only when a second worker or multi-machine access is actually required (do not migrate speculatively).
- `object_store.py` — adapter for Cloudflare R2 (or equivalent) for artifacts/logs, using immutable/content-hashed keys, since native bucket versioning is unverified (per CLOUD/STORAGE track).
- `secrets_bootstrap.md` + implementation — SOPS/age-encrypted secrets file in the private repo, with a tested (not assumed) bootstrap flow for how the VM obtains a decrypted, runtime-only secrets artifact at deploy/restart. This must be tested before any real credential is deployed.
- `policy_registry.py` — versioned `provider_endpoint_policy` table (provider, model, endpoint, training-use, retention, ZDR eligibility, allowed sensitivity tier, review date) — replaces hardcoded provider assumptions and gates the classification check added in v0.2.x.
- `governance.py` — implements immutable task-contract fields, structured `change_request` objects, and the tiered approval rules (primary-goal changes always require human approval; narrowing changes may auto-accept and log; widening changes require approval).
- `importance.py` — the importance-scoring rubric (band 0–3) driving model floor, review requirement, redundancy eligibility, and budget reservation, distinct from model-reported confidence.
- `provider_gemini_adapter.py` — added behind the same `provider_adapter.py` interface, gated entirely by `policy_registry.py`; Gemini is the first non-core provider added because research ranks it highest-priority for low-cost triage and file-search/multimodal coverage.
- `retrieval_semantic.py` (Tier 2) — selective semantic search over documents/ADRs only when Tier-1 lexical/AST retrieval (v0.2.x) fails to resolve a query; uses provider-native file search as a disposable, per-task cache, not a persistent index. No vector DB, no GraphRAG at this milestone (both remain DEFERRED per CONTEXT_AND_MEMORY).
- `webhook_listener.py` — receives OpenAI background-mode/webhook completion events and Batch completion notifications; treated as an acceleration signal that triggers reconciliation against the ledger, never as the authoritative state transition.
- `dashboard/` — a minimal, read-only, server-rendered or lightweight SPA page (or a PWA shell) showing: current task/goal status, spend-to-date vs. budget, recent errors, pending approvals. No write actions in this milestone beyond an "approve/reject" button gated by authenticated session.
- `audit_log.py` — append-only, write-restricted security audit stream (actor, task ID, sensitivity class, provider/endpoint selected, approval outcomes), separate from `telemetry.py`.
- `sandbox_exec/` — containerized, egress-restricted execution environment for any generated code, replacing direct local execution.

### 3.2 Step-by-step build sequence

1. Provision the canonical VM; deploy the v0.2.x codebase unchanged as a smoke test (confirm parity before adding new components).
2. Stand up backup (Litestream or scheduled Postgres dump) and object storage; run one manual backup/restore cycle before proceeding.
3. Implement and test `secrets_bootstrap.md`; deploy real API keys only after this passes a rotation test.
4. Add `policy_registry.py` and `governance.py`; migrate `classification.py` calls to consult the registry rather than a hardcoded default.
5. Add `importance.py`; wire importance band into `router.py`'s model-floor and review-requirement decisions.
6. Add `provider_gemini_adapter.py` behind the registry gate; run a small parallel-provider comparison task (same prompt to OpenAI, Anthropic, Gemini) to confirm the adapter interface is genuinely provider-neutral.
7. Add `retrieval_semantic.py` as a fallback path only, with logging of when Tier-1 vs. Tier-2 retrieval was used, to support the later empirical retrieval benchmark.
8. Add `webhook_listener.py`; verify idempotent handling of a duplicated webhook delivery (send the same event twice, confirm no duplicate state transition).
9. Add `audit_log.py` and `sandbox_exec/`; verify a worker identity cannot write to the audit log directly (permission test).
10. Build `dashboard/` as read-only + single approve/reject action; deploy behind authenticated session with CSRF protection.
11. Run the full v0.3 acceptance suite (3.3).
12. Tag `v0.3.0`.

### 3.3 Acceptance criteria (v0.3 gate)

- The system runs unattended on the cloud VM for at least 48 continuous hours across at least one induced restart (simulated crash/reboot) with no lost task state and no duplicated external side-effect (verified via ledger + audit log inspection).
- A simulated scope-creep attempt (a planner proposing a widened effect-class ceiling) is blocked by `governance.py` and logged as a pending approval, 100% of the time across 10 induced attempts.
- A Gemini-routed task and an OpenAI-routed task both produce valid, logged, cost-tracked results through the same adapter interface, with the data-classification gate correctly refusing to route a `sensitive`-tagged test task to Gemini (or any non-core provider) in a scripted test.
- Backup/restore drill completes within the provisional Stage-0 targets (RPO ≤ 24h, RTO ≤ 8h) at least once, documented with timestamps.
- The dashboard/PWA correctly displays live spend-to-date and blocks an unauthenticated request to the approval endpoint (basic auth/CSRF test).
- Duplicate webhook delivery does not produce a duplicate task-state transition or duplicate provider call.
- Sandbox execution: a deliberately malicious test script (attempting network egress to an unlisted domain) is blocked and logged.

### 3.4 Checkpoint / Rollback for v0.3

**Checkpoint:** v0.3 is complete when the 48-hour unattended run, the governance-blocking test, the backup/restore drill, and the dashboard auth test all pass on the deployed VM, not just locally.

**Rollback/recovery:** maintain the v0.2.x local-only path as a documented fallback — if the cloud deployment fails acceptance, the system can run from a developer's machine using the v0.2.x loop while cloud issues are fixed, since no v0.3 component is a hard dependency for basic operation (Gemini, dashboard, and webhook listener are additive, not load-bearing). For infrastructure-level rollback: keep the previous VM image/snapshot until the new one has passed 48 hours of acceptance; DNS/credential cutover happens only after that window. Database rollback uses the tested backup/restore procedure from step 2 above — never an untested one.

---

## 4. Milestone v1.0 — Full Value Architecture

**Goal of this milestone:** close the remaining gaps between v0.3 and the full VALUE architecture — durable idempotency ledger, cross-provider review sampling on high-importance tasks, batch/caching cost optimization measured (not assumed), expanded but tightly-gated provider set, and a passing empirical eval suite. v1.0 is the version that can be described as "the recommended architecture," not a prototype.

### 4.1 Files/components to add

- `idempotency_ledger.py` — dedicated table (task_id, step_id, request_hash, status, result_ref, `submitted_unknown` reconciliation state) implementing application-owned idempotency, since neither OpenAI nor Anthropic guarantees exactly-once semantics on synchronous calls.
- `batch_adapter.py` — routes eligible, non-interactive, non-sensitive map-stage work (bulk classification, independent reviewer passes, corpus preprocessing) to native Batch APIs; gated by the data-classification check (batch is not ZDR-eligible on either core provider).
- `cache_policy.py` — narrow, measured prompt-caching for stable prefixes only (system prompt, tool schema, pinned repo snapshot), instrumented with hit-rate/cost logging per task template; caching is enabled per-template only after the measured ROI is positive, per COST_MODEL guidance.
- `review_sampler.py` — implements the importance-band-driven review policy: deterministic verifier always; cross-provider review sampled on Band 2–3 tasks and on the top-priority workload tiers (coding, automation, research); disagreement resolved via the evidence-first table (verifier pass/fail > evidence > human approval for irreversible/high-stakes disagreement).
- `provider_deepseek_adapter.py`, `provider_perplexity_adapter.py` (optional, gated) — added only if the empirical eval (Section 4.3) and the governance allowlist test both pass; DeepSeek restricted to `internal-non-sensitive` tasks only, enforced at the routing layer with a dedicated negative test.
- `dashboard/` upgrade — add cost-by-provider breakdown, escalation-rate chart, and pending-approval queue with expiry/escalation; PWA push notification for approvals (server-authenticated, CSRF-protected, per DEPLOYMENT guidance) — still not the agent runtime, notify/approve only.
- `eval_suite/` — the representative task suite (coding, automation, research, data, document) used to calibrate router thresholds, per EMPIRICAL_EVAL_PLAN.

### 4.2 Step-by-step build sequence

1. Implement `idempotency_ledger.py`; run the fault-injection subset relevant to duplicate dispatch (network timeout after provider acceptance, process crash mid-write) and confirm no duplicate external action occurs.
2. Implement `batch_adapter.py`; route a real independent-review workload through it and compare cost against the synchronous path over one billing cycle.
3. Implement `cache_policy.py`; instrument at least two weeks of real usage before enabling caching by default for any template, per the measured-ROI rule.
4. Implement `review_sampler.py`; run the reviewer-independence test (randomize equivalent tasks across self-review, same-provider stronger-model review, cross-provider review, deterministic-verifier-only) and only retain cross-provider review where it demonstrably reduces false-acceptance rate.
5. Run the governance/allowlist negative test for any newly added provider (DeepSeek/Perplexity) before enabling it for any live task.
6. Upgrade the dashboard/PWA with cost breakdown and approval-expiry logic.
7. Run the full `eval_suite/` and use results to set final router escalation thresholds (not desk-assumed values).
8. Run a full multi-day (5+ day) unattended soak test spanning at least one weekend, with at least one deliberately induced provider outage/rate-limit event.
9. Tag `v1.0.0`.

### 4.3 Acceptance criteria (v1.0 gate)

- Idempotency fault-injection suite passes with zero duplicated external side effects across all induced failure modes.
- Batch routing demonstrates measured (not assumed) cost savings on at least one real recurring workload, logged with before/after comparison.
- Cache hit-rate and net savings are positive and logged for every template where caching is enabled; any template with negative net savings has caching disabled.
- Reviewer-independence test shows a measurable false-acceptance reduction for cross-provider review on at least the coding and research task categories before it is retained as a default for those categories; if no measurable benefit is found, cross-provider review is scaled back to deterministic-verifier-only for that category and this is documented, not silently kept.
- Data-classification allowlist test: 100% of simulated sensitive-tagged tasks are refused routing to DeepSeek, any aggregator, or free-tier endpoints across a scripted adversarial batch.
- 5-day+ unattended soak test completes with no unrecovered crash, no silent budget breach, and correct resumption after at least one induced provider rate-limit/outage event.
- Total measured monthly spend across the soak period, extrapolated, falls within the $150/month target band (or the deviation is understood and documented against the COST_MODEL sensitivity ranges).

### 4.4 Checkpoint / Rollback for v1.0

**Checkpoint:** v1.0 is declared only after the 5-day soak test and all Section 4.3 criteria pass on the deployed system, with the eval suite results archived as the basis for the router's production thresholds.

**Rollback:** v1.0 components are additive to v0.3 and are individually feature-flagged (`batch_adapter`, `cache_policy`, `review_sampler`, each new provider adapter). Any component that fails its acceptance criterion is disabled via its flag rather than blocking the rest of the release — v1.0 rollback is therefore component-level, not all-or-nothing. The idempotency ledger is the one exception: it must pass before v1.0 is tagged at all, since every other component depends on its correctness guarantees.

---

## 5. Cross-Cutting Rollback and Recovery Strategy

- **Every milestone tag is a restorable checkpoint.** Git tags (`v0.1-baseline`, `v0.2.0`, `v0.3.0`, `v1.0.0`) plus their corresponding database schema migrations must be paired, so reverting code without reverting schema (or vice versa) is never required.
- **Database migrations are additive and reversible where feasible** (new nullable columns, new tables) rather than destructive, so a rollback to a prior code version does not require a matching destructive data migration.
- **Recovery from mid-task failure always resumes from the ledger, never from provider-side conversation state** — this is a standing invariant carried from v0.2.x through v1.0 and is directly tested at every milestone's acceptance gate.
- **Any new provider or component is added behind a flag** from v0.3 onward specifically so a bad integration can be disabled without a full rollback.
- **The backup/restore drill (Section 3.3) must be re-run after any schema change**, not just once at v0.3 — this is a recurring operational discipline, not a one-time milestone gate.

---

## 6. Immediate Next Build

The immediate next build, starting from the current working GPT↔Claude loop, is **v0.2.x Section 2**, in the exact order listed in 2.2: baseline tag → provider adapter extraction → local ledger → telemetry → budget guard → two-tier router/cascade → classification tag → Tier-1 retrieval → acceptance suite. No cloud spend, no new providers, and no dashboard work should begin before this milestone's acceptance criteria pass — the roadmap is deliberately sequenced so that the cheapest, most reversible work happens first, and cloud/security/governance investment happens only once the local system has proven it can track its own cost, state, and errors reliably.

## 7. Open Verification Gates Before Later Milestones Are Trusted

The following are explicitly carried from the research base as unresolved and must be checked before the corresponding milestone step is treated as final, not assumed true from this roadmap alone: current OpenAI/Anthropic/Gemini pricing and tier IDs (re-pull at each milestone, not hardcoded); actual achievable prompt-cache hit rate and batch discount on this workload; whether cross-provider review measurably reduces false-acceptance rate (Section 4.2 step 4); DeepSeek governance-gate effectiveness under adversarial testing; R2 versioning/backup-independence behavior; and the fencing protocol required before any automated (non-manual) failover is enabled. None of these block starting v0.2.x; several block full v1.0 sign-off per Sections 3–4.

## 8. Milestone Summary Table

| Milestone | Scope | Key new components | Cloud? | New providers | Gate |
|---|---|---|---|---|---|
| v0.1 | Baseline loop | none (inventory only) | No | OpenAI, Anthropic | Component map produced |
| v0.2.x | Local hardening | ledger, adapter, router, telemetry, budget guard, Tier-1 retrieval | No | none | Section 2.3 tests pass |
| v0.3 | Cloud + governance + dashboard | VM, backup, secrets bootstrap, policy registry, governance, importance scoring, Gemini adapter, Tier-2 retrieval, webhook listener, audit log, sandbox, read-only dashboard | Yes | + Gemini | Section 3.3 tests pass, 48h soak |
| v1.0 | Full value architecture | idempotency ledger, batch adapter, cache policy, review sampler, gated DeepSeek/Perplexity, upgraded dashboard/PWA, eval suite | Yes | + DeepSeek/Perplexity (gated) | Section 4.3 tests pass, 5-day soak |

<!-- ARTIFACT_COMPLETE -->
