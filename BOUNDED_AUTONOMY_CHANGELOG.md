# Bounded Autonomy Package Changelog

Baseline: `v0.3-bootstrap-transactional` (`5c4d6ee`)

## Added

- `repair_loop.py`
  - provider-neutral structured repair-agent contract;
  - validate/propose/patch/revalidate/checkpoint-or-rollback orchestration;
  - hard attempt, cost, duration, identical-failure, identical-patch, and
    no-progress bounds;
  - durable restart/resume and conservative ambiguous-dispatch handling.
- `run_bootstrap_bounded.py`
  - status-only and full offline verification;
  - explicit guarantee that the entry point configures no provider calls.
- migration `0003_bounded_autonomy`
  - `repair_runs` and `repair_attempts` durable records.
- `docs/implementation/BOUNDED_AUTONOMY.md`
  - state machine, recovery rules, cost semantics, tests, and limitations.
- `tests/test_repair_loop.py`
  - successful and bounded-failure integration tests using temporary Git
    repositories and deterministic offline agents.
- `tests/test_bounded_entrypoint.py`
  - entry-point, migration, table, and no-provider regression coverage.
- `tests/test_budget_guard.py`
  - deterministic reservation replay without double reservation.

## Changed

- `budget_guard.py`
  - optional deterministic reservation keys make pre-dispatch reservation
    replay idempotent.
- `ledger.py`
  - additive repair migration and guarded repair state transitions;
  - idempotent budget-reservation lookup/replay;
  - repair proposal costs recorded in telemetry.
- `patch_manager.py`
  - public read-only request validation/fingerprint method used before a
    proposal body is durably accepted.
- prior migration/entry-point tests
  - fresh-ledger expectations now include migration `0003_bounded_autonomy`.
- `README.md` and transactional implementation notes
  - current bootstrap status and next boundary updated.

## Preserved

- the frozen v0.2 backup and its known-good four-stage provider workflow;
- all prior command, validation, patch, Git, portability, and v0.2 behavior;
- existing SQLite rows and tables through additive migration only;
- project-relative paths, secret exclusions, output/log exclusions, and
  provider-free preflight;
- human control over promotion, merging, remote operations, and paid runs.

## Not included

- `.env`, credentials, Git metadata, virtual environments, ledgers, outputs,
  logs, caches, or machine-specific executable paths;
- a live provider repair adapter;
- Git merge/push/remote operations;
- cloud deployment, PWA, GraphRAG, or production automation.
