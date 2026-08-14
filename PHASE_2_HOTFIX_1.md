# Phase 2 Hotfix 1

This small paste-over update fixes guarded pytest on Windows when the scrubbed
child environment cannot use a shared `pytest-of-unknown` temporary directory.

It changes guarded pytest to use:

```text
--basetemp logs/pytest_tmp
```

That location is project-local, runtime-only, and already excluded by
`.gitignore`. It also adds a bounded redacted output tail to future Phase 2
failure reports.

## Apply

Extract `bootstrap_phase_2_hotfix_1` beside `ai_loop_v0_3_candidate`. From
`Agentic Project Workspace`, copy the hotfix contents over the candidate:

```powershell
robocopy .\bootstrap_phase_2_hotfix_1 .\ai_loop_v0_3_candidate /E
if ($LASTEXITCODE -ge 8) { throw "Hotfix copy failed with robocopy code $LASTEXITCODE" }
```

Then run from inside the candidate:

```powershell
python -m pytest -q
python run_bootstrap_phase2.py
python run_loop_v0_2.py --preflight-only
```

No new ledger backup or schema migration is required. The previous failed
command and validation remain as historical evidence. Because this hotfix
changes source files, the Phase 2 entry point calculates a new source snapshot
and dispatches a fresh pytest command automatically; `--rerun` is not needed.

Expected results:

- pytest: `83 passed, 1 skipped` when link creation is unavailable;
- Phase 2 result: `PASS`;
- offline v0.2 preflight: `PASS`.

All checks are offline and make no provider calls.
