# Phase 9 Live Canary Findings for Phase 10

## Decision

The Phase 9 live canary passed and produced useful Phase 10 design evidence.
No second paid Phase 9 canary is required before Phase 10 implementation.

The generated blueprint is a strong design input, not an executable
specification by itself. This review accepts it with implementation amendments.
Those amendments are incorporated into
`docs/planning/PHASE_10_IMPLEMENTATION_AND_ACCEPTANCE_CONTRACT.md`.

Phase 10 must now be built and exhausted against deterministic offline
fixtures before another live provider run is considered.

## Evidence identity

| Item | Value |
|---|---|
| Baseline commit | `07d16e5d436b7e9c0b82d79ebcbeaf8cac92657d` |
| Baseline tag | `v0.3-phase9-phase10-canary-ready` |
| Run | `phase9-live-9191df0d3a84185302bf` |
| Contract | `contract-9191df0d3a84185302bf` |
| Contract SHA-256 | `9191df0d3a84185302bf999467625403f774df385cd06675e8e7eea25c720bcf` |
| Graph SHA-256 | `5d1ce3802783654069802b1d825acbcc579d91fa0b0af44475b8f6486a0c61d6` |
| Artifact SHA-256 | `9a06088710967f424beabff4daaeda951104e801b3cc45d82eb55534d3c77c18` |
| Artifact bytes | 15,418 |
| Diagnostic SHA-256 | `b57b9b903de9de7fc04d99823bc7545cf709a729b1e4ee81556806bed5702dd3` |
| Terminal-log SHA-256 | `b1df71ae211a6125534e92a40be1b221d1460bfb03209c4889ee66045be265ea` |
| Run result | `completed / PASS / acceptance-pass` |
| Replay | completed result replayed with zero new provider calls |

The repository stores a minimized, sanitized evidence record rather than the
raw diagnostic bundle. Provider request identifiers, raw prompts, response
content, credentials, and mutable ledger state are excluded.

## Measured run results

| Signal | Composer | Reviewer | Total |
|---|---:|---:|---:|
| Provider/model | OpenAI / `gpt-5.6-terra` | Anthropic / `claude-sonnet-5` | two independent routes |
| Attempts | 1 | 1 | 2 calls |
| Input tokens | 1,141 | 7,603 | 8,744 |
| Output tokens | 3,459 | 2,277 | 5,736 |
| Latency | 40,216 ms | 20,481 ms | 60,697 ms summed |
| Actual cost | $0.0547375 | $0.0379760 | $0.0927135 |
| Quoted ceiling | $0.0756275 | $0.0939620 | $0.1695895 |
| Stop reason | `completed` | `end_turn` | no truncation |

The project completed in 60.978 seconds and consumed 18.543% of its $0.50
budget. Recorded project cost and provider-call cost reconciled exactly.
Actual cost was 54.669% of the pre-dispatch quote. There were no retries,
known truncations, errors, no-progress events, or human decisions.

Acceptance recorded 10 of 10 required criteria as `PASS` and zero of six hard
constraints as violated. That is evidence that the Phase 9 parser, routing,
telemetry, semantic review, deterministic checks, artifact preservation, and
idempotent completed replay worked on the happy path. It is not evidence that
the proposed Phase 10 revision loop already works.

## What the blueprint did well

The blueprint provides a coherent bounded revision cycle with explicit
terminal outcomes. Its strongest design contributions are:

- criterion-linked, evidence-bearing reviewer findings;
- immutable artifact identities, before-and-after hashes, and rollback;
- separation of candidate artifacts from the last accepted artifact;
- a continuation capsule that preserves goal, current state, decisions,
  unresolved findings, budgets, direction of travel, and exact next action;
- attempt, cost, time, repeated-finding, repeated-change, regression, and
  no-progress bounds;
- human gates for ambiguity, disagreement, authority expansion, and ambiguous
  provider execution;
- a useful edge-case matrix and measurable evidence plan;
- named extension seams for later intake, research, collaboration profiles,
  dynamic work graphs, artifact sets, and remote status.

The artifact is internally consistent and unusually specific for a single
composer/reviewer pass. The independent reviewer accepted all mapped criteria,
and deterministic controls confirmed the required sections, declared output,
workspace confinement, and planning-only scope.

## Required implementation amendments

The following gaps are not reasons to rerun the canary. They are decisions the
application must make before Phase 10 code is accepted.

1. **Finding semantics.** Keep `verdict` and `severity` separate. `PASS` is a
   verdict, not a severity. Add schema version, source role, lifecycle status,
   timestamps, and supersession linkage.
2. **Acceptance precedence.** Hard constraints outrank deterministic evidence,
   which outranks semantic opinion. Conflicts never silently select the more
   convenient result.
3. **Repair eligibility.** Automatic revision is permitted only for a
   criterion-linked, bounded, non-authority-increasing change. Unknown business
   intent and semantic ambiguity require a human decision.
4. **Durable data model.** Phase 10 needs an explicit migration, foreign keys,
   uniqueness constraints, indexes, and idempotency rules rather than prose-only
   records.
5. **Artifact atomicity.** Bounded artifact bytes are stored immutably in
   SQLite. A candidate must not overwrite the accepted workspace output. Only
   acceptance may atomically materialize the declared path.
6. **Provider ambiguity.** Persist the dispatch claim and continuation capsule
   before a call. Once a request may have left the process, an unknown result is
   never automatically repeated.
7. **Human-decision freshness.** A decision must be bound to a run state,
   artifact/finding fingerprint, option set, scope, and expiry. Stale or
   tampered decisions are rejected.
8. **No-progress math.** Define normalization, finding-set fingerprint,
   artifact-change fingerprint, criterion weights, and regression baseline in
   application code.
9. **Privacy boundary.** Diagnostics retain hashes, usage, stop reason, failure
   class, and a bounded redacted excerpt only when needed. They do not require
   full raw provider output.
10. **Cancellation.** Cancellation is a first-class transition that creates a
    continuation capsule and leaves the last accepted artifact untouched.
11. **Budget accounting.** Reserve quoted cost before dispatch and reconcile
    actual billable cost even when parsing or validation fails after a provider
    response.
12. **Strict response contracts.** Revision and review responses require
    versioned JSON schemas, exact enum values, bounded arrays/strings, and
    rejection of trailing or duplicate objects.
13. **Adversarial tests.** Add malformed findings, unauthorized repair, replay,
    transition crashes, stale/tampered capsules, concurrency, migration
    compatibility, exact rollback, repeated patches/findings, regression,
    disagreement, budget denial, truncation, and ambiguous dispatch fixtures.
14. **Operator usefulness.** Replace an undefined qualitative threshold with a
    five-point human rubric; require at least 4/5 overall and no safety or next-
    action field below 4 for the later live acceptance canary.
15. **Latency interpretation.** Preserve raw state and call latency. Do not
    report percentiles as meaningful until a multi-case benchmark exists.
16. **Independent truth.** A model reviewer cannot be the only proof that a
    model-produced design is correct. Deterministic invariants and a human
    evidence review remain required.
17. **Deferred interfaces.** Later roadmap seams are versioned and documented,
    but Phase 10 must not implement dynamic collaboration, live research,
    multi-artifact projects, goal interviews, or remote control by implication.

## Phase 10 consequences

Phase 10 should implement one narrow profile: a bounded revision of one
declared Markdown artifact. The application—not either model—owns the state
machine, policy, routes, budget, file paths, acceptance precedence, and stop
rules. Provider output proposes content and findings; it does not grant itself
authority or choose whether a hard gate is ignored.

The implementation sequence should be:

1. schema migration and strict data contracts;
2. immutable artifact and finding repositories;
3. fixed application-owned revision state machine;
4. deterministic fixture gateway and adversarial recovery suite;
5. operator status, continuation, and human-decision commands;
6. complete offline regression and restart testing;
7. packaging and a new local checkpoint;
8. only then, design a separately approved small live Phase 10 canary.

## Evidence limits

This was one happy-path live sample with two calls. It demonstrates that the
current governed handoff can produce a substantial artifact, accept it, record
cost and latency, and replay without new spend. It does not exercise automatic
revision, disagreement, regression, no progress, cancellation, crash recovery,
or human decisions. Those branches belong in deterministic Phase 10 fixtures.

No user qualitative rubric was collected for this artifact. That is not a
Phase 10 implementation blocker; the rubric becomes a required input for the
later Phase 10 live acceptance canary.
