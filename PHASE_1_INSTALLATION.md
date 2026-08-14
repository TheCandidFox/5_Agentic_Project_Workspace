# Bootstrap Phase 1 Installation

This update is a paste-over package for the existing `ai_loop_v0_3_candidate`
project. It does not contain `.env`, `.git`, `.venv`, `ledger.db`, `outputs`, or
`logs`.

## Correct folder placement

Keep the shared virtual environment beside the candidate project:

```text
Agentic Project Workspace/
|-- .venv/
|-- ai_loop_v0_3_candidate/       <- existing project; paste update contents here
`-- bootstrap_phase_1_update/     <- temporary extracted update folder
```

Do not paste the outer `bootstrap_phase_1_update` folder inside the project.
Paste or copy its **contents** into `ai_loop_v0_3_candidate`, merging the
`tests` and `docs` folders and replacing `README.md` when prompted.

The resulting project locations are:

```text
ai_loop_v0_3_candidate/
|-- command_runner.py
|-- workspace_guard.py
|-- README.md
|-- BOOTSTRAP_PHASE_1_CHANGELOG.md
|-- PHASE_1_INSTALLATION.md
|-- tests/
|   |-- test_command_runner.py
|   `-- test_workspace_guard.py
`-- docs/
    `-- implementation/
        `-- BOOTSTRAP_PHASE_1.md
```

Your existing `.env`, `.git`, `ledger.db`, source files, research, and other
project contents remain in place.

## PowerShell copy method

From `Agentic Project Workspace`, after extracting this update as the sibling
folder shown above:

```powershell
robocopy .\bootstrap_phase_1_update .\ai_loop_v0_3_candidate /E
if ($LASTEXITCODE -ge 8) { throw "Update copy failed with robocopy code $LASTEXITCODE" }
```

Robocopy codes 0 through 7 are successful outcomes. This update has no secret
or Git files to overwrite.

## Verify offline

```powershell
cd .\ai_loop_v0_3_candidate
..\.venv\Scripts\Activate.ps1
python -m pip check
python -m pytest -q
python run_loop_v0_2.py --preflight-only
```

The preflight is offline and does not make provider calls. It should report
`Preflight result: PASS`; warnings about missing historical completed artifacts
may remain informational if the old `outputs` folder was intentionally omitted.

## Record the milestone in Git

First confirm the current branch:

```powershell
git branch --show-current
```

If it prints `bootstrap/local-execution`, continue. If that branch already
exists but is not active, run `git switch bootstrap/local-execution`. If it does
not exist, run `git switch -c bootstrap/local-execution`.

Then record the verified update:

```powershell
git status
git add README.md BOOTSTRAP_PHASE_1_CHANGELOG.md PHASE_1_INSTALLATION.md command_runner.py workspace_guard.py tests docs
git commit -m "add guarded local command execution bootstrap"
git tag v0.3-bootstrap-phase1
```

If the tag already exists, inspect it before changing anything:

```powershell
git show --stat v0.3-bootstrap-phase1
```
