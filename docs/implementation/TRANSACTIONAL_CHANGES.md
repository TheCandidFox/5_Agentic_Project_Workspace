# Transactional Changes — Bootstrap Phases 3 and 4

## Purpose

This package supplies the reversible local mutation boundary needed before a
bounded repair loop can safely edit candidate code. It combines controlled file
transactions with scoped Git checkpoints while preserving the v0.2 workflow
and Phase 1/2 execution policies.

It is entirely offline. It does not invoke a model, provider, remote Git host,
or cloud service.

## Patch API

`PatchManager.apply(PatchRequest(...))` accepts one or more `FilePatch`
records. An existing target requires its exact SHA-256 pre-image. A missing
target is treated as a create operation only when no pre-image is supplied.

Each request includes:

- patch and idempotency identities;
- actor, reason, and optional task identity;
- portable project-relative paths;
- UTF-8 replacement content;
- an expected SHA-256 for every existing target.

Default limits are 1 MB per file and 4 MB per transaction. The manager rejects
protected, secret, runtime, ledger, output, log, cache, and out-of-workspace
paths. It requires existing parent directories and does not accept deletion.

Writes use a same-directory temporary file followed by `os.replace`. If a
later file fails, already-written files are restored in reverse order. The
original bytes and mode are recorded before dispatch, allowing rollback after
process restart.

### Patch states

```text
prepared -> applied -> rolling_back -> rolled_back
    |                         |
    +-> failed_rolled_back    +-> recovery_required
    +-> recovery_required
```

`recovery_required` is deliberately terminal for automatic behavior. A retry
with a new key is not a repair procedure.

Explicit rollback first verifies every current file still matches its recorded
post-image. It will not overwrite subsequent human or agent changes. A file
created by a patch is removed only during rollback of that same patch.

## Git checkpoint API

`GitCheckpointManager` routes Git through the Phase 1 `CommandRunner`; no shell
is involved. Side-effecting commands use Phase 2 durable command claims.

Supported operations are:

- detect or initialize the workspace repository;
- inspect branch, HEAD, and porcelain status;
- create a validated branch from a clean worktree;
- produce bounded diff evidence;
- add and commit an exact reviewed path set;
- replay an already completed checkpoint;
- revert the latest clean HEAD checkpoint.

Checkpoint creation refuses:

- changes outside the requested set;
- paths already staged before the request;
- unresolved conflicts;
- renames or copies requiring separate review;
- protected or escaping paths;
- a repository root different from the granted workspace.

The commit identity is a deterministic local service identity. Git environment
configuration redirects hooks to an empty ignored directory, preventing a
repository hook from escaping the command policy during autonomous commits.

Automatic revert creates a normal Git revert commit. It never invokes reset,
clean, checkout-overwrite, merge, push, or a remote operation. To avoid
out-of-order history changes, only the recorded checkpoint at current `HEAD`
may be reverted automatically, and the worktree must be clean.

### Checkpoint states

```text
preparing -> committed -> reverting -> reverted
     |                         |
     +-> failed               +-> failed
     +-> recovery_required    +-> recovery_required
```

When a checkpoint linked to a patch is successfully reverted, the patch record
is also marked rolled back.

## Durable schema

Checksummed migration `0002_transactional_changes` adds:

- `patch_transactions` — identities, request hash, actor/reason, state, and
  timestamps;
- `patch_files` — portable path, operation, pre/post hashes, bounded original
  bytes, file mode, and sizes;
- `git_checkpoints` — patch linkage, base/commit/revert hashes, path list, diff
  evidence hash, state, and timestamps.

Compact state-transition events contain identities, portable paths, hashes,
and outcomes. New patch contents, Git configuration values, credentials, and
absolute machine paths are not written to event or checkpoint records.

## Offline acceptance entry point

```powershell
python run_bootstrap_transactional.py --status-only
python run_bootstrap_transactional.py
```

Status-only mode applies migrations and checks SQLite, table availability, and
Git state. Full mode also runs the Phase 2 syntax and pytest suite. Dirty paths
are reported as a warning during overlay installation; unresolved conflicts
are a failure.

## Deliberate limitations

1. Filesystem writes and SQLite commits cannot form one operating-system ACID
   transaction. Explicit intermediate and recovery states make that boundary
   observable instead of silently retrying.
2. Patches replace complete UTF-8 files. Unified-diff parsing, binary patches,
   deletion, and automatic parent-directory creation are deferred.
3. Git checkpointing does not merge, push, contact remotes, or promote to the
   frozen baseline.
4. Only current-HEAD revert is automatic. Older or conflicting history needs
   reviewed recovery.
5. Command policy and path guards remain application controls, not hostile-code
   operating-system containment.
6. Autonomous diagnosis still depends on the quality and authority of the
   injected repair agent and validation contract.

## Bounded repair integration

Bootstrap Phase 5 now composes these primitives in `repair_loop.py`. It enforces
attempt, cost, duration, repeated-failure, repeated-patch, and no-progress
limits; validates after each patch; checkpoints success; and rolls back failed
candidates without bypassing unresolved durable states. See
`BOUNDED_AUTONOMY.md`.
