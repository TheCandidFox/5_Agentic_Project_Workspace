# Phase 7 Markdown Project Orchestration

**Status:** implemented and verified offline

**Default profile:** `offline-checklist-v1`

**Provider/network calls:** none

**Cost:** `$0.00`

## User-facing contract

`project_contract.py` parses a bounded UTF-8 Markdown schema. A contract has a
single title and required `Goal`, `Acceptance Criteria`, `Deliverables`, and
`Required Content` sections. Context, constraints, out-of-scope items, and
execution policy are optional.

The parser deliberately rejects broad Markdown features that would make the
contract ambiguous in this first release. Unknown or duplicate headings, HTML,
fenced code, unsafe paths, duplicate keys, malformed policy values, unsupported
profiles, and contracts over 64 KiB fail before durable execution begins.
LF/CRLF input produces the same normalized contract identity.

Each acceptance criterion and constraint has a stable backtick identifier.
Every Phase 7 deliverable must be a project-relative Markdown path below
`outputs/`. The default profile accepts exactly one deliverable.

## Compiled backlog

`task_graph.py` validates application-owned `TaskSpec` records. It enforces:

- unique lowercase task keys and supported task kinds;
- explicit dependencies that refer to existing tasks;
- no self-dependencies or cycles;
- bounded task count, attempts, input size, and finite cost estimates;
- JSON-compatible inputs without sensitive-looking field names;
- deterministic topological and ready-task ordering.

`offline-checklist-v1` compiles two tasks: compose the checklist, then validate
it. The second task cannot become ready until the first is durably complete.

## Durable state and replay

Migration `0006_project_orchestration` adds:

- `project_runs` — contract/plan fingerprints, policy, deadline, progress,
  outcome, cost, and acceptance link;
- `backlog_tasks` — immutable task definition plus attempts and result;
- `backlog_dependencies` — declared graph edges;
- `task_dispatches` — at-most-once attempt claims and terminal result payloads;
- `project_artifacts` — portable path, SHA-256, byte count, and media type.

The run idempotency fingerprint includes contract, graph, policy, run identity,
and execution profile. Reusing a key after any semantic change raises a
conflict. Completed runs replay directly from SQLite.

An interrupted `dispatching` attempt is not retried. The kernel marks the run
`RECOVERY_REQUIRED`, preserving the task identity for manual inspection. A
running project with only completed terminal tasks resumes from the first
incomplete dependency-ready task.

## Policy gates

The Phase 7 entry point permits only `read-only` and `workspace-write` tasks.
It denies local commands, live network, external side effects, and every
positive-cost task before executor dispatch. The submitted contract also has
an authority ceiling and total budget.

Other bounded stops include task count, attempts, scheduler iterations,
consecutive no-progress results, deadline, dependency deadlock, task failure,
changed idempotency semantics, invalid artifact evidence, and invalid acceptance
evidence.

The executor receives a declared-artifact writer. The writer confines paths
through `WorkspaceGuard`, accepts only contract-declared deliverables, writes
atomically, bounds content, refuses unexpected overwrites, and verifies UTF-8.
The kernel independently re-hashes returned artifacts before recording them.

As with the earlier workspace guard, this is an application policy boundary,
not an operating-system sandbox for hostile injected Python. Only reviewed
executor implementations should be instantiated.

## Acceptance completion

The validation task emits typed deterministic evidence for each declared
criterion and supported constraint. The kernel requires exact evidence coverage
and submits it to `AcceptanceEngine`.

A project is complete only when the acceptance aggregate is `PASS`.
`REPAIR`, `BLOCK`, `HUMAN_DECISION`, and `DEFER` remain distinct terminal or
paused states. A model cannot mark its own work accepted because this profile
does not construct a model and acceptance is application-owned.

## Commands

```powershell
python run_phase7.py --status-only
python run_phase7.py
python run_phase7.py --contract project/phase7_sample_goal.md
```

Status-only applies/checks the additive schema, validates the Phase 1–6
foundation, parses the contract, compiles the graph, and validates policy. It
does not dispatch a task or create an output.

Full mode executes the sample and immediately invokes the same run again. The
second invocation must report `replayed=True` and `new_dispatch_calls=0`.

## Current boundary

Phase 7 proves the smallest complete local project lifecycle. It does not yet
perform arbitrary goal decomposition, call a live planner/executor, research a
real topic, repair a project until semantically complete, expose remote status,
or run the five-project generalization benchmark. Those remain later governed
phases.
