from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from bootstrap_acceptance import FINAL_BOOTSTRAP_GATES
from ledger import Ledger
from run_phase7 import print_report, run_phase7


GIT = os.environ.get("AI_LOOP_GIT_EXECUTABLE") or shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="Git is not installed")


def make_candidate(tmp_path: Path) -> Path:
    root = tmp_path / "candidate"
    root.mkdir()
    (root / ".gitignore").write_text(
        "ledger.db\nledger.db-shm\nledger.db-wal\noutputs/\nlogs/\n.pytest_tmp/\n",
        encoding="utf-8",
    )
    subprocess.run(
        [GIT, "init", "--initial-branch", "main"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    project = root / "project"
    project.mkdir()
    sample = Path(__file__).resolve().parents[1] / "project" / "phase7_sample_goal.md"
    (project / "phase7_sample_goal.md").write_text(
        sample.read_text(encoding="utf-8"), encoding="utf-8"
    )
    functions_by_path: dict[str, set[str]] = {}
    for gate in FINAL_BOOTSTRAP_GATES:
        for node in gate.evidence_nodes:
            path, function_name = node.split("::", 1)
            functions_by_path.setdefault(path, set()).add(function_name)
    for path, function_names in functions_by_path.items():
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            "\n\n".join(
                f"def {function_name}():\n    assert True"
                for function_name in sorted(function_names)
            )
            + "\n",
            encoding="utf-8",
        )
    return root


def test_status_only_validates_contract_graph_and_schema_without_dispatch(tmp_path):
    root = make_candidate(tmp_path)
    report = run_phase7(
        project_root=root,
        ledger_path=root / "ledger.db",
        status_only=True,
        git_executable=GIT,
    )

    assert report.passed is True
    assert report.status_only is True
    assert report.schema_ready is True
    assert report.policy_ready is True
    assert report.graph.topological_order == (
        "compose-checklist",
        "validate-checklist",
    )
    assert report.first_result is None
    assert report.replay_result is None
    assert not (root / "outputs").exists()
    with Ledger(root / "ledger.db", project_root=root).connect() as con:
        assert con.execute("SELECT COUNT(*) FROM project_runs").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM task_dispatches").fetchone()[0] == 0


def test_full_entrypoint_completes_sample_and_replays_without_new_dispatch(tmp_path, capsys):
    root = make_candidate(tmp_path)
    first = run_phase7(
        project_root=root,
        ledger_path=root / "ledger.db",
        git_executable=GIT,
    )
    print_report(first)
    output = capsys.readouterr().out
    second = run_phase7(
        project_root=root,
        ledger_path=root / "ledger.db",
        git_executable=GIT,
    )

    assert first.passed is True
    assert first.first_result is not None and first.first_result.completed
    assert first.replay_result is not None and first.replay_result.replayed
    assert first.first_dispatch_calls == 2
    assert first.replay_dispatch_calls == 0
    assert second.passed is True
    assert second.first_result is not None and second.first_result.replayed
    assert second.first_dispatch_calls == 0
    assert second.replay_dispatch_calls == 0
    assert "Phase 7 result: PASS" in output
    assert "offline, zero cost" in output
    assert "new_dispatch_calls=0" in output
    assert str(root) not in output
    artifact = root / "outputs" / "phase7_supplier_evaluation_checklist.md"
    assert artifact.is_file()
    assert "## Price and value" in artifact.read_text(encoding="utf-8")


def test_status_reports_migration_six_once(tmp_path):
    root = make_candidate(tmp_path)
    first = run_phase7(
        project_root=root,
        ledger_path=root / "ledger.db",
        status_only=True,
        git_executable=GIT,
    )
    second = run_phase7(
        project_root=root,
        ledger_path=root / "ledger.db",
        status_only=True,
        git_executable=GIT,
    )

    assert first.newly_applied_migrations == (
        "0001_bootstrap_commands_validations",
        "0002_transactional_changes",
        "0003_bounded_autonomy",
        "0004_research_provenance",
        "0005_acceptance_truth",
        "0006_project_orchestration",
        "0007_governed_provider_calls",
        "0008_recovery_observability",
        "0009_bounded_revision_cycle",
    )
    assert second.newly_applied_migrations == ()
    assert first.integrity == second.integrity == "ok"
