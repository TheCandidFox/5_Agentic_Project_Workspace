# Phase 7 Installation and Checkpoint

Apply Phase 7 only to the confirmed Phase 6 repository checkpoint:

- branch: `bootstrap/local-execution`;
- commit: `3aa5bee1db1d30d6dc2e04e006b04653316b9803`;
- tag: `v0.3-bootstrap-phase6`;
- clean worktree synchronized with `origin/bootstrap/local-execution`.

The supplied Git Bash installer automates these gates. The manual procedure is
retained here for inspection and recovery.

## 1. Pre-install

```powershell
git status
git branch --show-current
git rev-parse HEAD
git tag --points-at HEAD
python run_bootstrap_phase6.py --status-only
```

Stop on a dirty worktree, unexpected branch/commit, conflicts, or failed Phase
6 status. Preserve the existing ledger backup and `.env`.

## 2. Apply one payload

Use either the delivered update patch or the full source snapshot, not both.
The preferred installer verifies and applies the patch with strict whitespace
checks. It does not copy `.env`, `.venv`, ledger files, outputs, logs, caches,
or Git metadata.

## 3. Migration and status

```powershell
python -m pip check
python run_phase7.py --status-only
python run_phase7.py --status-only
```

Expected migration `0006_project_orchestration` applies on the first status run
and reports `newly_applied=none` on the second. Status-only must not create the
sample deliverable or task dispatch.

## 4. Complete offline validation

```powershell
python -m pytest -q
python run_bootstrap_phase6.py --status-only
python run_phase7.py
python run_phase7.py
python run_loop_v0_2.py --preflight-only
```

Expected:

- the complete suite passes with only documented platform skips;
- all ten Phase 6 gates remain represented and ready;
- the Phase 7 sample reaches `PASS` and creates its declared checklist;
- the immediate replay and later command make zero new task dispatches;
- provider/network calls and cost remain zero;
- legacy offline preflight remains passing.

## 5. Local checkpoint

```powershell
git status
git diff --check
git add -- <reviewed Phase 7 paths>
git diff --cached --check
git commit -m "add durable Markdown project orchestration"
git tag -a v0.3-phase7-markdown-orchestration -m "Phase 7 durable Markdown project orchestration"
git status
git log -3 --oneline --decorate
```

Review locally before pushing. Do not merge into `main` automatically.

## 6. `.env` and dependencies

Phase 7 adds no dependency and requires no `.env` change. The installer hashes
`.env` before and after installation and stops if it changes.

## 7. Recovery

The installer creates an annotated `phase7-preinstall-...` tag before applying
the patch. On a validation failure it leaves the repository in place for
inspection and does not perform an automatic reset. Do not delete or rewrite
the ledger merely to undo additive migration `0006`; preserve it and review the
recorded state first.
