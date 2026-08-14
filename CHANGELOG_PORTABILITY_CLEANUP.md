# Portability and Repository Cleanup Changelog

**Completed:** August 10, 2026  
**Candidate:** local v0.3 foundation derived from the proven v0.2 runtime  
**Scope:** isolated extracted copy only

## Source protection

- Source archive: `ai_loop_v0_1_portable_review.zip`
- Source archive SHA-256: `78E47A859B0F5B5537D92200187E2B5E20E0ABC82E8473C36702E641E9B37ED4`
- The archive copied into the audit workspace matched that hash exactly.
- The supplied source archive, original project folder, and frozen v0.2 backup were not modified.
- Removed material remains recoverable from the source archive and frozen backup.

## Portability defects corrected

### SQLite artifact paths

All eight completed rows in `steps.artifact_path` used the old machine path:

```text
C:\Users\dfoxy\Downloads\ai_loop_v0_1\ai_loop_v0_1\outputs\...
```

They were migrated in place to portable POSIX-style project-relative paths:

```text
outputs/01_gpt_brief.md
outputs/02_claude_draft.md
outputs/03_gpt_audit.md
outputs/04_claude_final.md
```

This occurred for two historical task IDs, producing eight migrated rows total.
Task, step, telemetry, reservation, and completion evidence was preserved. One
`artifact_paths_migrated` event records the migration count without retaining
the old machine path.

SQLite verification after migration:

- integrity check: `ok`;
- tasks: 3;
- steps: 8;
- telemetry rows: 8;
- budget reservations: 10;
- events: 9;
- remaining machine-specific path markers: 0;
- apparent API-key markers: 0.

### Runtime path handling

Added `project_paths.py` and updated configuration/ledger handling so that:

- relative runtime configuration resolves from the project directory, not the
  terminal's current directory;
- artifact paths are stored relative to the project with `/` separators;
- legacy Windows absolute paths ending in `outputs/...` migrate automatically;
- path traversal and artifact paths outside the candidate root are rejected;
- relative artifacts resolve correctly after the whole project is moved.

### Resume behavior when an artifact is absent

The former resume sequence checked for a missing file, reserved budget, then
tried to read the same missing completed artifact and raised `FileNotFoundError`.

The corrected sequence now:

1. resolves a completed artifact against the current project root;
2. reuses it only when it is a readable file;
3. records an `artifact_missing` state/event when the output was not transferred;
4. permits a controlled rerun through the existing budget guard.

No provider work is silently duplicated merely because a path string changed.
When the artifact itself is genuinely absent, regeneration is explicit in
durable state and still budget-gated.

### Real offline preflight

`run_loop_v0_2.py --preflight-only` was previously ignored because the program
did not parse arguments. It then entered the paid workflow and encountered the
stale ledger path.

The flag now performs only offline checks:

- project goal exists and is non-empty;
- SQLite integrity and path migration;
- completed-artifact availability;
- API key variable presence without displaying values;
- output directory remains project-relative.

Provider clients are imported/constructed only for a live workflow, after
argument handling. The preflight makes no provider calls.

## Consolidated and preserved

### Runtime kernel kept

- `run_loop_v0_2.py`
- `budget_guard.py`
- `classification.py`
- `config.py`
- `ledger.py`
- `provider_adapter.py`
- `retrieval_local.py`
- `router.py`
- `task_contract.py`
- `telemetry.py`
- `project/goal.md`
- `ledger.db` with migrated paths
- `tests/`

These files form or test the proven durable v0.2 kernel and are the correct
foundation for the separate v0.3 candidate.

### Requirements consolidated

The known-good frozen dependency set was promoted verbatim to the conventional
`requirements.txt` name. Its SHA-256 matches the original ZIP entry exactly:

```text
F44671A59B5389AB4C03836C1A3026E8C2313834158186DFEF6F7C3964AFC2E1
```

The unpinned v0.1 and redundant v0.2 requirement files were removed.

### Configuration consolidated

The three environment examples were merged into one `.env.example` containing
only the durable local runtime settings and portable path defaults. Research and
repair-run-only settings were omitted because their one-off runners were retired.

The v0.2 ignore additions were merged into `.gitignore`, including secrets,
environments, caches, mutable SQLite sidecars, logs, and generated outputs.

### Documentation preserved as references

The accepted v0.2.1 architecture package was moved from `final_v0_2_1/` to:

```text
docs/reference/v0_2_1_architecture/
```

The reusable validation contracts and summarized validator calibration report
were retained at:

```text
docs/reference/v0_2_1_validation/
```

The three supplied forward-planning documents were copied byte-for-byte into:

```text
docs/planning/
```

Their source SHA-256 hashes are:

- v0.3 savepoint: `BAC3E760A9A8A56B3F188EE1ED3EAB416C145BFE77411B9020085A65A845C0A8`
- bootstrap design: `259A587DF027F2D8B71311753EFA1892F78D2D6E256E38582B53EF0FB49595A2`
- overnight contract draft: `ECE399B463A7DC43A2F960736B55C4FB8C78B68634F5B53C6ADC00446BAF7C5D`

`README.md` was rewritten as the single current setup, portability, safety, and
forward-development guide.

## Removed from the candidate

### Superseded executable workflows

- `run_loop.py` — v0.1 smoke-test runner, superseded by the durable kernel.
- `run_architecture_study.py` — completed one-off v0.2 research orchestrator.
- `run_repair_study.py` — completed one-off v0.2.1 repair orchestrator; its
  accepted outputs and reusable calibration evidence were retained.

None of these files was imported by the retained runtime or tests.

### Superseded state and inputs

- `state.json`
- `state_v0_2.json`
- `STATUS.md`
- `LOCAL_BUILD_CHECK.txt`
- `MASTER_GOAL.md`
- `research_tracks.json`
- root `VALIDATION_CONTRACTS.json` after its reference copy was preserved

The state/status files described completed retired workflows rather than the
durable SQLite kernel. The two stale absolute paths in
`recovery_v0_2_1/state_v0_2_1.json` were eliminated by retiring that obsolete
recovery state; they were not part of canonical runtime state.

### Superseded or raw artifact trees

- `final/` — older v0.2 final set, superseded by the accepted v0.2.1 package.
- `research/` — raw v0.2 generation/audit/revision artifacts already synthesized
  into accepted reference outputs.
- `recovery_v0_2_1/` — attempts, duplicate accepted candidates, per-attempt
  validation records, and completed recovery state. Only the summarized
  validator preflight report was retained.

Exact duplicate hashing confirmed that the accepted final v0.2.1 modules were
duplicated among recovery candidates; the accepted copies were kept and the
candidate duplicates removed.

### Duplicate instructions and dependency files

- `README_v0_1.md`
- `README_v0_2.md`
- `README_v0_2_LOCAL.md`
- `README_v0_2_1_REPAIR.md`
- `.env.v0_2.example`
- `.env.v0_2_1.example`
- `.gitignore.v0_2_additions.txt`
- `requirements_v0_2.txt`
- `requirements_frozen_v0_2.txt` after its byte-identical promotion

Generated `__pycache__/` and `.pytest_cache/` directories were also removed.

## Verification performed without paid API calls

Using the existing Python 3.12.10 project environment:

- `pip check`: **PASS**, no broken requirements;
- syntax compilation: **PASS**, 12 Python files;
- regression suite: **PASS**, 11 tests;
- SQLite integrity: **PASS**;
- offline preflight: **PASS** with temporary placeholder key variables;
- machine-specific path scan of retained text: **PASS**;
- machine-specific path and apparent key-marker scan of SQLite: **PASS**.

Preflight produced one expected warning: all eight historical completed-artifact
records point to output files that were deliberately excluded from the supplied
portable-review ZIP.

No live OpenAI or Anthropic request was made.

## Remaining risks and next decisions

1. **Historical outputs are absent.** Reusing either historical task ID will
   require regeneration of missing work and may incur paid API usage. Review the
   goal and budget before any live run.
2. **Live provider behavior was not retested.** This cleanup deliberately stopped
   at offline verification to avoid exposing secrets or incurring charges.
3. **Models, prices, and provider SDK behavior are time-sensitive.** Review them
   against current official documentation before a paid run; do not assume the
   example rates are billing truth.
4. **The v0.3 bootstrap is planning only.** Command execution, workspace guard,
   patch manager, bounded repair loop, Git checkpoints, and extended schema are
   not implemented by this cleanup.
5. **The overnight contract is not launch-ready.** Its provider balances, safety
   reserves, hard ceilings, expected range, and maximum duration remain `TBD` and
   require explicit authorization.
6. **`ledger.db` contains historical objectives and telemetry.** No apparent
   secrets were found, but it should still be treated as internal project data
   rather than published casually.
