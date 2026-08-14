# Bounded Autonomy Package Installation

This overlay adds Bootstrap Phase 5 to the clean
`v0.3-bootstrap-transactional` checkpoint. All installation verification is
offline and makes no provider calls.

## 1. Confirm the baseline

From `ai_loop_v0_3_candidate`:

```powershell
git status
git log --oneline --decorate -5
```

Expected baseline:

- branch `bootstrap/local-execution`;
- tag `v0.3-bootstrap-transactional` at commit `5c4d6ee`;
- `nothing to commit, working tree clean`.

Stop if the worktree is not clean. Do not discard unrelated work.

## 2. Back up the ledger

```powershell
python -c "import sqlite3; s=sqlite3.connect('ledger.db'); d=sqlite3.connect(r'..\ai_loop_v0_3_candidate_ledger_pre_bounded_autonomy.db'); s.backup(d); d.close(); s.close(); print('Ledger backup complete')"
```

The backup remains outside the candidate and outside Git.

## 3. Copy the overlay

Extract `bootstrap_bounded_autonomy_update` beside the candidate. From
`Agentic Project Workspace`:

```powershell
robocopy .\bootstrap_bounded_autonomy_update .\ai_loop_v0_3_candidate /E
if ($LASTEXITCODE -ge 8) {
    throw "Bounded autonomy update copy failed with robocopy code $LASTEXITCODE"
}
```

`*EXTRA` lines are informational. `/E` overlays included files and does not
delete candidate-only files.

## 4. Validate offline

From `ai_loop_v0_3_candidate` with the shared `.venv` active:

```powershell
python -m pip check
python -m pytest -q
python run_bootstrap_bounded.py --status-only
python run_bootstrap_bounded.py
python run_loop_v0_2.py --preflight-only
```

Expected results:

- no broken requirements;
- `112 passed, 1 skipped` when Windows link creation is unavailable;
- migration list includes `0003_bounded_autonomy`;
- `Bounded autonomy status: PASS`;
- `Bounded autonomy result: PASS`;
- `Preflight result: PASS`.

The status report may show the overlay files as changed before commit. That is
expected. Any Git conflict is a failure. The historical eight-missing-artifact
preflight warning remains expected because the portable review excluded old
`outputs/` files.

No command above creates a repair agent or makes a paid provider call.

## 5. Save the Git checkpoint

```powershell
git add -- README.md budget_guard.py ledger.py patch_manager.py repair_loop.py `
  run_bootstrap_bounded.py BOUNDED_AUTONOMY_CHANGELOG.md `
  BOUNDED_AUTONOMY_INSTALLATION.md `
  docs/implementation/TRANSACTIONAL_CHANGES.md `
  docs/implementation/BOUNDED_AUTONOMY.md `
  tests/test_phase2_entrypoint.py tests/test_phase2_ledger.py `
  tests/test_transactional_entrypoint.py tests/test_budget_guard.py `
  tests/test_repair_loop.py tests/test_bounded_entrypoint.py

git commit -m "add bounded autonomous repair loop"
git tag v0.3-bootstrap-bounded-autonomy

git status
git log --oneline --decorate -6
git show --stat v0.3-bootstrap-bounded-autonomy
python run_bootstrap_bounded.py --status-only
```

After the commit, expect a clean worktree and `changed_paths=0`, `conflicts=0`.

## Recovery notes

- Keep the pre-install ledger backup until the checkpoint is validated.
- Do not bypass `recovery_required` with a new idempotency key.
- A run left at `proposing` may represent a paid-but-unrecorded dispatch and
  intentionally requires review rather than automatic resend.
- A failed validation is rolled back before another attempt.
- A passing repair is not complete until its scoped Git checkpoint commits.
- The overlay does not enable a live repair provider. Paid integration remains
  a separate, explicitly budgeted step.
