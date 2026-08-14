# AI Project OS v0.3 — Phase 9 Implementation and Acceptance Contract

**Status:** approved implementation boundary

**User repository baseline:**
`afc2c683adc0fe524f020314204e4cd46e32bf80`

**Baseline tag:** `v0.3-phase8-live-canary-ready`

**Target branch:** `bootstrap/local-execution`

**Validation posture:** offline and zero external cost

## 1. Purpose

Phase 9 converts the first live canary's most informative failure into a
bounded recovery and observability tranche. It must prove that a measured
reviewer truncation can be diagnosed, costed, terminated, retried once, and
resumed in a new process without redispatching successful composition or
rewriting the artifact.

This phase improves the quality of evidence before another live canary. It is
not authorization for unattended arbitrary-goal execution.

## 2. Canary evidence accepted as input

The Phase 8 composer completed and wrote a 12,464-byte blueprint. The reviewer
used 6,759 input and 3,000 output tokens, stopped at `max_tokens`, and returned
an incomplete JSON envelope. Provider calls cost `$0.094653` in total, while
the Phase 8 project run recorded only the composer's `$0.051135`. The run
stopped at `recovery_required` and replay made no new calls.

The detailed sanitized evidence is preserved in
`docs/evidence/PHASE_8_LIVE_CANARY_FINDINGS_2026-08-14.md`.

## 3. Preserved boundaries

All Phase 1–8 controls remain active. Phase 9 must not:

- call a provider or live network during installation, tests, status, or the
  recovery canary;
- automatically launch a real live canary;
- retry a transport-ambiguous or unmeasured call;
- retry the composer or permit more than two reviewer attempts;
- let Markdown or model output change attempts, routes, providers, models,
  prices, budgets, paths, authority, or graph shape;
- parse partial/truncated JSON as success;
- overwrite the composer artifact during reviewer recovery;
- persist raw prompts, secrets, full unvalidated responses, or API keys;
- execute model-selected commands, tools, research, Git pushes, or remote
  actions;
- represent progress text or semantic review as deterministic proof;
- claim that requested future collaboration and intake features exist.

## 4. Implementation requirements

### 4.1 Known versus ambiguous failure

Normalize provider stop reasons and classify output-limit completion as
`response-truncated` before JSON parsing. If response identity and usage are
measurable, finalize the provider call and task dispatch, persist billable
cost, and return a structured task failure. Exceptions without a measurable
response remain ambiguous and human-gated.

### 4.2 Reviewer-only retry

Add `governed-live-v2` with a fixed composer-attempt ceiling of one and reviewer
ceiling of two. Only `response-truncated` may request the second attempt. All
normal project budget, time, iteration, no-progress, and authority gates must
be re-evaluated before retry.

### 4.3 Durable restart

Support an optional controlled pause after the first known retryable failure.
An explicit resume in a fresh kernel must reject nonterminal dispatch state,
retain the same run/graph/contract identity, and dispatch only the unfinished
reviewer attempt.

### 4.4 Cost truth

Failed-but-billable provider usage must appear in provider telemetry, task
cost, and project cost. Diagnostic output must show any difference instead of
silently reconciling it.

### 4.5 Diagnostics and operator status

Produce a redacted run bundle and a five-segment terminal view. The view must
state the overall objective, active/completed segment, its relation to that
objective, failure/retry status, acceptance result, cost, and next action.

### 4.6 Review envelope hardening

Use concise bounded review rationales and a 5,000-token retry ceiling. Include
the changed prompt version, token limit, and retry policy in the live approval
fingerprint.

## 5. Acceptance gates

Phase 9 is complete only when:

- migration `0008_recovery_observability` applies once with checksum
  protection and all prior migrations remain intact;
- the full Phase 1–8 regression suite passes;
- status mode makes no provider call and writes no artifact;
- the offline recovery canary makes exactly one composer and two reviewer
  fixture calls on its first run;
- reviewer attempt one is terminal `failed` with
  `failure_kind=response-truncated`, measured usage, stop reason, excerpt hash,
  and no lingering dispatch state;
- reviewer attempt two completes, acceptance is `PASS`, and the project cost
  equals all billable attempts in live-mode fixture coverage;
- the composer artifact hash is unchanged across review failure, retry, and
  process restart;
- a new kernel resumes a deliberately paused run without composer redispatch;
- completed replay makes zero new calls and does not rewrite the artifact;
- diagnostic output contains the required ledger categories, five segments,
  and useful recommendations without raw prompts or full response payloads;
- ambiguous transport failure remains `recovery_required` and is not retried;
- the package excludes mutable/runtime/private state;
- the installer preserves `.env`, does not push, and performs no network or
  provider call.

## 6. Requested future capability record

The following user goals are deliberately preserved for future phases so later
sessions do not mistake the Phase 9 fixed profile for the final system.

| Capability | Desired behavior | Required future foundation |
|---|---|---|
| Conversational goal intake | Interview the user about intent, deliverables, success, constraints, ambiguity, and human gates; compile a validated Markdown contract for approval. | Intake schema, question policy, preview/diff, contract linter, human sign-off. |
| Collaboration profiles | Select research/critic, divide-and-conquer, parallel independent solutions, cross-review, adversarial review, or consensus synthesis per goal. | Typed roles, capability/authority matrix, profile-owned DAG compiler, bounded message protocol. |
| Durable handoff capsules | Preserve decisions, evidence, assumptions, unresolved issues, artifact hashes, direction of travel, and exact next action at every handoff/restart. | Versioned capsule schema, context budgets, provenance links, stale-context detection. |
| Dynamic backlog | Safely decompose different goals into dependency-aware tasks, parallel branches, repair tasks, and multiple deliverables. | Bounded planner, graph review gate, path/authority validation, task-level acceptance. |
| Agreement and judging | Allow independent judgments, disagreement capture, discussion, revision proposals, and a final accepted synthesis without false consensus. | Multiple judge identities, calibrated rubrics, dissent records, deterministic hard gates, human escalation. |
| Research integration | Route only approved research tasks to authoritative sources and preserve claim-level provenance in handoffs. | Phase 6 provenance adapter connected to profile/task policy and network approval. |
| Human intervention queue | Present concise choices when policy, evidence, cost, business semantics, or ambiguous execution requires a person. | Durable decision records, expiration/resume rules, operator notification boundary. |
| Visible project status | Show a five-segment bar, overall objective, current task, contribution to the goal, completed evidence, blockers, cost, and estimated remaining work. | Stable status API/event projection, later local UI, eventually explicit remote/mobile authorization. |
| Overnight operation | Run approved contracts until acceptance or a hard bound, safely stop, and resume with high-fidelity context. | All above plus soak tests, quotas, alerting, recovery drills, and operator runbooks. |

These are product-roadmap requirements, not Phase 9 acceptance criteria.
Implementation order should favor truthful handoffs and reviewed goal
compilation before increasing autonomy or UI reach.

## 7. Recommended next experiment

After installing and checkpointing Phase 9, run its offline recovery canary and
review the diagnostic bundle. Then design one separately approved live recovery
canary that is small enough to finish in two calls under normal conditions but
can validate cost, latency, response compactness, acceptance, and operator
status. Do not manufacture a paid failure merely to prove the already-tested
restart path; use fixtures for deterministic failure injection.

## 8. Delivery

Delivery follows the established full-source ZIP, exact update patch, manifest,
handoff, checksums, and standalone Git Bash installer workflow. The installer
targets only the confirmed Phase 8 canary-ready commit, creates a safety tag,
preserves `.env`, runs complete offline verification, creates a local Phase 9
commit/tag, and never pushes or contacts a provider.
