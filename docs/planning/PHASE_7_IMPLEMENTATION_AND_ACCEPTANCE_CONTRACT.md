# AI Project OS v0.3 — Phase 7 Implementation and Acceptance Contract

**Status:** approved implementation boundary

**User repository baseline:**
`3aa5bee1db1d30d6dc2e04e006b04653316b9803`

**Baseline tag:** `v0.3-bootstrap-phase6`

**Target branch:** `bootstrap/local-execution`

**Execution posture:** deterministic and offline; no provider or live-network
calls

## 1. Purpose

Phase 7 adds the first top-level project runner above the Phase 1–6 bootstrap.
It accepts a bounded Markdown project contract, compiles a durable dependency
graph, enforces authority/budget/stopping rules, executes an injected offline
profile, and evaluates the resulting evidence through the Phase 6 acceptance
engine.

The first sample is intentionally small: a deterministic Markdown checklist
generator. It proves that a submitted goal can move from contract parsing to a
durable backlog, artifact creation, validation, acceptance, completion, and
replay without a model or network call. It does not claim arbitrary semantic
planning or paid-agent autonomy.

## 2. Preserved Boundaries

All Phase 1–6 controls remain active, including workspace confinement,
redaction, durable claims, additive migrations, transactional code changes,
bounded repair, research provenance, and truth-governed acceptance.

Phase 7 must not:

- construct or call a model-provider client;
- make a live HTTP request;
- enable a paid or live execution profile;
- read, modify, copy, or log `.env` or credential values;
- run shell text or an unrestricted executable;
- modify files outside the project root;
- push, fetch, merge, reset, clean, or contact a Git remote;
- silently redispatch a task whose prior dispatch has no durable result;
- claim that a fixture profile can solve an arbitrary goal;
- promote the real workbook or the five later generalization benchmarks.

## 3. Markdown Project Contract

The parser accepts UTF-8 Markdown with one title and these level-two sections:

- required: `Goal`, `Acceptance Criteria`, `Deliverables`, and
  `Required Content`;
- optional: `Context`, `Constraints`, `Out of Scope`, and
  `Execution Policy`.

Acceptance criteria and constraints use stable backtick identifiers followed
by descriptions. Deliverables use project-relative paths under `outputs/`.
Unknown/duplicate sections, duplicate identifiers, unsafe paths, unsupported
profiles, malformed policy values, HTML blocks, NUL characters, or oversized
contracts fail before a run is claimed.

Recommended Phase 7 policy defaults are:

- profile: `offline-checklist-v1`;
- authority ceiling: `workspace-write`;
- budget: `$0`;
- maximum tasks: 8;
- maximum scheduler iterations: 16;
- maximum no-progress results: 2;
- maximum runtime: 120 seconds.

The normalized contract receives a stable SHA-256 identity. Reusing a run
idempotency key for changed contract or plan semantics fails closed.

## 4. Durable Backlog and Task Graph

Migration `0006_project_orchestration` adds:

- `project_runs`;
- `backlog_tasks`;
- `backlog_dependencies`;
- `task_dispatches`;
- `project_artifacts`.

Plans contain unique task keys, declared dependencies, authority requirements,
estimated costs, attempt limits, and typed input data. The graph validator
rejects missing dependencies, self-dependencies, cycles, duplicate keys,
unsupported task kinds, and limits above the contract policy.

Ready tasks are selected deterministically by plan ordinal. Completed tasks are
not dispatched again after restart. A durable `dispatching` record without a
terminal result is ambiguous and causes `RECOVERY_REQUIRED`; the kernel does
not guess whether an external side effect occurred.

## 5. Authority, Budget, and Stopping Rules

Phase 7 defines ordered authority classes:

1. `read-only`;
2. `workspace-write`;
3. `local-command`;
4. `live-network`;
5. `external-side-effect`.

The default profile uses only the first two. A task above the contract ceiling
is blocked before dispatch. Live-network/external authority and positive-cost
execution are unconditionally disabled by the Phase 7 entry point.

The scheduler stops on completion, explicit task failure, authority denial,
budget denial, dependency deadlock, no progress, task/iteration limit,
wall-clock deadline, changed idempotency semantics, or ambiguous dispatch.
Every stop has a durable state and reason.

## 6. Offline Checklist Profile

`offline-checklist-v1` is an explicit deterministic fixture profile, not a
general-purpose agent. It compiles two tasks:

1. create the declared Markdown checklist from `Required Content`;
2. validate the declared artifact and acceptance checks.

The profile supports these acceptance checks:

- `deliverable-exists`;
- `required-sections`;
- `concise-length`.

It records artifact path, byte count, SHA-256, media type, and deterministic
evidence. The final evidence is submitted to the Phase 6 acceptance engine.
Completion requires an aggregate `PASS`; `REPAIR`, `BLOCK`, `DEFER`, or
`HUMAN_DECISION` remains non-complete.

## 7. Entry Point and First Sample

The entry point is:

```powershell
python run_phase7.py --status-only
python run_phase7.py
```

The default contract is `project/phase7_sample_goal.md`. Status-only mode
parses and validates the contract, applies/checks migration `0006`, validates
the compiled DAG, and reports policy readiness without dispatching a task or
writing a deliverable.

Full mode executes the deterministic sample. A second identical run must replay
the completed project without another executor dispatch or artifact rewrite.

## 8. Acceptance Gate

Phase 7 is complete only when:

- all Phase 1–6 regressions remain passing, allowing documented platform skips;
- migration `0006` applies once and retains checksum protection;
- valid Markdown parses identically across LF and CRLF input;
- malformed, ambiguous, duplicate, or unsafe contracts fail closed;
- valid task graphs produce a stable topological schedule;
- missing dependencies and cycles are rejected;
- authority and positive-cost denials occur before executor dispatch;
- the sample creates only its declared `outputs/` artifact;
- deterministic acceptance returns `PASS` with linked evidence;
- completed replay makes zero new dispatches and does not rewrite the artifact;
- ambiguous dispatch produces `RECOVERY_REQUIRED` without redispatch;
- status-only performs no task dispatch or artifact write;
- full execution performs no provider or network call;
- SQLite integrity remains `ok`;
- the source package excludes `.git`, `.env`, `.venv`, ledgers, outputs, logs,
  and caches.

## 9. Delivery

Delivery uses the established two-file workflow:

1. a Phase 7 implementation ZIP containing full source, an update patch,
   manifest, handoff, and checksums;
2. a standalone Git Bash installer placed beside the ZIP and repository in
   `0_GitHub_Projects`.

The installer verifies the exact Phase 6 baseline, preserves `.env`, creates a
pre-install tag, applies the patch, runs offline validation and the sample
replay, creates a local Phase 7 commit/tag, and never pushes automatically.
