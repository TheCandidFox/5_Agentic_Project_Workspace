# Transactional Changes Package Installation

This overlay combines Bootstrap Phases 3 and 4: controlled patch transactions,
Git checkpoints, and rollback. It starts from
`v0.3-bootstrap-phase2-hotfix2` and makes no provider calls.

## 1. Confirm the baseline

From `ai_loop_v0_3_candidate`:

```powershell
git status
git log --oneline --decorate -4
```

The worktree must be clean and `v0.3-bootstrap-phase2-hotfix2` must identify the
current baseline before copying the update.

## 2. Back up the working ledger

This migration is additive, but preserve a recoverable pre-install copy:

```powershell
python -c "import sqlite3; s=sqlite3.connect('ledger.db'); d=sqlite3.connect(r'..\ai_loop_v0_3_candidate_ledger_pre_transactional.db'); s.backup(d); d.close(); s.close(); print('Ledger backup complete')"
```

## 3. Copy the overlay

Extract `bootstrap_transactional_changes_update` beside the candidate. From
`Agentic Project Workspace`:

```powershell
robocopy .\bootstrap_transactional_changes_update .\ai_loop_v0_3_candidate /E
if ($LASTEXITCODE -ge 8) {
    throw "Transactional update copy failed with robocopy code $LASTEXITCODE"
}
```

`*EXTRA` lines are informational. `/E` does not delete candidate-only files.

## 4. Validate offline

From inside `ai_loop_v0_3_candidate` with `.venv` active:

```powershell
python -m pip check
python -m pytest -q
python run_bootstrap_transactional.py --status-only
python run_bootstrap_transactional.py
python run_loop_v0_2.py --preflight-only
```

Expected results:

- no broken requirements;
- `97 passed, 1 skipped` when Windows link creation is unavailable;
- migration list includes `0002_transactional_changes`;
- `Transactional status: PASS`;
- `Transactional result: PASS`;
- `Preflight result: PASS`.

The transactional report may warn that the worktree contains changes. That is
expected before the overlay is committed. No command in this validation block
makes a provider call.

## 5. Save the checkpoint

After every validation passes:

```powershell
git add -- README.md ledger.py patch_manager.py git_checkpoint.py `
  run_bootstrap_transactional.py TRANSACTIONAL_CHANGES_CHANGELOG.md `
  TRANSACTIONAL_CHANGES_INSTALLATION.md `
  docs/implementation/BOOTSTRAP_PHASE_2.md `
  docs/implementation/TRANSACTIONAL_CHANGES.md `
  tests/test_phase2_entrypoint.py tests/test_phase2_ledger.py `
  tests/test_patch_manager.py tests/test_git_checkpoint.py `
  tests/test_transactional_entrypoint.py

git commit -m "add transactional patching and Git rollback"
git tag v0.3-bootstrap-transactional

git status
git log --oneline --decorate -5
git show --stat v0.3-bootstrap-transactional
```

The final worktree should be clean.

## Recovery notes

- Do not rerun a record in `recovery_required` state with a new key merely to
  bypass it. Review the filesystem, Git status, command record, and stored
  hashes first.
- Patch rollback refuses changed post-images rather than overwriting them.
- Git revert refuses a dirty worktree and checkpoints that are no longer HEAD.
- The pre-install ledger backup remains outside the candidate and is not
  included in Git or the overlay.
