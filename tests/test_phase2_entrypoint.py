from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from ledger import Ledger
from run_bootstrap_phase2 import run_bootstrap_phase2, source_snapshot_sha256
from test_runner import ValidationOutcome
from workspace_guard import WorkspaceGuard


def make_root(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    return root


def test_source_snapshot_changes_only_for_authorized_source(tmp_path):
    root = make_root(tmp_path)
    source = root / "main.py"
    source.write_text("value = 1\n", encoding="utf-8")
    (root / "outputs").mkdir()
    generated = root / "outputs" / "generated.py"
    generated.write_text("ignored = 1\n", encoding="utf-8")
    (root / ".venv").mkdir()
    (root / ".venv" / "installed.py").write_text("ignored = 2\n", encoding="utf-8")
    (root / ".pytest_tmp").mkdir()
    pytest_generated = root / ".pytest_tmp" / "generated.py"
    pytest_generated.write_text(
        "ignored = 3\n", encoding="utf-8"
    )
    guard = WorkspaceGuard(root)

    initial = source_snapshot_sha256(guard)
    generated.write_text("ignored = 3\n", encoding="utf-8")
    pytest_generated.write_text("ignored = 4\n", encoding="utf-8")
    runtime_changed = source_snapshot_sha256(guard)
    source.write_text("value = 2\n", encoding="utf-8")
    source_changed = source_snapshot_sha256(guard)

    assert runtime_changed == initial
    assert source_changed != initial


def test_entrypoint_runs_offline_suite_and_replays_unchanged_source(tmp_path):
    root = make_root(tmp_path)
    (root / "pytest.ini").write_text(
        (Path(__file__).resolve().parents[1] / "pytest.ini").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_sample.py").write_text(
        "def test_sample():\n    assert 3 * 3 == 9\n",
        encoding="utf-8",
    )
    environment = {}
    if os.environ.get("PYTHONPATH"):
        environment["PYTHONPATH"] = os.environ["PYTHONPATH"]
    first = run_bootstrap_phase2(
        project_root=root,
        ledger_path=root / "ledger.db",
        python_executable=sys.executable,
        pytest_environment=environment,
    )
    second = run_bootstrap_phase2(
        project_root=root,
        ledger_path=root / "ledger.db",
        python_executable=sys.executable,
        pytest_environment=environment,
    )

    assert first.passed is True
    assert first.suite.outcome == ValidationOutcome.PASS
    assert first.newly_applied_migrations == (
        "0001_bootstrap_commands_validations",
        "0002_transactional_changes",
        "0003_bounded_autonomy",
        "0004_research_provenance",
        "0005_acceptance_truth",
        "0006_project_orchestration",
        "0007_governed_provider_calls",
    )
    assert second.newly_applied_migrations == ()
    assert all(result.replayed for result in second.suite.results)
    ledger = Ledger(root / "ledger.db", project_root=root)
    command = ledger.get_command(
        f"bootstrap:phase2:pytest:{first.source_snapshot_sha256}:command"
    )
    assert command["request"]["argv"][-2:] == [
        "--basetemp",
        ".pytest_tmp",
    ]
    stale = root / "logs" / "pytest_tmp" / "stale" / "candidate"
    stale.mkdir(parents=True, exist_ok=True)
    (stale / "test_sample.py").write_text(
        "def test_stale_copy():\n    assert False\n",
        encoding="utf-8",
    )
    collection = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    collected_output = (collection.stdout + collection.stderr).replace("\\", "/")
    assert collection.returncode == 0, collected_output
    assert "tests/test_sample.py::test_sample" in collected_output
    assert "logs/pytest_tmp" not in collected_output
    with ledger.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM validation_runs").fetchone()[0] == 2


def test_status_only_migrates_and_checks_integrity_without_dispatch(tmp_path):
    root = make_root(tmp_path)

    report = run_bootstrap_phase2(
        project_root=root,
        ledger_path=root / "ledger.db",
        status_only=True,
    )

    assert report.passed is True
    assert report.integrity == "ok"
    assert report.suite is None
    ledger = Ledger(root / "ledger.db", project_root=root)
    with ledger.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM validation_runs").fetchone()[0] == 0
