# Phase 10 Implementation and Acceptance Contract

## Status and authority

- Status: approved implementation contract; code not started by this checkpoint.
- Baseline: `07d16e5d436b7e9c0b82d79ebcbeaf8cac92657d` on
  `bootstrap/local-execution`.
- Evidence source: the successful Phase 9 run recorded in
  `docs/evidence/PHASE_9_PHASE10_LIVE_CANARY_FINDINGS_2026-08-15.md`.
- Target profile: `governed-revision-v1`.
- Implementation mode: offline deterministic fixtures first.
- Live provider authority: absent during implementation and installation.
- External side effects: prohibited.

This contract translates the canary blueprint into application-owned rules.
If implementation convenience conflicts with this document, the bounded and
human-gated behavior in this document wins.

## Phase 10 objective

Implement a durable, bounded revision cycle for one declared Markdown artifact.
The cycle must turn strict, criterion-linked reviewer findings into either a
safe candidate revision, a terminal accepted result, a bounded stop with a
continuation capsule, or an explicit human-decision request.

The system must never overwrite the last accepted artifact with an unaccepted
candidate. It must resume after interruption without duplicate provider
dispatch, preserve the overall goal and direction of travel, expose five
goal-relative progress segments, and explain the exact next authorized action.

## Definition of done

Phase 10 is complete only when all of the following are true:

1. migration `0009_bounded_revision_cycle` is durable, idempotent, compatible
   with existing ledgers, and covered by schema tests;
2. versioned strict schemas exist for reviewer findings, revision proposals,
   continuation capsules, and human decisions;
3. artifact candidates and accepted versions are immutable and content-addressed;
4. the application owns a fixed bounded state machine and deterministic
   acceptance precedence;
5. all stop, crash, cancellation, ambiguity, no-progress, regression, budget,
   and human-gate branches preserve a valid continuation record;
6. status output shows the overall goal, a five-segment progress view, current
   step, relationship to the goal, cost, bounds, and next action;
7. deterministic fixtures prove restart safety and zero duplicate dispatch;
8. the complete Phase 1-10 offline suite passes twice against the same ledger;
9. installation performs no provider or live network call and preserves `.env`;
10. a separate future live canary remains inactive pending human review of a
    new exact approval fingerprint.

## Scope

Phase 10 includes:

- one project run and one declared Markdown output;
- an initial accepted or reviewable artifact version;
- strict typed review findings;
- a maximum of two candidate revision attempts by default;
- deterministic candidate validation and semantic review;
- comparison with the previous accepted or reviewed baseline;
- automatic revision only inside pre-authorized paths and policy;
- immutable artifact, finding, decision, and attempt history;
- continuation capsules and restart/resume;
- cancellation, bounded stops, and human-decision gates;
- offline simulated composer, reviewer, reviser, truncation, failure, and crash
  fixtures;
- sanitized diagnostic export and five-segment local status.

## Non-goals

Phase 10 does not implement:

- conversational goal interviews or automatic goal-to-contract synthesis;
- dynamic or model-authored task graphs;
- configurable multi-agent collaboration profiles;
- live web research or autonomous source discovery;
- multiple declared deliverables or repository-wide code repair;
- background daemons, overnight scheduling, remote dashboards, notifications,
  or remote human approval;
- automatic provider/model/authority/budget selection;
- paid failure injection;
- automatic resolution of disputed business intent;
- a production claim based only on one live canary.

These remain explicit later-phase capabilities. Phase 10 provides versioned
interfaces for them but does not simulate their existence.

## Application-owned invariants

The following values come from validated policy or human approval and cannot be
changed by model output:

- workspace root and declared artifact path;
- provider and model routes;
- provider-call count, per-call token ceilings, total cost, runtime, and
  revision-attempt limits;
- hard constraints and acceptance precedence;
- whether a finding is structurally eligible for automatic revision;
- allowed state transitions;
- human-gate conditions;
- diagnostic redaction policy;
- the last accepted artifact identity.

A provider response is untrusted data until its exact schema, size, enums,
hashes, references, and authority boundaries validate.

## Migration `0009_bounded_revision_cycle`

The migration must use foreign keys, checks, uniqueness constraints, and indexes
consistent with the existing SQLite ledger conventions. It adds at least these
logical records; names may change only if the semantics and evidence remain
identical.

### `artifact_versions`

Required fields:

- `version_id` — content-addressed or deterministic immutable identifier;
- `run_id`, `logical_path`, `parent_version_id`;
- `content_bytes` — bounded Markdown bytes stored transactionally;
- `content_sha256`, `byte_count`, `media_type`;
- `source_task`, `source_attempt`, `status`;
- `created_at`, `accepted_at`, `superseded_at`.

Allowed status values are `candidate`, `accepted`, `rejected`, and
`superseded`. A unique constraint prevents conflicting content for the same
version identity. Accepted versions are never updated in place.

### `review_findings`

Required fields:

- `finding_id`, `schema_version`, `run_id`, `evaluation_id`, `version_id`;
- `criterion_key`, `verdict`, `severity`, `fingerprint`;
- bounded JSON evidence references;
- `observed`, `expected`, `proposed_action`;
- `repair_eligibility`, `human_decision_reason`;
- `source_role`, `status`, `supersedes_finding_id`;
- `created_at`, `resolved_at`, `superseded_at`.

`verdict` is one of `PASS`, `REPAIR`, `BLOCK`, `HUMAN_DECISION`. `severity` is
separate and one of `none`, `low`, `medium`, `high`, `critical`. Finding status
is one of `open`, `targeted`, `resolved`, `superseded`, `human_pending`.

### `revision_attempts`

Required fields:

- `revision_attempt_id`, `run_id`, `ordinal`;
- baseline and candidate version identifiers;
- target-finding-set SHA-256 and normalized plan SHA-256;
- status and terminal reason;
- quoted, reserved, actual, and reconciled cost;
- started, deadline, completed, and updated timestamps;
- deterministic validation result, semantic result, comparison result;
- provider dispatch and continuation references.

`(run_id, ordinal)` and attempt idempotency keys are unique.

### `continuation_capsules`

Required fields:

- `capsule_id`, `schema_version`, `run_id`, `state`;
- overall goal and contract hash;
- accepted, baseline, and candidate version identifiers and hashes;
- open finding-set hash and bounded finding summaries;
- decision-log hash and unresolved human gate;
- policy, spent/reserved budget, deadline, attempts, no-progress count;
- direction-of-travel summary;
- exact `next_action` enum and required inputs;
- payload SHA-256, created time, consumed time, supersession reference.

Capsules are immutable. Consuming the same capsule twice is idempotent; two
workers must not both acquire continuation authority.

### `human_decisions`

Required fields:

- `decision_id`, `schema_version`, `run_id`, `gate_kind`;
- state, artifact, finding-set, and option-set fingerprints;
- bounded options and selected option;
- scope, rationale, decider label, decided time, expiry time;
- consumption and supersession fields.

Decisions with stale fingerprints, changed options, expired scope, or expanded
authority are rejected before any dispatch or write.

## Strict provider contracts

Provider envelopes must contain exactly one JSON object and no trailing prose.
All strings and arrays have application-set byte/item limits. Unknown fields
are rejected unless the schema explicitly permits an extension namespace.

### Reviewer finding response `phase10-review-v1`

The response contains:

- `schema_version` exactly `phase10-review-v1`;
- `artifact_sha256` matching the candidate under review;
- `overall_verdict`;
- zero or more typed findings in stable criterion order;
- `criterion_results` covering every required criterion exactly once;
- bounded `summary` and `recommended_next_action`.

Each finding includes all fields defined for `review_findings`. A `PASS`
criterion cannot carry an open repair finding. Duplicate finding identifiers,
unknown criteria, invalid evidence references, contradictory eligibility, or
an artifact-hash mismatch invalidate the whole response.

### Revision proposal `phase10-revision-v1`

The response contains:

- `schema_version` exactly `phase10-revision-v1`;
- baseline artifact and finding-set hashes;
- the target finding identifiers;
- a bounded revision rationale;
- the complete candidate Markdown content;
- claimed resolved and intentionally deferred findings;
- no routes, tools, paths, policy changes, or authority requests.

The application calculates all hashes. Provider-supplied hash claims are
checked but never trusted as the stored identity.

## Repair eligibility

A finding is automatically repairable only if all conditions hold:

- its verdict is `REPAIR` and its status is `open`;
- it maps to an existing required criterion;
- evidence references the current baseline artifact;
- observed, expected, and proposed action are concrete and mutually consistent;
- the change affects only the declared Markdown content;
- no hard constraint, route, path, provider, budget, tool, external action, or
  human authority is added or weakened;
- no unknown business intent, disputed judgment, or safety ambiguity remains;
- the attempt, time, cost, repetition, and no-progress bounds permit work.

Any failed condition changes the action to `HUMAN_DECISION` or `BLOCK`; it must
not be weakened to an automatic repair by a model recommendation.

## State machine

The application permits only these logical states:

1. `INTAKE_VALIDATED`
2. `BASELINE_PRESERVED`
3. `REVIEW_CLAIMED`
4. `REVIEW_RECORDED`
5. `REVISION_PLANNED`
6. `REVISION_CLAIMED`
7. `CANDIDATE_PRESERVED`
8. `CANDIDATE_VALIDATED`
9. `COMPARISON_RECORDED`
10. `ACCEPTED`
11. `HUMAN_DECISION_REQUIRED`
12. `RECOVERY_REQUIRED`
13. `BOUNDED_STOP`
14. `CANCELLED`

Each transition is one transaction that records the prior state, event,
idempotency key, relevant hashes, cost state, and next-action capsule. Invalid
or skipped transitions fail closed.

Before any provider dispatch the application must transactionally:

1. reserve the worst-case quoted cost;
2. create an attempt/dispatch claim;
3. create a continuation capsule identifying the possible in-flight call;
4. commit those records;
5. only then call the provider.

If the process cannot prove whether a claimed call reached a provider, it
enters `HUMAN_DECISION_REQUIRED` with reason `ambiguous-dispatch`; it does not
automatically repeat the call.

## Acceptance precedence

The decision order is deterministic:

1. any hard-constraint violation -> `BLOCK`;
2. any invalid schema, missing evidence, artifact mismatch, or ambiguous
   dispatch -> `HUMAN_DECISION` or `RECOVERY_REQUIRED` as prescribed;
3. deterministic required-criterion failure -> `REPAIR` when eligible,
   otherwise `BLOCK` or `HUMAN_DECISION`;
4. deterministic pass plus semantic `REPAIR` -> repair only when the typed
   finding is eligible; otherwise human decision;
5. deterministic/semantic disagreement involving `PASS` versus `BLOCK`, an
   unknown criterion, or business intent -> `HUMAN_DECISION`;
6. all hard constraints clear and every required criterion deterministically
   and semantically resolved -> `PASS`.

No majority vote, model confidence score, or later response may override a hard
constraint.

## Artifact safety and materialization

Candidate content is stored in `artifact_versions` before validation. The
declared workspace output remains the last accepted bytes throughout review.
On acceptance the application:

1. rechecks candidate hash and all policy/acceptance fingerprints;
2. writes the candidate to a confined temporary file;
3. fsyncs where supported and atomically replaces the declared output;
4. verifies materialized bytes and hash;
5. marks the candidate accepted in the same recoverable protocol;
6. retains every earlier version and exact rollback target.

A crash between file replacement and ledger finalization must reconcile by
content hash without losing either version. Rejection, cancellation, bounds,
or human escalation never replaces the accepted output.

## Progress, bounds, and comparison

Default policy for the offline profile:

- maximum candidate revisions: 2;
- maximum total provider dispatches: 5;
- maximum repeated normalized finding set: 1 after its first occurrence;
- maximum repeated normalized candidate change: 1 after its first occurrence;
- maximum consecutive no-progress revisions: 1;
- maximum runtime: 600 seconds;
- project cost ceiling: fixture `$0.00`; later live value requires approval;
- no authority expansion.

Normalization removes volatile timestamps and identifiers, canonicalizes JSON,
normalizes Markdown line endings and trailing whitespace, and hashes stable
criterion/finding/change structures. A finding fingerprint covers criterion,
verdict, severity, normalized observed/expected/action, and evidence identities.

Comparison records per-criterion outcomes against the prior reviewed baseline:

- `improved` — an open required finding resolves without a new equal/higher
  severity failure;
- `unchanged` — normalized findings and content direction do not materially
  improve;
- `regressed` — a passed criterion fails, severity increases, a hard constraint
  is threatened, or a previously resolved finding reopens;
- `incomparable` — evidence is missing or business intent is disputed.

`regressed` stops automatic revision and requires human review. `unchanged`
increments no progress. `incomparable` never becomes an automatic pass.

## Cost accounting

The gateway reserves the full quoted maximum before dispatch. On any identified
provider response it records usage, stop reason, latency, response hash, and
billable cost even if response parsing later fails. Reservation is reconciled
to actual cost exactly once. An unavailable usage report retains the reservation
and creates a cost-uncertain human gate rather than assuming zero.

Project cost equals the sum of reconciled call cost plus unresolved reservations.
Budget denial occurs before dispatch claim when worst-case cost would cross the
ceiling.

## Cancellation and human decisions

Cancellation is accepted only at an application-owned transition boundary. It
records `CANCELLED`, preserves the last accepted artifact, marks any candidate
non-accepted, reconciles known cost, and creates a capsule whose next action is
`resume_after_cancellation` or `close_run`.

Human gates use a local command that displays:

- overall goal and current five-segment status;
- the exact conflict and supporting hashes/evidence;
- last accepted and candidate identities;
- cost and remaining bounds;
- a bounded option set with consequences;
- whether each option changes authority;
- the exact command for recording a decision.

The command must not silently choose a default. A decision is accepted only
when its fingerprints match the current state.

## Continuation quality

Every nonterminal stop and every possibly in-flight call has a continuation
capsule committed before control returns. Resuming from a capsule must answer:

- What is the overall goal?
- Which of the five segments is active?
- What has completed and what evidence proves it?
- Which artifact is accepted, which is candidate, and what are their hashes?
- Which findings remain and how did they change?
- What decisions were made and which human choice is pending?
- What cost, time, attempts, and authority remain?
- What direction was the work taking and why?
- What exact next action is authorized?
- What actions are prohibited without new approval?

Tampered, stale, superseded, or concurrently consumed capsules fail closed.

## Operator status

All status and run modes render five stable segments:

1. `Govern` — contract, authority, budget, routes, integrity;
2. `Plan` — baseline, finding set, eligible work, bounds;
3. `Revise` — current attempt and candidate preservation;
4. `Verify` — deterministic checks, semantic review, comparison;
5. `Handoff` — acceptance, human gate, recovery, cancellation, or bounded stop.

Output also includes the overall objective, current-step relationship to that
objective, completed/total work, spent/reserved budget, elapsed/deadline,
accepted/candidate short hashes, stop reason, and exact next action. Status-only
mode makes no provider call and writes no artifact.

## Diagnostics and privacy

Diagnostic bundles include stable identifiers, states, timestamps, hashes,
attempts, transition events, criterion verdicts, redacted finding summaries,
cost/usage/latency/stop reason, failure class, continuation identity, and
recommended next actions.

They exclude credentials, environment contents, full raw prompts, full raw
responses, provider request identifiers from the sanitized export, and artifact
content unless the user explicitly selects that artifact. A failure may retain
a bounded redacted excerpt only when required to diagnose strict parsing.

## Required deterministic test matrix

### Schemas and migration

- fresh migration and repeat migration;
- upgrade from the Phase 9 ledger;
- foreign-key, uniqueness, enum, and size violations;
- malformed, duplicate, trailing, unknown-field, and contradictory JSON;
- separate verdict/severity and complete criterion coverage.

### Artifact history

- immutable candidate and accepted content;
- candidate rejection leaves accepted output byte-identical;
- atomic acceptance and exact rollback;
- crash before and after materialization with hash reconciliation;
- undeclared path, traversal, link escape, and oversized artifact denial.

### Findings and acceptance

- eligible criterion-linked repair;
- missing evidence, unknown criterion, business ambiguity, and authority change;
- deterministic/semantic disagreement in both directions;
- hard constraint precedence;
- resolved, reopened, superseded, and duplicate findings;
- reviewer PASS with a contradictory open finding is rejected.

### Revision bounds

- successful improvement and acceptance;
- same normalized finding set;
- same normalized patch/content change;
- no progress;
- criterion regression and severity increase;
- attempt, runtime, and cost exhaustion;
- second failure after an allowed measured truncation.

### Recovery and idempotency

- process crash at every state transition boundary;
- restart before dispatch, during possible dispatch, after response, after
  candidate preservation, after validation, and after acceptance;
- known no-call retry versus ambiguous-dispatch human gate;
- completed replay with zero new calls;
- stale, tampered, superseded, and double-consumed capsules;
- two concurrent resume attempts with one winner;
- cancellation at each safe boundary.

### Human authority

- fresh matching decision accepted;
- stale, expired, altered-option, wrong-artifact, and expanded-authority decision
  rejected;
- no default decision and no provider call while human input is pending.

### Cost and diagnostics

- budget denial before dispatch;
- failed-but-billable response reconciliation;
- missing usage retains reservation and gates continuation;
- exact project/provider sum;
- diagnostics identify the failing state and file/module without secrets;
- status-only is read-only and provider-free.

## Offline acceptance gates

The Phase 10 implementation package must report all gates as `PASS`:

1. **Schema gate:** migration and strict contracts pass.
2. **History gate:** candidates cannot overwrite accepted bytes.
3. **Finding gate:** typed findings and eligibility rules pass.
4. **Precedence gate:** constraints and disagreement route correctly.
5. **Revision gate:** a deterministic repair improves and is accepted.
6. **Regression gate:** regression stops without corrupting accepted output.
7. **Bounds gate:** repetition, no progress, attempt, runtime, and budget stop.
8. **Recovery gate:** transition crash matrix resumes without duplicate calls.
9. **Ambiguity gate:** possibly dispatched work is never automatically repeated.
10. **Human gate:** fresh scoped decisions work; stale authority does not.
11. **Observability gate:** five segments, goal relationship, diagnostics, and
    continuation next action are complete.
12. **Replay gate:** completed replay adds zero dispatches and preserves hashes.
13. **Regression-suite gate:** all Phase 1-9 tests remain green.
14. **Installer gate:** `.env` is byte-identical and calls/network/cost are zero.

The complete suite must pass twice on the same local ledger. A fixture run must
also be interrupted and resumed in a new process.

## Later live-canary gate

Phase 10 implementation does not itself authorize a live run. After all offline
gates pass, a separate review may prepare one small canary with:

- a new exact contract and approval fingerprint;
- explicit provider/model/token/cost ceilings;
- one deliberately repairable Markdown defect, not a manufactured provider
  failure;
- an independent reviewer before and after revision;
- at most one automatic revision;
- immutable before/candidate/accepted evidence;
- replay with zero new calls;
- a human qualitative rubric scored 1-5 for correctness, usefulness, traceability,
  recovery context, and operator clarity.

Live acceptance requires at least 4/5 overall and no safety, traceability,
recovery-context, or next-action score below 4. Any disagreement or authority
question ends at a human gate.

## Delivery requirements

The Phase 10 implementation checkpoint will include:

- source snapshot and exact reviewed patch from this planning baseline;
- migration, implementation modules, offline fixtures, and tests;
- implementation and operator documentation;
- machine-readable change manifest and SHA-256 checksums;
- a Git Bash installer that targets the exact planning-ready commit, preserves
  `.env`, creates a safety tag, runs all offline gates, commits locally, and
  never pushes or contacts providers;
- a handoff stating known limitations and the commands required to verify and
  push the checkpoint.

## Future roadmap interfaces

Phase 10 may define but must not activate these versioned inputs/events:

- `GoalIntakeApproved.v1` for later conversation-to-contract intake;
- `ResearchEvidenceRef.v1` for provenance-backed research;
- `CollaborationProfileRef.v1` for future team work patterns;
- `WorkGraphProposal.v1` for human-approved dynamic backlogs;
- `ArtifactSetManifest.v1` for multiple deliverables;
- `StatusExportRequest.v1` for later local/remote visibility.

Unknown interface versions are rejected. None of these events can expand an
active run's authority without a fresh human approval bound to the new policy
fingerprint.
