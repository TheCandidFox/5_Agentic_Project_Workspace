# Phase 2 Hotfix 2

This small paste-over update makes top-level pytest collection repeatable after
the guarded Phase 2 test run has created its project-local temporary workspace.

It adds `pytest.ini` with an explicit `tests` collection boundary, gives direct
pytest a safe project-local `.pytest_tmp` directory, and excludes generated
trees including `.pytest_tmp`, `logs`, and `outputs`. Guarded pytest now uses
the same location. This prevents both shared Windows temporary-directory errors
and collection of temporary test copies left by earlier runs.

## Apply

Extract `bootstrap_phase_2_hotfix_2` beside `ai_loop_v0_3_candidate`. From
`Agentic Project Workspace`, copy the hotfix contents over the candidate:

```powershell
robocopy .\bootstrap_phase_2_hotfix_2 .\ai_loop_v0_3_candidate /E
if ($LASTEXITCODE -ge 8) { throw "Hotfix copy failed with robocopy code $LASTEXITCODE" }
```

Then run from inside the candidate:

```powershell
python -m pip check
python -m pytest -q
python run_bootstrap_phase2.py --status-only
python run_bootstrap_phase2.py
python run_loop_v0_2.py --preflight-only
```

Expected results:

- dependency check: no broken requirements;
- pytest: `83 passed, 1 skipped` when link creation is unavailable;
- Phase 2 result: `PASS`;
- offline v0.2 preflight: `PASS`.

The existing `logs/pytest_tmp` tree may remain; pytest no longer traverses it.
Both that tree and `.pytest_tmp` are ignored runtime state and can be removed
later when convenient.

No ledger backup or schema migration is required. This update changes a Python
regression test, so the Phase 2 source snapshot changes and a fresh guarded
pytest command is dispatched automatically. All checks are offline and make no
provider calls.
