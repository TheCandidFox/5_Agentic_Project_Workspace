from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from bootstrap_acceptance import FINAL_BOOTSTRAP_GATES
from ledger import Ledger
from provider_fixtures import ScriptedProviderClient, passing_phase8_replies
from provider_gateway import ProviderRoute
from run_phase8 import Phase8Mode, Phase8Routes, run_phase8


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
    source_project = Path(__file__).resolve().parents[1] / "project"
    for name in (
        "phase7_sample_goal.md",
        "phase8_mock_goal.md",
        "phase8_live_canary_goal.md",
    ):
        (project / name).write_text(
            (source_project / name).read_text(encoding="utf-8"), encoding="utf-8"
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


def routes() -> Phase8Routes:
    return Phase8Routes(
        composer=ProviderRoute("openai", "fixture-openai", 1500, 2.5, 15),
        reviewer=ProviderRoute("anthropic", "fixture-anthropic", 1200, 2, 10),
    )


def test_status_and_prepare_construct_no_client_and_write_no_artifact(tmp_path):
    root = make_candidate(tmp_path)
    factory_calls = 0

    def forbidden_factory():
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("provider client must not be constructed")

    status = run_phase8(
        project_root=root,
        ledger_path=root / "ledger.db",
        contract_path="project/phase8_live_canary_goal.md",
        routes=routes(),
        mode=Phase8Mode.STATUS,
        git_executable=GIT,
        provider_client_factory=forbidden_factory,
    )
    prepared = run_phase8(
        project_root=root,
        ledger_path=root / "ledger.db",
        contract_path="project/phase8_live_canary_goal.md",
        routes=routes(),
        mode=Phase8Mode.PREPARE_LIVE,
        git_executable=GIT,
        provider_client_factory=forbidden_factory,
    )

    assert status.passed and prepared.passed
    assert status.approval_token == prepared.approval_token
    assert status.schema_ready and status.policy_ready
    assert factory_calls == 0
    assert not (root / "outputs").exists()
    with Ledger(root / "ledger.db", project_root=root).connect() as con:
        assert con.execute("SELECT COUNT(*) FROM provider_calls").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM project_runs").fetchone()[0] == 0


def test_mock_canary_completes_and_replays_without_external_cost(tmp_path):
    root = make_candidate(tmp_path)
    first = run_phase8(
        project_root=root,
        ledger_path=root / "ledger.db",
        contract_path="project/phase8_mock_goal.md",
        routes=routes(),
        mode=Phase8Mode.MOCK,
        git_executable=GIT,
    )
    second = run_phase8(
        project_root=root,
        ledger_path=root / "ledger.db",
        contract_path="project/phase8_mock_goal.md",
        routes=routes(),
        mode=Phase8Mode.MOCK,
        git_executable=GIT,
    )

    assert first.passed and second.passed
    assert first.first_provider_calls == 2
    assert first.replay_provider_calls == 0
    assert first.first_result is not None and first.first_result.cost_usd == 0
    assert second.first_result is not None and second.first_result.replayed
    assert second.first_provider_calls == 0
    artifact = root / "outputs" / "phase8_mock_canary_brief.md"
    assert artifact.is_file()
    with Ledger(root / "ledger.db", project_root=root).connect() as con:
        assert con.execute("SELECT COUNT(*) FROM provider_calls").fetchone()[0] == 2


def test_bad_live_fingerprint_stops_before_client_construction(tmp_path):
    root = make_candidate(tmp_path)
    factory_calls = 0

    def forbidden_factory():
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("provider client must not be constructed")

    with pytest.raises(PermissionError, match="fingerprint"):
        run_phase8(
            project_root=root,
            ledger_path=root / "ledger.db",
            contract_path="project/phase8_live_canary_goal.md",
            routes=routes(),
            mode=Phase8Mode.LIVE,
            approval="wrong",
            git_executable=GIT,
            provider_client_factory=forbidden_factory,
        )
    assert factory_calls == 0
    assert not (root / "outputs").exists()
    with Ledger(root / "ledger.db", project_root=root).connect() as con:
        assert con.execute("SELECT COUNT(*) FROM provider_calls").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM project_runs").fetchone()[0] == 0


def test_approved_live_path_uses_injected_client_and_records_measured_cost(tmp_path):
    root = make_candidate(tmp_path)
    selected_routes = routes()
    prepared = run_phase8(
        project_root=root,
        ledger_path=root / "ledger.db",
        contract_path="project/phase8_live_canary_goal.md",
        routes=selected_routes,
        mode=Phase8Mode.PREPARE_LIVE,
        git_executable=GIT,
    )
    client = ScriptedProviderClient(
        passing_phase8_replies(
            prepared.contract,
            composer_provider=selected_routes.composer.provider,
            composer_model=selected_routes.composer.model,
            reviewer_provider=selected_routes.reviewer.provider,
            reviewer_model=selected_routes.reviewer.model,
        )
    )
    # This injected test double exercises the live accounting path without a
    # network. Real CLI runs construct ProviderAdapter instead.
    client.offline_fixture = False
    report = run_phase8(
        project_root=root,
        ledger_path=root / "ledger.db",
        contract_path="project/phase8_live_canary_goal.md",
        routes=selected_routes,
        mode=Phase8Mode.LIVE,
        approval=prepared.approval_token,
        git_executable=GIT,
        provider_client_factory=lambda: client,
    )

    assert report.passed
    assert report.first_result is not None
    assert 0 < report.first_result.cost_usd < prepared.contract.policy.budget_usd
    assert client.call_count == 2
    with Ledger(root / "ledger.db", project_root=root).connect() as con:
        modes = {
            row["execution_mode"]
            for row in con.execute("SELECT execution_mode FROM provider_calls")
        }
        cost = con.execute(
            "SELECT SUM(estimated_cost_usd) FROM provider_calls"
        ).fetchone()[0]
    assert modes == {"live"}
    assert 0 < float(cost) < prepared.contract.policy.budget_usd
