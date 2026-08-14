from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from run_bootstrap_transactional import (
    print_report,
    run_bootstrap_transactional,
)


GIT = os.environ.get("AI_LOOP_GIT_EXECUTABLE") or shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="Git is not installed")


def make_candidate(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    (root / ".gitignore").write_text(
        "ledger.db\nledger.db-shm\nledger.db-wal\nlogs/\n.pytest_tmp/\n",
        encoding="utf-8",
    )
    subprocess.run(
        [GIT, "init", "--initial-branch", "main"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return root


def test_transactional_status_applies_additive_schema_without_tests(tmp_path):
    root = make_candidate(tmp_path)

    report = run_bootstrap_transactional(
        project_root=root,
        ledger_path=root / "ledger.db",
        status_only=True,
        git_executable=GIT,
    )

    assert report.passed is True
    assert report.integrity == "ok"
    assert report.transaction_tables_ready is True
    assert report.newly_applied_migrations == (
        "0001_bootstrap_commands_validations",
        "0002_transactional_changes",
        "0003_bounded_autonomy",
        "0004_research_provenance",
        "0005_acceptance_truth",
        "0006_project_orchestration",
        "0007_governed_provider_calls",
        "0008_recovery_observability",
    )
    assert report.phase2 is None
    assert report.git_status.branch == "main"
    assert not report.git_status.conflicts


def test_transactional_full_run_executes_offline_phase2_suite_and_reports(tmp_path, capsys):
    root = make_candidate(tmp_path)
    (root / "pytest.ini").write_text(
        (Path(__file__).resolve().parents[1] / "pytest.ini").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_sample.py").write_text(
        "def test_sample():\n    assert 4 * 4 == 16\n",
        encoding="utf-8",
    )
    environment = {}
    if os.environ.get("PYTHONPATH"):
        environment["PYTHONPATH"] = os.environ["PYTHONPATH"]

    report = run_bootstrap_transactional(
        project_root=root,
        ledger_path=root / "ledger.db",
        git_executable=GIT,
        python_executable=sys.executable,
        pytest_environment=environment,
    )
    print_report(report)
    output = capsys.readouterr().out

    assert report.passed is True
    assert report.phase2 is not None and report.phase2.passed is True
    assert "Transactional result: PASS" in output
    assert "no provider calls" in output
    assert str(root) not in output
