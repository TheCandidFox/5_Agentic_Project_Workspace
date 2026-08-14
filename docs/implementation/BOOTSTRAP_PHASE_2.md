# Bootstrap Phase 2 - Durable Validation and Command Records

**Status:** implemented and verified offline  
**Scope:** normalized deterministic validation plus durable, idempotent local
command dispatch  
**Paid provider calls:** none

## Entry point

`run_bootstrap_phase2.py` is the Phase 2 offline entry point:

```powershell
python run_bootstrap_phase2.py --status-only
python run_bootstrap_phase2.py
```

`--status-only` opens the ledger, applies pending checksummed additive
migrations, and reports SQLite integrity without running tests. The full command
then runs Python syntax validation and pytest through the guarded command layer.
Pytest receives `--basetemp .pytest_tmp`, avoiding shared-machine temporary
directories while keeping generated test state in an ignored runtime tree.
Repository-level `pytest.ini` applies the same temp location to direct runs,
limits supported collection to `tests/`, and excludes runtime/generated trees,
so later direct pytest runs do not traverse temporary test copies left under
the previous `logs/pytest_tmp` location.

A snapshot hash covers authorized Python source and test files. That hash is
part of each validation idempotency key. Repeating the command against unchanged
source replays the prior durable results. `--rerun` creates a new evidence run
when a deliberate repeat is required.

The entry point does not import provider adapters, construct provider clients,
or invoke `run_loop_v0_2.py`.

## Normalized validation

`test_runner.py` provides these initial check types:

- `PythonSyntaxCheck`: compiles authorized Python source without executing it;
- `PytestCheck`: invokes only the allowlisted `python -m pytest ...` family;
- `CommandCheck`: normalizes an already structured, policy-authorized command;
- `FileCheck`: checks presence, type, minimum size, and optional SHA-256;
- `JsonCheck`: checks JSON parsing, root shape, required keys, and expected
  top-level values.

Every check returns one of:

- `PASS`
- `FAIL`
- `ERROR`
- `TIMEOUT`
- `NOT_APPLICABLE`

Results include stable check identity, portable paths, timing, bounded redacted
command previews and hashes, optional command linkage, and a specification hash.
Suites aggregate outcomes deterministically and can stop after the first result
that is neither `PASS` nor `NOT_APPLICABLE`.

When a command-backed validation fails, the entry point prints the last bounded,
redacted portion of captured output so the immediate cause is visible without a
manual SQLite query.

Protected and runtime trees such as `.env`, `.git`, `.venv`, `__pycache__`,
`.pytest_cache`, `.pytest_tmp`, `outputs`, and `logs` are not traversed during source discovery.
Existing links and junctions are authorized through `WorkspaceGuard` before
they can enter the source set.

## Additive ledger migration

The migration identifier is:

```text
0001_bootstrap_commands_validations
```

`schema_migrations` records the identifier, SHA-256 of the migration SQL, and
application time. Startup rejects a recorded migration whose checksum differs
from the code. Migration claims use an immediate SQLite transaction so
concurrent processes cannot both apply the same migration.

No v0.2 table or column is deleted or renamed. The migration adds:

### `commands`

Durable fields include:

- command, task, action, and idempotency identities;
- a private request fingerprint;
- redacted arguments, executable alias, and project-relative working directory;
- dispatch status and normalized outcome;
- exact exit code, bounded redacted stdout/stderr, hashes, and truncation flags;
- start/completion timestamps, duration, and redacted error.

Absolute executable paths are runtime-only and are not written to the command
table or JSONL event records.

### `validation_runs`

Durable fields include:

- validation, task, action, check, and idempotency identities;
- validation kind, specification hash, normalized outcome, and summary;
- structured portable details and timing;
- optional foreign-key linkage to the command that produced the evidence.

Compact `command_claimed`, `command_completed`, `command_dispatch_error`, and
`validation_recorded` entries are also appended to the existing `events` table.
The Phase 1 JSONL command sink remains available and now uses executable aliases
instead of absolute paths.

## Idempotent dispatch behavior

`IdempotentCommandRunner` validates a request before claiming its key. The
claim and lookup occur under `BEGIN IMMEDIATE`.

- New key: insert `dispatching`, execute once, then persist the result.
- Same key and same request after completion: replay the stored result.
- Same key with a different request fingerprint: raise a conflict.
- Existing `dispatching` claim: block a possible duplicate.
- Existing `dispatch_error`: block implicit retry and require review/new intent.

Fingerprint calculation uses the real arguments and explicitly supplied
environment values, but only the SHA-256 fingerprint is stored. The durable
request description contains redacted arguments and environment variable names,
not environment values.

This design favors at-most-once safety. A crash after a command starts but
before its result commits leaves a `dispatching` record and will not silently
repeat the command.

## Offline verification

The final suite covers:

- all preserved v0.2 and Phase 1 behavior;
- migration-once and checksum-tampering detection;
- migration of a disposable copy of the uploaded historical ledger;
- concurrent command claims with exactly one winner;
- execute-once command replay and changed-request conflicts;
- interrupted and failed dispatch states;
- secret non-persistence and portable SQLite/JSONL events;
- syntax, file, JSON, command, timeout, and pytest normalization;
- durable validation replay and command-to-validation linkage;
- the Phase 2 entry point and source-snapshot replay.

Current offline result: **83 passed, 1 skipped**. The one skip is the existing
Windows link-creation test when the verification account lacks symlink/junction
creation privilege. A disposable migration of the uploaded ledger preserved
three tasks, eight steps, and eight telemetry rows with SQLite integrity `ok`.

## Deliberate limitations

1. This remains an application policy layer, not an operating-system sandbox.
   An allowed executable has the current Windows user's permissions.
2. A stranded `dispatching` command is intentionally not retried automatically.
   A reviewed recovery/abandonment transition belongs with the repair layer.
3. Captured output is bounded and redacted, but redaction is pattern- and
   policy-based. Commands must still be narrowly allowlisted and must not print
   arbitrary secret material.
4. The JSON check is a small deterministic assertion interface, not a complete
   JSON Schema implementation.
5. Output capture still terminates the direct child on timeout; Windows Job
   Object/process-tree containment is not implemented.
6. Patch application, rollback, Git checkpoints, and autonomous repair are not
   part of Phase 2 itself. The first three are implemented by the subsequent
   transactional package; autonomous repair remains deferred.

## Next phase

The transactional package now implements `patch_manager.py`, Git checkpoints,
and rollback evidence under migration `0002_transactional_changes`. See
`TRANSACTIONAL_CHANGES.md`. The next package is the bounded repair loop, which
must consume these records without weakening command policy or implicitly
retrying unresolved command, patch, or checkpoint claims.
