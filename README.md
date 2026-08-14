# AI Loop — v0.3 Candidate Foundation

This is a portable forward-development candidate derived from the proven local
v0.2 durable orchestrator. It is separate from the frozen v0.2 backup, which
must remain unchanged.

The current code still implements the known-good four-stage workflow:

1. OpenAI architect
2. Anthropic executor
3. OpenAI auditor
4. Anthropic revision

The v0.3 bootstrap is being implemented in bounded offline phases. Phase 1
provides guarded local command execution; Phase 2 adds normalized durable
validation; Phases 3 and 4 add controlled patches, Git checkpoints, and
rollback; Phase 5 adds the bounded repair state machine. Live repair-provider
integration remains deliberately disabled pending explicit provider and budget
approval. Phase 6 adds offline research provenance and acceptance/truth
governance. Phase 7 adds the first durable Markdown-contract runner using a
deterministic zero-cost checklist profile. Phase 8 adds an opt-in, fingerprint-
approved provider profile with strict response schemas, durable call
provenance, dual budget gates, and an offline simulated canary.
Phase 9 classifies known provider failures, performs one policy-bounded reviewer
retry, accounts for failed-but-billable attempts, emits redacted diagnostics
and five-segment progress, and proves restart/resume without redispatching the
accepted composer artifact.

## What is preserved

- durable SQLite tasks, steps, telemetry, reservations, and events;
- completed-step idempotency and restart/resume;
- pre-dispatch budget enforcement;
- sensitive-data blocking for the local v0.2.x runtime;
- deterministic routing and one-step escalation policy;
- local lexical and Python symbol retrieval;
- the accepted v0.2.1 architecture package and validator calibration evidence;
- the historical ledger, with its artifact paths migrated to project-relative form.

## Portable layout

Runtime paths default to locations relative to this project:

```text
project/goal.md
ledger.db
outputs/
```

New artifact paths are stored in SQLite with forward slashes, for example
`outputs/01_gpt_brief.md`. Legacy absolute paths ending in `outputs/...` are
migrated automatically when the ledger opens.

The portable-review archive intentionally excluded `outputs/`. The historical
ledger therefore retains completed-step and telemetry evidence, but its eight
referenced output files are not present. A full run with the same task ID will
mark the first unavailable completed artifact as missing and regenerate work
subject to the normal budget guard. It will not silently treat a missing file as
a reusable result.

## Setup

Use Python 3.12 and create or activate a virtual environment. The environment
may live in this project or at its parent workspace level.

```powershell
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add real keys only to `.env`:

```powershell
Copy-Item .env.example .env
```

Do not overwrite an existing `.env`, commit it, upload it, or paste its values
into logs.

## Offline verification

Run the regression suite first:

```powershell
python -m pytest -q
```

Then run the real offline preflight:

```powershell
python run_loop_v0_2.py --preflight-only
```

`--preflight-only` does not construct provider clients or make paid API calls.
It checks the goal, SQLite integrity, persisted artifact paths, output location,
and whether both key variables are present. Missing historical output files are
reported as warnings. Missing keys are reported by variable name only, never by
value.

## Live run

Only after reviewing preflight, task scope, and budget settings:

```powershell
python run_loop_v0_2.py
```

The task ID is deterministic from `project/goal.md`. Set `TASK_ID` explicitly
only when intentionally starting a separate run for the same goal.

## Forward-development boundary

- Make v0.3 changes only in this candidate or another disposable copy.
- Do not merge into or overwrite the frozen v0.2 baseline automatically.
- Keep the real workbook project out-of-sample until the five planned benchmark
  projects have been run and reviewed.
- Do not launch the overnight contract until its provider budgets and maximum
  duration are populated and explicitly approved.

See `docs/planning/AI_PROJECT_OS_V0_3_SAVEPOINT_2026-08-09.md` for the current
savepoint and `CHANGELOG_PORTABILITY_CLEANUP.md` for this cleanup's full audit.

## Bootstrap Phase 1: local execution boundary

The first offline v0.3 bootstrap tranche is implemented in:

- `workspace_guard.py` — project-root confinement, protected paths, immutable
  paths, traversal rejection, and link-aware resolution;
- `command_runner.py` — structured allowlisted subprocess execution with no
  shell, bounded output, timeouts, scrubbed environments, redaction, and an
  optional durable JSONL event sink;
- `tests/test_workspace_guard.py` and `tests/test_command_runner.py` —
  adversarial offline regression coverage.

Run all Phase 1 and preserved v0.2 tests with:

```powershell
python -m pytest -q
```

These modules are a policy layer, not an operating-system sandbox. In
particular, an allowlisted Python interpreter can perform any action permitted
to its Windows process if callers allow arbitrary Python arguments. Production
callers must use narrow executable argument-prefix rules and must not treat the
workspace guard as containment for hostile code.

See `docs/implementation/BOOTSTRAP_PHASE_1.md` for the supported API, example
policy, verified behavior, and remaining limitations.

## Bootstrap Phase 2: durable validation

Phase 2 adds:

- `test_runner.py` - normalized Python syntax, pytest, selected-command, file,
  and JSON checks;
- `durable_execution.py` - atomic command claims, request fingerprints,
  execute-once behavior, and terminal-result replay;
- additive `commands` and `validation_runs` tables managed by `ledger.py`;
- `run_bootstrap_phase2.py` - the offline Phase 2 entry point.

After backing up `ledger.db` as described in `PHASE_2_INSTALLATION.md`, run:

```powershell
python run_bootstrap_phase2.py --status-only
python run_bootstrap_phase2.py
```

The status command applies the checksummed additive schema migration and checks
SQLite integrity. The full command runs syntax and pytest through the guarded
durable layer and records redacted evidence. Direct and guarded pytest use the
ignored workspace-local `.pytest_tmp` directory instead of a shared machine
temp folder. Pytest collection is explicitly limited to `tests/`, and runtime
trees such as `.pytest_tmp`, `logs`, and `outputs` are excluded so repeated runs
do not collect generated test copies. It makes no provider calls.

When source files have not changed, a repeated full command replays the stored
validation results instead of dispatching pytest again. Use `--rerun` only when
you intentionally want another evidence record for unchanged source.

The normal live workflow remains `python run_loop_v0_2.py`. Phase 2 does not
replace or automatically invoke that paid provider workflow. See
`docs/implementation/BOOTSTRAP_PHASE_2.md` for schema, APIs, state transitions,
tests, and recovery limitations.

## Transactional changes: Bootstrap Phases 3 and 4

The combined transactional package adds:

- `patch_manager.py` - hash-locked file create/replace transactions, bounded
  restart-safe backups, partial-failure restoration, and explicit rollback;
- `git_checkpoint.py` - guarded Git status, branch, add/commit checkpoint, and
  latest-HEAD revert operations with hooks disabled;
- additive `patch_transactions`, `patch_files`, and `git_checkpoints` tables;
- `run_bootstrap_transactional.py` - the offline transactional readiness entry
  point.

After the ledger backup and overlay steps in
`TRANSACTIONAL_CHANGES_INSTALLATION.md`, run:

```powershell
python run_bootstrap_transactional.py --status-only
python run_bootstrap_transactional.py
```

The status command applies checksummed migration `0002_transactional_changes`
and inspects SQLite and Git without running tests. The full command runs the
preserved syntax/pytest validation. Worktree changes are an expected warning
until the overlay is committed; unresolved conflicts fail the check. Neither
command invokes a provider.

Patches cannot delete files, enter protected/runtime paths, or overwrite an
unexpected pre-image. Git checkpoints refuse unrelated and pre-staged changes,
disable repository hooks, and never reset, clean, merge, push, or contact a
remote. See `docs/implementation/TRANSACTIONAL_CHANGES.md` for APIs, states,
durable evidence, recovery rules, and limitations.

## Bounded autonomy: Bootstrap Phase 5

Phase 5 adds:

- `repair_loop.py` — a provider-neutral validate/repair/revalidate loop;
- hard attempt, cost, wall-clock, repeated-failure, repeated-patch, and
  no-progress limits;
- durable proposal, patch, validation, rollback, checkpoint, and terminal-state
  records under migration `0003_bounded_autonomy`;
- `run_bootstrap_bounded.py` — offline status and complete-suite verification.

After following `BOUNDED_AUTONOMY_INSTALLATION.md`, run:

```powershell
python run_bootstrap_bounded.py --status-only
python run_bootstrap_bounded.py
```

The loop accepts an injected structured `RepairAgent`; neither command above
constructs one or calls a provider. Positive-cost repair dispatch also requires
a configured `BudgetGuard`. Successful repairs are complete only after
validation and a scoped Git checkpoint. Failed repairs restore their recorded
pre-images. Ambiguous provider dispatch stops as `recovery_required` instead of
being blindly retried.

See `docs/implementation/BOUNDED_AUTONOMY.md` for the state machine, resume
rules, cost handling, tests, and deliberate limitations.

## Phase 6 Tranche A: authoritative documentation research

Phase 6 begins with `research_provenance.py`, an offline-first research action
that preserves source URLs, titles, primary-source status, applicable
version/date, retrieval timestamps, bounded captured text, SHA-256 evidence,
claim-to-source excerpts, and usage telemetry. Migration
`0004_research_provenance` adds durable research runs, sources, claims, and
citations without changing prior tables.

Automated tests use only deterministic fixtures. Completed runs replay from
SQLite without retrieval, and partially captured offline runs resume without
refetching the stored source. The included HTTP adapter is disabled by default,
requires an exact hostname allowlist and public HTTPS target, refuses redirects
and ambient proxies, and is not invoked by any bootstrap entry point.

See `docs/implementation/AUTHORITATIVE_RESEARCH.md` and
`docs/planning/PHASE_6_IMPLEMENTATION_AND_ACCEPTANCE_CONTRACT.md` for the
governed request, evidence policy, live-network boundary, and acceptance tests.

## Phase 6 Tranche B: acceptance and truth governance

`acceptance_truth.py` adds evidence references, claim truth labels, required
and optional criterion verdicts, hard-constraint findings, and deterministic
acceptance aggregation. It enforces `VERIFIED`, `SUPPORTED`, `INFERRED`,
`DISPUTED`, and `UNKNOWN` evidence invariants and returns only `PASS`, `REPAIR`,
`BLOCK`, `HUMAN_DECISION`, or `DEFER`.

Migration `0005_acceptance_truth` persists idempotent evaluations and their
evidence, claims, criteria, constraints, and outcomes. The fixed calibration
runs known complete, incomplete, uncertain, constraint-violating, and genuinely
disputed cases twice; both rounds must match without a model judge or provider
call.

See `docs/implementation/ACCEPTANCE_TRUTH.md` for aggregation precedence,
durability, calibration, and the boundary between structural evidence
governance and semantic truth.

## Phase 6 Tranche C: final bootstrap acceptance

Run the complete Phase 6 gate with:

```powershell
python run_bootstrap_phase6.py --status-only
python run_bootstrap_phase6.py
```

Status-only mode checks migrations, SQLite/Git readiness, default network
denial, and the ten-gate evidence manifest without pytest, retrieval, providers,
or mutation. Full mode runs the complete guarded regression suite, deterministic
research capture/replay, research-to-acceptance linkage, stable five-case truth
calibration, and exactly ten final bootstrap gates.

Neither mode constructs a provider client or performs a network request. A
passing result completes the execution/research/acceptance bootstrap; Markdown
project-contract parsing and the first bounded backlog orchestration layer are
implemented in Phase 7 below.

See `docs/implementation/PHASE_6_FINAL_BOOTSTRAP.md`,
`PHASE_6_INSTALLATION.md`, and `PHASE_6_CHANGELOG.md`.

## Phase 7: Markdown project orchestration

Phase 7 adds:

- `project_contract.py` — a strict, portable Markdown project-contract parser;
- `task_graph.py` — bounded DAG validation and deterministic ready-task order;
- `orchestration_kernel.py` — durable task claims, resume/replay, authority,
  cost, deadline, no-progress, and ambiguous-dispatch stopping rules;
- `offline_checklist_profile.py` — the explicit `offline-checklist-v1` fixture
  planner/executor;
- migration `0006_project_orchestration` for project runs, backlog tasks,
  dependencies, dispatches, and artifacts;
- `run_phase7.py` — the first end-to-end Markdown-goal entry point.

Run the default synthetic contract with:

```powershell
python run_phase7.py --status-only
python run_phase7.py
```

The default contract is `project/phase7_sample_goal.md`. A first full run creates
`outputs/phase7_supplier_evaluation_checklist.md`, validates it, submits the
evidence to the Phase 6 acceptance engine, and completes only on `PASS`. The
same command immediately verifies completed replay without another task
dispatch. Status-only mode writes no artifact.

This profile is a deterministic checklist generator, not an arbitrary semantic
planner. It makes no provider or network call and permits no positive-cost task.
Later phases can add reviewed planner/executor adapters behind the same durable
and policy-controlled interfaces. See
`docs/implementation/PHASE_7_ORCHESTRATION.md` and
`docs/planning/PHASE_7_IMPLEMENTATION_AND_ACCEPTANCE_CONTRACT.md`.

## Phase 8: governed provider orchestration

Phase 8 adds:

- `provider_gateway.py` — explicit execution modes, route allowlists,
  conservative pre-call quotes, daily/monthly/project budget reservations,
  strict JSON parsing, usage/cost validation, and durable call claims;
- `governed_live_profile.py` — a fixed two-task composer/reviewer DAG that can
  write only one declared Markdown deliverable;
- migration `0007_governed_provider_calls` for prompt/response hashes, validated
  payloads, request identity, usage, cost, latency, and safe failure evidence;
- `run_phase8.py` — status, offline simulation, live preparation, and
  fingerprint-approved live modes;
- separate mock and proposed live-canary Markdown contracts.

Run the complete offline Phase 8 verification path with:

```powershell
python run_phase8.py --status-only
python run_phase8.py --mock-canary
python run_phase8.py --prepare-live
```

None of these commands constructs a provider SDK client or makes a network
call. Mock mode uses an explicit in-memory fixture but exercises the real
gateway, schema, durable orchestration, acceptance, and replay path. Live mode
requires both `--live` and the exact fingerprint printed by `--prepare-live`;
the installer never supplies either.

Phase 8 is intentionally one-shot: a failed semantic review returns `REPAIR`
without silently overwriting or redispatching the artifact. Repair and
multi-iteration quality hardening are Phase 9 feedback targets. See
`docs/implementation/PHASE_8_GOVERNED_PROVIDERS.md` and
`docs/planning/PHASE_8_IMPLEMENTATION_AND_ACCEPTANCE_CONTRACT.md`.

## Phase 9: bounded recovery and operator observability

Phase 9 adds:

- `recovery_live_profile.py` — `governed-live-v2`, retaining the fixed
  composer/reviewer DAG while allowing exactly one reviewer-only retry;
- classified, measured provider failures in `provider_gateway.py`, including
  the Phase 8 `response-truncated` case;
- migration `0008_recovery_observability` for bounded redacted failure excerpts
  and explicit failure kinds;
- controlled pause/resume in `orchestration_kernel.py`, with nonterminal-
  dispatch checks and no composer redispatch;
- `run_diagnostics.py` — a redacted run bundle covering the project, tasks,
  dispatches, calls, artifacts, acceptance, events, cost, and next actions;
- `run_phase9.py` — status, exact offline recovery canary, live preparation,
  and fingerprint-approved live modes with a five-segment status view.

Run the complete zero-cost recovery proof with:

```powershell
python run_phase9.py --status-only
python run_phase9.py --recovery-canary
python run_phase9.py --recovery-canary
```

The first recovery canary composes once, simulates the observed 3,000-token
review truncation, retries only the reviewer, reaches acceptance `PASS`, and
writes a diagnostic bundle. The second invocation replays the completed run
with zero new calls and no artifact rewrite. These commands use only explicit
in-memory fixtures and make no network request.

Live mode remains separately fingerprint-gated. Phase 9 does not yet implement
arbitrary dynamic decomposition, multi-agent collaboration profiles, automatic
goal interviews, multi-judge consensus, live research, or a remote dashboard.
Those requested capabilities are recorded as future milestones in
`docs/planning/PHASE_9_IMPLEMENTATION_AND_ACCEPTANCE_CONTRACT.md`.
