# Bootstrap Phase 1 Changelog

**Input archive SHA-256:**
`0EE6809B862EB1BA9B3D1CF85C1792335452E84B018B371F9A0550C8A7F7776C`

## Added

- `workspace_guard.py`
- `command_runner.py`
- `tests/test_workspace_guard.py`
- `tests/test_command_runner.py`
- `docs/implementation/BOOTSTRAP_PHASE_1.md`
- `PHASE_1_INSTALLATION.md`
- this changelog

## Updated

- `README.md` with Phase 1 behavior, test instructions, and the explicit
  application-policy-versus-OS-sandbox boundary.

## Unchanged

- `.env` was not present in the upload and is not part of the update.
- `.git` was not present and is not modified.
- `ledger.db` and `ledger.py` were not changed in this tranche.
- the dependency set was not changed; all new runtime code uses the Python
  standard library.
- the proven v0.2 runner and its original tests were not changed.

## Removed

- None. This is a narrow additive overlay; it does not delete project files.

## Migrated

- None. The SQLite ledger and existing state are intentionally untouched in
  this tranche.

## Excluded from the overlay

- `.env`, `.git`, `.venv`, `ledger.db`, `outputs`, and `logs`
- all unchanged project source, documentation, research, and tests

## Offline verification

- syntax parsing: PASS (16 Python files)
- preserved and new regression suite: **52 passed, 1 skipped**
- paid provider calls: **0**

The skipped case requires Windows symlink-creation privileges unavailable in the
verification environment. See the implementation document for the tested
resolution behavior and remaining OS-level containment limitations.
