# Phase 9 Installation and Checkpoint

Apply Phase 9 only to the confirmed live-canary-ready checkpoint:

- branch: `bootstrap/local-execution`;
- commit: `afc2c683adc0fe524f020314204e4cd46e32bf80`;
- tag: `v0.3-phase8-live-canary-ready`;
- clean worktree synchronized with `origin/bootstrap/local-execution`.

The supplied Git Bash installer automates these gates. The manual procedure is
retained for review and recovery.

## 1. Pre-install

```powershell
git status
git branch --show-current
git rev-parse HEAD
git tag --points-at HEAD
python run_phase8.py --status-only
```

Stop on a dirty worktree, unexpected branch/commit, conflicts, or failed Phase
8 status. Preserve the existing ledger, outputs, logs, and `.env`.

## 2. Apply one payload

Use either the delivered update patch or full source snapshot, not both. The
preferred installer verifies and applies the patch with strict whitespace
checks. It excludes `.env`, `.venv`, ledgers, outputs, logs, caches, and Git
metadata.

## 3. Migration and safe status

```powershell
python -m pip check
python run_phase9.py --status-only
python run_phase9.py --status-only
```

Migration `0008_recovery_observability` applies once; the second status reports
`newly_applied=none`. Status-only makes no provider call and writes no artifact.

## 4. Complete offline validation

```powershell
python -m pytest -q
python run_bootstrap_phase6.py --status-only
python run_phase7.py --status-only
python run_phase8.py --status-only
python run_phase9.py --recovery-canary
python run_phase9.py --recovery-canary
python run_loop_v0_2.py --preflight-only
```

Expected:

- the complete suite passes with only documented platform skips;
- all earlier phase status checks remain passing;
- the first Phase 9 recovery canary records three fixture calls: composer
  success, known reviewer truncation, and reviewer retry success;
- cost is `$0.00`, the artifact reaches acceptance `PASS`, and no composer
  redispatch occurs;
- a diagnostic bundle is written below `logs/` with no raw prompts or full raw
  responses;
- the second invocation reports completed replay with zero new calls and no
  artifact rewrite;
- no provider client, paid request, or live-network request is made.

## 5. Local checkpoint

```powershell
git status
git diff --check
git add -- <reviewed Phase 9 paths>
git diff --cached --check
git commit -m "add bounded recovery and operator observability"
git tag -a v0.3-phase9-recovery-observability -m "Phase 9 recovery and observability"
git status
git log -3 --oneline --decorate
```

Review locally before pushing. The installer does not push or merge.

## 6. `.env` and dependencies

Phase 9 adds no dependency and requires no `.env` change. The installer hashes
`.env` before and after installation and stops if it changes.

## 7. Live boundary

Installation does not prepare or run a live canary. After reviewing the Phase
9 checkpoint, a separate canary can be prepared with:

```powershell
python run_phase9.py --prepare-live
```

The later `--live` command requires the exact printed fingerprint. Contract,
route, model, token, pricing, budget, prompt-template, or recovery-policy
changes produce a different fingerprint. Do not reuse the Phase 8 fingerprint.

## 8. Recovery

The installer creates an annotated `phase9-preinstall-...` tag. On failure it
leaves the repository and ledger intact for inspection and performs no reset.
Do not delete the ledger to recover. Generate a redacted bundle with:

```powershell
python run_diagnostics.py --latest
```

Only a known measured `response-truncated` failure is eligible for the single
reviewer retry. Ambiguous transport state still requires human review.
