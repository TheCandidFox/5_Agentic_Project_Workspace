# Phase 6 Installation and Checkpoint

Apply these files only to the recovered repository baseline on branch
`bootstrap/local-execution`. The expected starting commit is
`e007c9edcf408cfba45e6cebc9978ef7621beab6`, which reconstructs—but is not the
same Git object as—the original lost checkpoint `a83880594c83...`.

## 1. Pre-install gate

From the candidate repository with its existing virtual environment active:

```powershell
git status
git log --oneline --decorate -3
python run_bootstrap_bounded.py --status-only
```

Stop if the worktree is unexpectedly dirty, conflicts exist, the branch is not
`bootstrap/local-execution`, or the bounded-autonomy status does not pass.

Keep the existing pre-Phase-6 ledger backup until Phase 6 is validated and
checkpointed. Do not overwrite `.env`, copy credentials, or replace the frozen
v0.2 backup.

## 2. Apply the Phase 6 source overlay

Copy the reviewed Phase 6 files into the repository while preserving the
relative paths. Do not copy the delivery manifest, checksums, or handoff note
into the source repository unless intentionally retaining them as project
documentation.

The delivery ZIP excludes `.git`, `.env`, `.venv`, ledgers, logs, outputs, and
caches.

## 3. Install/confirm pinned requirements

```powershell
python -m pip install -r requirements.txt
python -m pip check
```

Phase 6 adds no package beyond the already pinned requirements. `httpx` is used
only by the disabled live HTTP transport and is already present for provider
dependencies.

## 4. Status-only migration gate

```powershell
python run_bootstrap_phase6.py --status-only
```

Expected:

- SQLite integrity `ok`;
- migrations `0001` through `0005` present;
- research and acceptance tables ready;
- live HTTP disabled by default;
- final manifest `10/10`;
- no smoke/calibration/tests executed;
- `Phase 6 bootstrap status: PASS`.

Run the status command a second time. Expected `newly_applied=none`.

## 5. Complete offline verification

```powershell
python -m pytest -q
python run_bootstrap_phase6.py
python run_loop_v0_2.py --preflight-only
```

Expected from the delivered source baseline:

- pytest: `128 passed, 1 skipped` when the Windows link-creation privilege is
  unavailable; the platform-specific count may become `129 passed` when that
  existing link test can run;
- all ten Phase 6 gates pass;
- deterministic research replay passes;
- truth calibration returns
  `PASS,REPAIR,PASS,BLOCK,HUMAN_DECISION` twice;
- no provider or network calls;
- legacy preflight passes, with the previously documented missing historical
  artifacts warning still allowed when outputs were intentionally excluded.

## 6. Inspect and checkpoint

```powershell
git status
git diff --check
git diff --stat
git add -- <reviewed Phase 6 paths>
git diff --cached --check
git commit -m "complete offline research and acceptance bootstrap"
git tag v0.3-bootstrap-phase6
git status
git log --oneline --decorate -4
python run_bootstrap_phase6.py --status-only
```

Do not push, merge, or promote the candidate automatically. Review the commit
and tag locally first. A remote push remains a separate user action.

## 7. Rollback

Before commit, remove only the reviewed Phase 6 overlay paths or restore them
from the recovered baseline through a normal reviewed Git operation. After
commit, prefer a normal Git revert commit rather than reset/clean. Do not delete
or rewrite the ledger without first preserving its backup and reviewing the
applied migrations.
