# Bootstrap Phase 2 Changelog

**Phase 1 package SHA-256:**
`181DE1640DCD7E8C5D56DABFCB4889B4F46696CF337825B690725DBCA8B0B0EE`

**User Phase 1 checkpoint:** `f34d22d` / `v0.3-bootstrap-phase1`

## Added

- `test_runner.py`
- `durable_execution.py`
- `run_bootstrap_phase2.py`
- `tests/test_test_runner.py`
- `tests/test_durable_execution.py`
- `tests/test_phase2_ledger.py`
- `tests/test_phase2_entrypoint.py`
- `docs/implementation/BOOTSTRAP_PHASE_2.md`
- `PHASE_2_INSTALLATION.md`
- this changelog

## Updated

- `ledger.py`
  - added checksummed, additive schema migrations;
  - added atomic command claims and terminal result storage;
  - added durable validation storage and command linkage;
  - added compact events for claims, outcomes, errors, and validations.
- `command_runner.py`
  - added portable redacted request descriptions;
  - added runtime command identity to results/events;
  - removed absolute executable paths from durable JSONL events;
  - requires a concrete argument sequence for deterministic replay.
- `tests/test_command_runner.py` with the concrete-sequence regression.
- `README.md` with Phase 2 status and the offline entry point.

## Hotfix 1 - guarded pytest temporary directory

- Sets guarded pytest `--basetemp` to the project-local, ignored
  `logs/pytest_tmp` directory.
- Avoids Windows permission collisions in a shared `pytest-of-unknown` temp
  directory when the command runner intentionally scrubs user identity variables.
- Adds bounded redacted failure-tail output to the Phase 2 console report.
- Adds regression coverage for the default project-local pytest temp path.

## Hotfix 2 - repeatable pytest collection

- Adds `pytest.ini` with the supported `tests` collection boundary.
- Gives direct and guarded pytest the ignored project-local `.pytest_tmp`
  directory, avoiding inaccessible shared Windows temp roots.
- Excludes runtime/generated `.pytest_tmp`, `logs`, and `outputs` trees from
  recursive pytest and source-snapshot discovery.
- Prevents stale `logs/pytest_tmp` copies from causing duplicate-module import
  mismatches during a later direct `python -m pytest -q` run.
- Adds regressions that verify runtime Python files do not affect the source
  snapshot and conflicting generated test modules are not collected.

## SQLite migration

- Adds `schema_migrations`, `commands`, and `validation_runs`.
- Does not delete, rename, or rebuild any v0.2 table.
- Runs automatically the first time the Phase 2 `Ledger` opens a database.
- The overlay does **not** contain or replace `ledger.db`.
- A disposable copy of the uploaded ledger migrated with integrity `ok` while
  preserving three tasks, eight steps, and eight telemetry rows.

## Removed

- None.

## Excluded from the overlay

- `.env`, `.git`, `.venv`, `ledger.db`, SQLite sidecars, `outputs`, and `logs`
- all unchanged source, research, reference documents, and requirements

## Offline verification

- preserved v0.2 and Phase 1 suite: PASS
- full suite: **83 passed, 1 skipped**
- syntax parsing: PASS (23 Python files)
- historical-ledger copy migration: PASS
- forbidden-content, machine-path, and credential-pattern scans: PASS
- paid provider calls: **0**

The skipped case is the existing Windows symlink/junction escape test when the
verification account cannot create a link. See the implementation document for
the security boundary, stranded-claim behavior, and remaining containment and
repair limitations.
