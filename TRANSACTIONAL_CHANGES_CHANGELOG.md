# Transactional Changes Package Changelog

**Starting checkpoint:** `37523ac` / `v0.3-bootstrap-phase2-hotfix2`

## Added

- `patch_manager.py`
  - project-confined UTF-8 create/replace operations;
  - required SHA-256 pre-images for existing files;
  - per-file and transaction byte limits;
  - atomic same-directory writes;
  - automatic restoration after partial failure;
  - restart-safe explicit rollback from SQLite backups;
  - idempotent terminal-result replay and conflict detection.
- `git_checkpoint.py`
  - guarded repository detection and initialization;
  - clean branch creation;
  - portable status and bounded diff evidence;
  - scoped add/commit checkpoints;
  - unrelated, conflicted, renamed, and pre-staged change refusal;
  - latest-checkpoint-only revert;
  - disabled repository hooks and deterministic local checkpoint identity;
  - durable command and checkpoint linkage.
- `run_bootstrap_transactional.py`
  - offline migration, integrity, Git-state, syntax, and pytest verification.
- `tests/test_patch_manager.py`
- `tests/test_git_checkpoint.py`
- `tests/test_transactional_entrypoint.py`
- `docs/implementation/TRANSACTIONAL_CHANGES.md`
- `TRANSACTIONAL_CHANGES_INSTALLATION.md`
- this changelog.

## Updated

- `ledger.py`
  - adds checksummed migration `0002_transactional_changes`;
  - adds `patch_transactions`, `patch_files`, and `git_checkpoints`;
  - records compact patch/checkpoint state-transition events;
  - preserves rollback pre-images as bounded SQLite BLOBs without storing new
    patch contents in event or checkpoint records.
- Phase 2 migration and entry-point regressions to recognize migration `0002`.
- `README.md` and the Phase 2 implementation handoff.

## Safety decisions

- Patch requests cannot delete files or create missing parent directories.
- Rollback may delete only a file created by that exact recorded patch.
- Rollback refuses to overwrite a file changed after patch application.
- Filesystem and SQLite changes expose explicit `recovery_required` states when
  a crash prevents a safe terminal transition.
- Git checkpoint commits run without repository hooks.
- Git checkpointing refuses unrelated or pre-staged files.
- Automatic Git revert is limited to the checkpoint currently at `HEAD`.
- No reset, clean, merge, push, remote, or cloud operation is implemented.

## Schema migration

- `0002_transactional_changes` is additive and checksummed.
- No v0.2 or Phase 2 table is deleted, renamed, or rebuilt.
- The overlay contains no `ledger.db` and never replaces the working ledger.

## Offline verification target

- dependency health: PASS;
- preserved and new regression suite: **97 passed, 1 skipped** on the Windows
  verification host;
- patch partial-failure restoration: PASS;
- restart-safe patch rollback: PASS;
- Git hook suppression and checkpoint/revert: PASS;
- historical-ledger copy migration and SQLite integrity: PASS;
- forbidden-content, credential-pattern, and machine-path scans: PASS;
- provider calls and API cost: **0**.

The one expected skip is the existing Windows link-escape test when the
verification identity cannot create a symlink or junction.
