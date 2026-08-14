# Bootstrap Phase 2 Installation

This is a paste-over update for the existing `ai_loop_v0_3_candidate` at the
Phase 1 checkpoint. It contains no secrets, Git metadata, virtual environment,
runtime ledger, outputs, or logs.

## Correct placement

Extract the update beside the candidate:

```text
Agentic Project Workspace/
|-- .venv/
|-- ai_loop_v0_3_candidate/       <- paste update contents here
`-- bootstrap_phase_2_update/     <- temporary extracted update folder
```

Copy the **contents** of `bootstrap_phase_2_update` into
`ai_loop_v0_3_candidate`. Do not put the outer update folder inside the
candidate. Merge `tests` and `docs`, and replace matching files when prompted.

## Back up SQLite before its first Phase 2 open

From inside `ai_loop_v0_3_candidate`, with no loop process running, create a
consistent SQLite backup as a sibling of the project:

```powershell
python -c "import sqlite3; s=sqlite3.connect('ledger.db'); d=sqlite3.connect(r'..\ai_loop_v0_3_candidate_ledger_pre_phase2.db'); s.backup(d); d.close(); s.close(); print('Ledger backup complete')"
```

The migration is additive and has been tested against a disposable copy of the
uploaded ledger, but this backup provides a simple recovery point for mutable
runtime state that is intentionally excluded from Git.

## PowerShell copy method

If the extracted update is the sibling shown above, run this from
`Agentic Project Workspace`:

```powershell
robocopy .\bootstrap_phase_2_update .\ai_loop_v0_3_candidate /E
if ($LASTEXITCODE -ge 8) { throw "Update copy failed with robocopy code $LASTEXITCODE" }
```

Robocopy codes 0 through 7 are successful. The update cannot overwrite `.env`,
`.git`, `.venv`, `ledger.db`, `outputs`, or `logs` because none are included.

## Verify offline

If the prompt already ends in `ai_loop_v0_3_candidate>`, do not run another
`cd .\ai_loop_v0_3_candidate`. Otherwise enter it from the parent workspace.

```powershell
cd .\ai_loop_v0_3_candidate
..\.venv\Scripts\Activate.ps1

python -m pip check
python -m pytest -q
python run_bootstrap_phase2.py --status-only
python run_bootstrap_phase2.py
python run_loop_v0_2.py --preflight-only
```

Expected results:

- pytest: `83 passed, 1 skipped` when Windows link creation is unavailable;
- Phase 2 schema: `0001_bootstrap_commands_validations`;
- Phase 2 result: `PASS`;
- v0.2 offline preflight: `PASS` (the historical-artifact warning may remain).

All commands above are offline and make no provider calls. The full Phase 2
entry point stores syntax and pytest evidence in the migrated ledger. Running it
again without source changes reports the records as replayed. Use
`python run_bootstrap_phase2.py --rerun` only for an intentional fresh evidence
run against unchanged source.

## Record the milestone in Git

Confirm that the Phase 1 branch is active:

```powershell
git branch --show-current
```

It should print `bootstrap/local-execution`. Then, after all verification passes:

```powershell
git status
git add README.md BOOTSTRAP_PHASE_2_CHANGELOG.md PHASE_2_INSTALLATION.md command_runner.py durable_execution.py ledger.py run_bootstrap_phase2.py test_runner.py tests docs
git commit -m "add durable validation and command records"
git tag v0.3-bootstrap-phase2

git log --oneline --decorate -3
git status
```

`ledger.db` and its sibling backup remain outside Git. If the Phase 2 tag already
exists, inspect it before changing anything:

```powershell
git show --stat v0.3-bootstrap-phase2
```
