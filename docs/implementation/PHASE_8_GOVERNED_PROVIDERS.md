# Phase 8 Governed Provider Orchestration

**Status:** implemented and verified with offline provider fixtures

**Live profile:** `governed-live-v1`

**Default state:** provider execution disabled

**Installation/test cost:** `$0.00`

## Execution shape

Phase 8 extends the durable Phase 7 kernel with a fixed two-task profile:

1. the approved composer route returns a strict JSON envelope containing one
   Markdown artifact;
2. the approved reviewer route returns a strict JSON envelope containing exact
   criterion and constraint assessments.

The task graph, dependencies, file path, authority, attempt count, budget
allocations, prompt templates, response schemas, provider routes, and model
routes are application-owned. Contract or model text cannot change them.

The composer writes through `DeclaredArtifactWriter`, which accepts only the
single path declared in the Markdown contract. The reviewer receives a read-
only copy of that artifact. Phase 8 does not support commands, code execution,
research retrieval, arbitrary tools, additional files, or external mutations.

## Contract invariants

The safe parser default remains `offline-checklist-v1`. Selecting
`governed-live-v1` additionally requires:

- authority `live-network`;
- positive budget no greater than `$5`;
- one Markdown deliverable below `outputs/`;
- at most four tasks, eight iterations, two no-progress results, and 600
  seconds;
- deterministic criteria `deliverable-exists` and `required-sections`;
- controls `workspace-confined`, `declared-artifact-only`, and
  `no-external-side-effects`.

The shipped proposed canary is stricter: two tasks, four iterations, one
no-progress result, 300 seconds, and `$0.50` total budget.

## Durable provider boundary

`GovernedProviderGateway` requires an explicit execution mode:

- `offline-simulation` accepts only a client marked as an offline fixture;
- `live` rejects fixture clients and requires a previously matched approval
  fingerprint.

The route allowlist matches provider, model, and maximum output tokens exactly.
A conservative quote treats UTF-8 prompt bytes as the maximum possible input
token count and adds the full approved output-token cost. The quote must fit
the task allocation before the existing `BudgetGuard` reserves daily, monthly,
and project/task capacity.

Migration `0007_governed_provider_calls` records the call claim before adapter
dispatch. It stores prompt hashes rather than raw prompts and stores only a
validated parsed payload rather than unconstrained raw response text. Usage,
estimated cost, response hash, provider request id, latency, stop reason, and
safe errors remain inspectable.

An existing call identity—completed, failed, or still dispatching—is never
automatically sent again. An adapter exception or invalid response leaves the
orchestration task ambiguous and the run in `RECOVERY_REQUIRED`.

## Strict response envelopes

The composition response contains exactly:

- `artifact_markdown`;
- `assumptions`;
- `criterion_notes`, with every criterion identity exactly once.

The review response contains exactly:

- ordered `criteria`, with every identity and one of `PASS`, `FAIL`, `UNKNOWN`,
  or `DISPUTED`;
- ordered `constraints`, with every identity and a Boolean violation finding;
- `overall_notes`.

JSON fences, prose wrappers, duplicate or unknown identities, unknown fields,
missing fields, oversized values, invalid verdicts, and route/usage anomalies
fail closed.

## Evidence and acceptance

Artifact existence and required level-two headings are checked
deterministically, even if the semantic reviewer says they pass. Other
criterion verdicts are recorded as `SEMANTIC_REVIEW`, not deterministic truth.
Workspace/path/external-effect constraints are linked to application-owned
control evidence; a reviewer-reported violation still blocks the run.

The Phase 6 acceptance engine aggregates the complete evidence set. `PASS`
completes the project. `FAIL` becomes `REPAIR`; `UNKNOWN` becomes `DEFER`; a
constraint violation becomes `BLOCK`. Phase 8 intentionally does not overwrite
or repair the artifact after review. This makes first-canary defects observable
inputs to Phase 9 rather than hiding them behind unbounded retries.

## Commands

Safe offline commands:

```powershell
python run_phase8.py --status-only
python run_phase8.py --mock-canary
python run_phase8.py --prepare-live
```

Status and preparation do not instantiate a provider client or write an
artifact. Mock mode uses a separate contract/output and an in-memory client;
its simulated usage is recorded but external cost is zero. A repeat invocation
must report completed replay with zero new provider calls.

The later live canary requires the exact token printed by preparation:

```powershell
python run_phase8.py --live --approval phase8-live-<prepared-fingerprint>
```

The fingerprint covers contract and graph hashes, both routes and models,
token limits, price inputs, project/daily/monthly budgets, and template
versions. Any change requires a new preparation and human review.

## Current boundary

Phase 8 proves a bounded, measurable provider round trip for one Markdown
artifact. It does not yet dynamically decompose arbitrary goals, repair failed
work, compare multiple revisions, execute code, perform live research, resolve
ambiguous calls automatically, expose remote status, or establish production
quality from one canary. Those are governed Phase 9 and later concerns.
