# Phase 8 Installation and Checkpoint

Apply Phase 8 only to the confirmed Phase 7 repository checkpoint:

- branch: `bootstrap/local-execution`;
- commit: `d14b4bca67d39247e444b8539f3c0da9bf935ee6`;
- tag: `v0.3-phase7-markdown-orchestration`;
- clean worktree synchronized with `origin/bootstrap/local-execution`.

The supplied Git Bash installer automates these gates. The manual procedure is
retained for review and recovery.

## 1. Pre-install

```powershell
git status
git branch --show-current
git rev-parse HEAD
git tag --points-at HEAD
python run_phase7.py --status-only
```

Stop on a dirty worktree, unexpected branch/commit, conflicts, or failed Phase
7 status. Preserve the existing ledger backup and `.env`.

## 2. Apply one payload

Use either the delivered update patch or full source snapshot, not both. The
preferred installer verifies and applies the patch with strict whitespace
checks. It excludes `.env`, `.venv`, ledger files, outputs, logs, caches, and
Git metadata.

## 3. Migration and safe status

```powershell
python -m pip check
python run_phase8.py --status-only
python run_phase8.py --status-only
```

Expected migration `0007_governed_provider_calls` applies once and the second
status reports `newly_applied=none`. Status-only makes no provider call,
constructs no provider SDK client, and writes no deliverable.

## 4. Complete offline validation

```powershell
python -m pytest -q
python run_bootstrap_phase6.py --status-only
python run_phase7.py --status-only
python run_phase8.py --mock-canary
python run_phase8.py --mock-canary
python run_phase8.py --prepare-live
python run_loop_v0_2.py --preflight-only
```

Expected:

- the complete suite passes with only documented platform skips;
- Phase 6 and Phase 7 status remain passing;
- the first simulated canary completes two fixture calls and one artifact at
  zero external cost;
- immediate and later replay make zero new provider calls or artifact writes;
- live preparation prints a stable approval fingerprint but makes no call;
- legacy offline preflight remains passing;
- no provider client, paid request, or live-network request is made.

## 5. Local checkpoint

```powershell
git status
git diff --check
git add -- <reviewed Phase 8 paths>
git diff --cached --check
git commit -m "add governed provider orchestration"
git tag -a v0.3-phase8-governed-providers -m "Phase 8 governed provider orchestration"
git status
git log -3 --oneline --decorate
```

Review locally before pushing. Do not merge into `main` automatically.

## 6. `.env` and dependencies

Phase 8 adds no dependency and requires no `.env` change. It uses the existing
OpenAI/Anthropic keys and documented model/pricing defaults only after an
explicitly approved live command. The installer hashes `.env` before and after
installation and stops if it changes.

## 7. Live-canary boundary

Do not run the live command as part of installation. First review the prepared
contract, routes, token limits, budget, and approval fingerprint with the user.
The later command will have this shape:

```powershell
python run_phase8.py --live --approval phase8-live-<prepared-fingerprint>
```

Changing the contract, route, model, token limit, pricing input, or budget
changes the required fingerprint. A failed or ambiguous provider call is not
silently repeated; preserve the ledger and inspect the recorded state.

## 8. Recovery

The installer creates an annotated `phase8-preinstall-...` tag before applying
the patch. On validation failure it leaves the repository for inspection and
does not reset it automatically. Do not delete or rewrite the ledger to undo
additive migration `0007`; preserve the evidence and review it first.
