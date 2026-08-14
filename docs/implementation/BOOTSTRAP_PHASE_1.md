# Bootstrap Phase 1 - Workspace Guard and Command Runner

**Status:** implemented and verified offline  
**Scope:** application-layer controls for authorized local development commands  
**Paid provider calls:** none

## Components

### `workspace_guard.py`

`WorkspaceGuard` establishes one resolved candidate root and authorizes paths
for `READ`, `WRITE`, or `EXECUTE` access.

It rejects:

- paths outside the candidate root;
- lexical `..` traversal, even if normalization would return inside the root;
- existing symlinks or junctions that resolve outside the candidate;
- `.env`, `.env.*` except `.env.example`, `secrets.env`, `.git`, and `.venv`;
- caller-declared immutable paths for write/execute access;
- NTFS alternate-data-stream syntax;
- Windows reserved device names and ambiguous trailing dots/spaces;
- missing read/execute targets and file/directory type mismatches.

Authorized paths include a stable forward-slash path relative to the candidate
for logs and durable state.

### `command_runner.py`

`CommandRunner` accepts a `CommandRequest` with a sequence of separate
arguments. It never accepts shell text and always invokes `subprocess.Popen`
with `shell=False`.

The policy requires:

- a resolved, explicitly allowlisted executable;
- a unique safe alias;
- no shell executable unless separately opted in;
- allowed argument prefixes or an explicit `allow_any_arguments=True` decision;
- an authorized candidate-local working directory;
- a positive timeout no greater than the policy maximum;
- a positive per-stream byte cap no greater than the policy maximum;
- an allowlist for every request-supplied environment variable.

The child environment inherits only a small OS-operability allowlist. API keys
and other ambient credentials are not inherited. Captured output and displayed
arguments are redacted for explicit secrets, common provider-key formats,
credential assignments, bearer tokens, and allowlisted sensitive environment
values.

Outcomes are normalized as:

- `PASS`
- `FAIL`
- `ERROR`
- `TIMEOUT`

The optional `JsonlCommandEventSink` appends redacted, compact records to
`logs/command_events.jsonl`, including outcome, exit code, duration, task/action
identity, relative working directory, bounded previews, and hashes of captured
redacted output.

## Narrow usage example

```python
from pathlib import Path
import sys

from command_runner import (
    CommandPolicy,
    CommandRequest,
    CommandRunner,
    ExecutableRule,
    JsonlCommandEventSink,
)
from workspace_guard import WorkspaceGuard


root = Path(__file__).resolve().parent
guard = WorkspaceGuard(
    root,
    immutable_paths=("docs/reference",),
)
policy = CommandPolicy(
    rules=(
        ExecutableRule(
            alias="python",
            executable=Path(sys.executable),
            allowed_argument_prefixes=(("-m", "pytest"),),
        ),
    ),
    max_timeout_seconds=300,
    max_output_bytes=1_000_000,
)
runner = CommandRunner(
    guard,
    policy,
    event_sink=JsonlCommandEventSink(guard),
)

result = runner.run(
    CommandRequest(
        argv=("python", "-m", "pytest", "-q"),
        cwd=".",
        timeout_seconds=120,
        task_id="bootstrap-validation",
        action_id="pytest",
        idempotency_key="bootstrap-validation:pytest:v1",
    )
)
```

The example permits only the Python `-m pytest ...` argument family. It does not
permit `python -c`, arbitrary scripts, PowerShell, `cmd.exe`, or Git.

## Verification

The full suite verifies:

- preserved v0.2 behavior;
- safe reads and writes inside the candidate;
- traversal and absolute external path denial;
- secret, Git, and immutable-path protection;
- Windows alternate streams, device names, and trailing-character denial;
- passing and failing command capture;
- exact exit codes and separate standard streams;
- timeout termination of the direct child;
- bounded draining of large stdout and stderr;
- ambient API-key removal;
- environment allowlisting and sensitive-value redaction;
- executable and argument-prefix denial;
- shell opt-in enforcement;
- working-directory confinement;
- durable redacted JSONL events.

Current offline result: **52 passed, 1 skipped**. The skipped case attempts to
create a Windows symlink/junction escape, but the verification environment did
not possess the Windows link-creation privilege. The guard follows resolved
links before containment checks; this case should be rerun on a Developer Mode
or otherwise link-enabled machine.

## Deliberate limitations

This phase does **not** claim operating-system sandboxing.

1. An allowed executable runs with the current Windows user's OS permissions.
   Workspace authorization validates orchestrator requests and working
   directories; it cannot prevent an allowed program from independently opening
   an external path.
2. Timeout handling kills the direct child. A deliberately detached descendant
   may survive; process-tree/job-object containment remains future work.
3. Filesystem authorization and use are separate operations, so a hostile local
   process could attempt a link-swap race. Untrusted concurrent processes are
   outside this phase's threat model.
4. Command events use workspace-local JSONL, not the SQLite ledger. Ledger schema
   migration and idempotent command dispatch belong to the next tranche.
5. Patch application, rollback, normalized test orchestration, and autonomous
   repair are not implemented yet.

These limitations require narrow allowlists and trusted deterministic commands
until later layers add stronger isolation and durable dispatch governance.

## Next tranche

Implement `test_runner.py`, then extend `ledger.py` with an idempotent schema
migration for command and validation records. Integrate the command event sink
with that durable ledger before adding the patch manager or model-driven repair.
