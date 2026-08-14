# Phase 7 Changelog

## Added

- Strict Markdown project-contract parsing and canonical contract identities.
- Deterministic bounded dependency-graph validation.
- Additive migration `0006_project_orchestration`.
- Durable project runs, backlog tasks, graph edges, dispatch attempts, and
  artifact evidence.
- Authority ceiling, zero-cost, deadline, attempt, iteration, no-progress,
  deadlock, and ambiguous-dispatch stopping rules.
- Declared, workspace-confined, atomic Markdown artifact writing.
- `offline-checklist-v1` deterministic planner/executor profile.
- Phase 6 acceptance-engine linkage for final project completion.
- `run_phase7.py` status and end-to-end sample entry point.
- Synthetic Markdown goal at `project/phase7_sample_goal.md`.
- Parser, graph, durability, policy, resume/replay, artifact, and entry-point
  tests.
- Phase 7 planning, implementation, installation, and delivery documentation.

## Preserved

- All Phase 1–6 tests and controls.
- Existing v0.2 live workflow and offline preflight.
- Default denial of live research and repair-provider dispatch.
- `.env`, virtual environment, ledger, outputs, logs, and Git metadata remain
  outside delivery archives.

## Not enabled

- Arbitrary semantic goal planning.
- Provider-backed task execution or paid repair.
- Live HTTP or external side effects.
- Remote Git operations or automatic merge to `main`.
- Real-workbook execution or the later five-project benchmark.
