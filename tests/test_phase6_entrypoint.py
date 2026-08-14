from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from bootstrap_acceptance import FINAL_BOOTSTRAP_GATES, inspect_gate_evidence
from ledger import Ledger
from run_bootstrap_phase6 import print_report, run_bootstrap_phase6


GIT = os.environ.get("AI_LOOP_GIT_EXECUTABLE") or shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="Git is not installed")


def make_candidate(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    (root / ".gitignore").write_text(
        "ledger.db\nledger.db-shm\nledger.db-wal\n.pytest_tmp/\n",
        encoding="utf-8",
    )
    subprocess.run(
        [GIT, "init", "--initial-branch", "main"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    (root / "pytest.ini").write_text(
        (Path(__file__).resolve().parents[1] / "pytest.ini").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    return root


def write_gate_evidence_stubs(root):
    functions_by_path = {}
    for gate in FINAL_BOOTSTRAP_GATES:
        for node in gate.evidence_nodes:
            path, function_name = node.split("::", 1)
            functions_by_path.setdefault(path, set()).add(function_name)
    for path, function_names in functions_by_path.items():
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = "\n\n".join(
            f"def {function_name}():\n    assert True"
            for function_name in sorted(function_names)
        )
        destination.write_text(source + "\n", encoding="utf-8")


def test_gate_manifest_fails_closed_when_evidence_is_missing(tmp_path):
    issues = inspect_gate_evidence(tmp_path)

    assert issues
    assert "command-capture" in issues
    assert any("missing" in item for item in issues["command-capture"])


def test_phase6_status_applies_schema_without_smoke_or_network(tmp_path):
    root = make_candidate(tmp_path)
    write_gate_evidence_stubs(root)

    report = run_bootstrap_phase6(
        project_root=root,
        ledger_path=root / "ledger.db",
        status_only=True,
        git_executable=GIT,
    )

    assert report.passed is True
    assert report.status_only is True
    assert report.schema_ready is True
    assert report.live_http_disabled_by_default is True
    assert report.gate_manifest_ready is True
    assert report.research_smoke is None
    assert report.calibration is None
    assert report.gates == ()
    assert report.newly_applied_migrations == (
        "0001_bootstrap_commands_validations",
        "0002_transactional_changes",
        "0003_bounded_autonomy",
        "0004_research_provenance",
        "0005_acceptance_truth",
    )
    ledger = Ledger(root / "ledger.db", project_root=root)
    with ledger.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM acceptance_runs").fetchone()[0] == 0


def test_phase6_full_verification_runs_ten_gates_and_replays(tmp_path, capsys):
    root = make_candidate(tmp_path)
    write_gate_evidence_stubs(root)
    environment = {}
    if os.environ.get("PYTHONPATH"):
        environment["PYTHONPATH"] = os.environ["PYTHONPATH"]

    first = run_bootstrap_phase6(
        project_root=root,
        ledger_path=root / "ledger.db",
        git_executable=GIT,
        python_executable=sys.executable,
        pytest_environment=environment,
    )
    print_report(first)
    output = capsys.readouterr().out
    second = run_bootstrap_phase6(
        project_root=root,
        ledger_path=root / "ledger.db",
        git_executable=GIT,
        python_executable=sys.executable,
        pytest_environment=environment,
    )

    assert first.passed is True
    assert first.research_smoke is not None and first.research_smoke.passed
    assert first.calibration is not None and first.calibration.passed
    assert len(first.gates) == 10
    assert all(gate.passed for gate in first.gates)
    assert second.passed is True
    assert second.bounded.transactional.phase2 is not None
    assert all(
        result.replayed for result in second.bounded.transactional.phase2.suite.results
    )
    assert second.research_smoke is not None
    assert second.research_smoke.first_replayed is True
    assert second.research_smoke.retrieval_calls == 0
    assert "Phase 6 bootstrap result: PASS" in output
    assert "no provider or network calls" in output
    assert "gate 10/10 research-provenance" in output
    assert str(root) not in output
