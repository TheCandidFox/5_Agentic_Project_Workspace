from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil

import pytest

from budget_guard import BudgetGuard
from git_checkpoint import CheckpointRequest, GitCheckpointManager
from ledger import Ledger
from patch_manager import FilePatch, PatchManager, PatchRequest, file_sha256
from repair_loop import (
    BoundedRepairLoop,
    RepairContext,
    RepairPolicy,
    RepairProposal,
    RepairRequest,
)
from test_runner import FileCheck, PythonSyntaxCheck, TestRunner
from workspace_guard import WorkspaceGuard


GIT = os.environ.get("AI_LOOP_GIT_EXECUTABLE") or shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="Git is not installed")


class SequenceAgent:
    label = "offline-sequence-agent"

    def __init__(
        self, proposals, *, estimate=0.0, on_estimate=None, on_propose=None
    ):
        self.proposals = list(proposals)
        self.estimate = estimate
        self.on_estimate = on_estimate
        self.on_propose = on_propose
        self.propose_calls = 0

    def estimate_cost(self, context: RepairContext) -> float:
        if self.on_estimate is not None:
            self.on_estimate()
        return self.estimate

    def propose(self, context: RepairContext) -> RepairProposal:
        if self.on_propose is not None:
            self.on_propose()
        proposal = self.proposals[min(self.propose_calls, len(self.proposals) - 1)]
        self.propose_calls += 1
        return proposal


def make_system(tmp_path, files):
    root = tmp_path / "candidate"
    root.mkdir()
    (root / ".gitignore").write_text(
        "ledger.db\nledger.db-shm\nledger.db-wal\nlogs/\n.pytest_tmp/\n",
        encoding="utf-8",
    )
    for path, content in files.items():
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    ledger = Ledger(root / "ledger.db", project_root=root)
    guard = WorkspaceGuard(root)
    git = GitCheckpointManager(guard, ledger, git_executable=GIT)
    git.initialize_repository(
        initial_branch="main",
        idempotency_key="test:git:init",
        task_id="repair-task",
    )
    git.create_checkpoint(
        CheckpointRequest(
            checkpoint_id="baseline-checkpoint",
            idempotency_key="test:git:baseline",
            actor="test",
            reason="broken fixture baseline",
            paths=(".gitignore", *files.keys()),
            task_id="repair-task",
        )
    )
    runner = TestRunner(guard, store=ledger)
    patches = PatchManager(guard, ledger)
    return root, ledger, git, runner, patches


def request_for(*paths, policy=None):
    return RepairRequest(
        run_id="repair-run-1",
        idempotency_key="repair:test:1",
        task_id="repair-task",
        actor="offline-test-agent",
        objective="repair the syntax fixture",
        checks=(
            PythonSyntaxCheck(
                check_id="fixture-syntax",
                paths=tuple(paths),
            ),
        ),
        policy=policy or RepairPolicy(),
    )


def make_loop(ledger, git, runner, patches, agent, **kwargs):
    return BoundedRepairLoop(
        ledger=ledger,
        test_runner=runner,
        patch_manager=patches,
        checkpoint_manager=git,
        repair_agent=agent,
        **kwargs,
    )


def test_tiny_broken_fixture_is_repaired_validated_and_checkpointed(tmp_path):
    root, ledger, git, runner, patches = make_system(
        tmp_path, {"app.py": "def broken(\n"}
    )
    proposal = RepairProposal(
        hypothesis="close the function declaration",
        files=(
            FilePatch(
                "app.py",
                "def repaired():\n    return True\n",
                expected_sha256=file_sha256(root / "app.py"),
            ),
        ),
    )
    agent = SequenceAgent([proposal])
    loop = make_loop(ledger, git, runner, patches, agent)
    request = request_for("app.py")

    result = loop.run(request)
    replay = loop.run(request)

    assert result.status == "passed"
    assert result.stop_reason == "validation_passed"
    assert result.attempts == 1
    assert result.checkpoint_id is not None
    assert (root / "app.py").read_text(encoding="utf-8").startswith("def repaired")
    assert git.status().clean is True
    assert replay.replayed is True
    assert replay.checkpoint_id == result.checkpoint_id
    assert agent.propose_calls == 1


def test_unfixable_attempt_is_rolled_back_and_stops_at_attempt_limit(tmp_path):
    root, ledger, git, runner, patches = make_system(
        tmp_path, {"app.py": "def original_broken(\n"}
    )
    original = (root / "app.py").read_text(encoding="utf-8")
    proposal = RepairProposal(
        hypothesis="an attempted repair that remains invalid",
        files=(
            FilePatch(
                "app.py",
                "def still_broken(:\n",
                expected_sha256=file_sha256(root / "app.py"),
            ),
        ),
    )
    loop = make_loop(
        ledger,
        git,
        runner,
        patches,
        SequenceAgent([proposal]),
    )

    result = loop.run(
        request_for("app.py", policy=RepairPolicy(max_attempts=1))
    )

    assert result.status == "blocked"
    assert result.stop_reason == "attempt_limit"
    assert (root / "app.py").read_text(encoding="utf-8") == original
    assert git.status().clean is True
    run = ledger.get_repair_run(run_id="repair-run-1")
    assert run["attempts"][0]["status"] == "rolled_back"
    assert ledger.get_patch(patch_id=run["attempts"][0]["patch_id"])["status"] == "rolled_back"


def test_repeated_identical_patch_is_blocked_before_second_write(tmp_path):
    root, ledger, git, runner, patches = make_system(
        tmp_path,
        {
            "app.py": "def app_broken(\n",
            "other.py": "def other_broken(\n",
        },
    )
    proposal = RepairProposal(
        hypothesis="repair only one of two failures",
        files=(
            FilePatch(
                "app.py",
                "def app_fixed():\n    return True\n",
                expected_sha256=file_sha256(root / "app.py"),
            ),
        ),
    )
    agent = SequenceAgent([proposal, proposal])
    loop = make_loop(ledger, git, runner, patches, agent)

    result = loop.run(
        request_for(
            "app.py",
            "other.py",
            policy=RepairPolicy(
                max_attempts=3,
                max_identical_failures=4,
                max_no_progress_attempts=3,
            ),
        )
    )

    assert result.status == "blocked"
    assert result.stop_reason == "repeated_identical_patch"
    assert result.attempts == 2
    assert agent.propose_calls == 2
    run = ledger.get_repair_run(run_id="repair-run-1")
    assert [item["status"] for item in run["attempts"]] == [
        "rolled_back",
        "rejected",
    ]
    assert git.status().clean is True


@pytest.mark.parametrize(
    ("policy", "expected_reason"),
    (
        (
            RepairPolicy(
                max_identical_failures=2,
                max_no_progress_attempts=5,
            ),
            "repeated_identical_failure",
        ),
        (
            RepairPolicy(
                max_identical_failures=5,
                max_no_progress_attempts=1,
            ),
            "no_progress_limit",
        ),
    ),
)
def test_identical_failure_and_no_progress_limits_are_enforced(
    tmp_path, policy, expected_reason
):
    root, ledger, git, runner, patches = make_system(
        tmp_path, {"app.py": "value = 1\n"}
    )
    proposal = RepairProposal(
        hypothesis="changes code but cannot create the required evidence file",
        files=(
            FilePatch(
                "app.py",
                "value = 2\n",
                expected_sha256=file_sha256(root / "app.py"),
            ),
        ),
    )
    request = RepairRequest(
        run_id="repair-run-1",
        idempotency_key="repair:test:1",
        task_id="repair-task",
        actor="offline-test-agent",
        objective="produce required evidence",
        checks=(
            FileCheck(
                check_id="required-evidence",
                path="required.txt",
                must_exist=True,
            ),
        ),
        policy=policy,
    )

    result = make_loop(
        ledger, git, runner, patches, SequenceAgent([proposal])
    ).run(request)

    assert result.status == "blocked"
    assert result.stop_reason == expected_reason
    assert result.attempts == 1
    assert (root / "app.py").read_text(encoding="utf-8") == "value = 1\n"
    assert git.status().clean is True


def test_budget_denial_happens_before_agent_dispatch(tmp_path):
    root, ledger, git, runner, patches = make_system(
        tmp_path, {"app.py": "def broken(\n"}
    )
    proposal = RepairProposal(
        hypothesis="would repair if admitted",
        files=(
            FilePatch(
                "app.py",
                "def repaired():\n    pass\n",
                expected_sha256=file_sha256(root / "app.py"),
            ),
        ),
        actual_cost_usd=0.2,
    )
    agent = SequenceAgent([proposal], estimate=0.2)
    budget = BudgetGuard(ledger, daily_limit_usd=0.1, monthly_limit_usd=0.1)
    loop = make_loop(
        ledger,
        git,
        runner,
        patches,
        agent,
        budget_guard=budget,
    )

    result = loop.run(request_for("app.py"))

    assert result.status == "blocked"
    assert result.stop_reason == "budget_denied"
    assert result.attempts == 0
    assert result.cost_usd == 0
    assert agent.propose_calls == 0


def test_wall_clock_limit_is_rechecked_before_dispatch(tmp_path):
    root, ledger, git, runner, patches = make_system(
        tmp_path, {"app.py": "def broken(\n"}
    )
    current = [datetime(2026, 8, 10, tzinfo=timezone.utc)]
    proposal = RepairProposal(
        hypothesis="unused proposal",
        files=(
            FilePatch(
                "app.py",
                "def repaired():\n    pass\n",
                expected_sha256=file_sha256(root / "app.py"),
            ),
        ),
    )
    agent = SequenceAgent(
        [proposal],
        on_estimate=lambda: current.__setitem__(0, current[0] + timedelta(seconds=2)),
    )
    loop = make_loop(
        ledger,
        git,
        runner,
        patches,
        agent,
        now=lambda: current[0],
    )

    result = loop.run(
        request_for("app.py", policy=RepairPolicy(max_wall_seconds=1))
    )

    assert result.status == "blocked"
    assert result.stop_reason == "wall_clock_limit"
    assert result.attempts == 0
    assert agent.propose_calls == 0


def test_wall_clock_expiry_during_proposal_stores_cost_but_does_not_patch(tmp_path):
    root, ledger, git, runner, patches = make_system(
        tmp_path, {"app.py": "def broken(\n"}
    )
    original = (root / "app.py").read_text(encoding="utf-8")
    current = [datetime(2026, 8, 10, tzinfo=timezone.utc)]
    proposal = RepairProposal(
        hypothesis="valid but returned after the deadline",
        files=(
            FilePatch(
                "app.py",
                "def repaired():\n    pass\n",
                expected_sha256=file_sha256(root / "app.py"),
            ),
        ),
        actual_cost_usd=0.1,
    )
    agent = SequenceAgent(
        [proposal],
        estimate=0.1,
        on_propose=lambda: current.__setitem__(0, current[0] + timedelta(seconds=2)),
    )
    budget = BudgetGuard(ledger, daily_limit_usd=1, monthly_limit_usd=1)
    loop = make_loop(
        ledger,
        git,
        runner,
        patches,
        agent,
        budget_guard=budget,
        now=lambda: current[0],
    )

    result = loop.run(
        request_for("app.py", policy=RepairPolicy(max_wall_seconds=1))
    )

    assert result.status == "blocked"
    assert result.stop_reason == "wall_clock_limit"
    assert result.cost_usd == pytest.approx(0.1)
    assert (root / "app.py").read_text(encoding="utf-8") == original
    assert ledger.get_repair_run(run_id="repair-run-1")["attempts"][0][
        "status"
    ] == "proposal_received"
    assert ledger.active_reservations(task_id="repair-task") == 0
    assert git.status().clean is True


def test_restart_resumes_durable_proposal_without_redispatch(tmp_path):
    root, ledger, git, runner, patches = make_system(
        tmp_path, {"app.py": "def broken(\n"}
    )
    proposal = RepairProposal(
        hypothesis="durable repair proposal",
        files=(
            FilePatch(
                "app.py",
                "def repaired():\n    return 1\n",
                expected_sha256=file_sha256(root / "app.py"),
            ),
        ),
    )
    unused_agent = SequenceAgent([proposal])
    loop = make_loop(ledger, git, runner, patches, unused_agent)
    request = request_for("app.py")
    request_sha = loop._request_sha(request)
    deadline = datetime.now(timezone.utc) + timedelta(minutes=5)
    ledger.claim_repair_run(
        run_id=request.run_id,
        task_id=request.task_id,
        actor=request.actor,
        objective=request.objective,
        idempotency_key=request.idempotency_key,
        request_sha256=request_sha,
        policy={
            "max_attempts": 3,
            "max_cost_usd": 1.0,
            "max_wall_seconds": 900.0,
            "max_identical_failures": 3,
            "max_identical_patches": 1,
            "max_no_progress_attempts": 2,
        },
        deadline_at=deadline.isoformat(),
    )
    _, context, failure_sha = loop._run_checks(request, sequence="initial")
    ledger.record_repair_initial_failure(request.run_id, failure_sha, context)
    attempt_id = f"{request.run_id}:attempt:1"
    ledger.claim_repair_attempt(
        attempt_id=attempt_id,
        run_id=request.run_id,
        attempt_number=1,
        agent_label=unused_agent.label,
        failure_before_sha256=failure_sha,
        estimated_cost_usd=0.0,
    )
    patch_request = PatchRequest(
        patch_id=f"{request.run_id}:attempt:1:patch",
        idempotency_key=f"{request.idempotency_key}:attempt:1:patch",
        actor=request.actor,
        reason=proposal.hypothesis,
        files=proposal.files,
        task_id=request.task_id,
    )
    patches.validate_request(patch_request)
    ledger.record_repair_proposal(
        attempt_id,
        proposal_sha256=loop._proposal_sha(proposal),
        proposal=loop._proposal_record(proposal),
        hypothesis=proposal.hypothesis,
        actual_cost_usd=0.0,
    )

    restarted_agent = SequenceAgent([proposal])
    restarted = make_loop(ledger, git, runner, patches, restarted_agent)
    result = restarted.run(request)

    assert result.status == "passed"
    assert result.checkpoint_id is not None
    assert restarted_agent.propose_calls == 0
    assert git.status().clean is True


def test_ambiguous_proposal_claim_requires_recovery_instead_of_redispatch(tmp_path):
    root, ledger, git, runner, patches = make_system(
        tmp_path, {"app.py": "def broken(\n"}
    )
    proposal = RepairProposal(
        hypothesis="must not be called",
        files=(
            FilePatch(
                "app.py",
                "def repaired():\n    pass\n",
                expected_sha256=file_sha256(root / "app.py"),
            ),
        ),
    )
    agent = SequenceAgent([proposal])
    loop = make_loop(ledger, git, runner, patches, agent)
    request = request_for("app.py")
    request_sha = loop._request_sha(request)
    ledger.claim_repair_run(
        run_id=request.run_id,
        task_id=request.task_id,
        actor=request.actor,
        objective=request.objective,
        idempotency_key=request.idempotency_key,
        request_sha256=request_sha,
        policy={
            "max_attempts": 3,
            "max_cost_usd": 1.0,
            "max_wall_seconds": 900.0,
            "max_identical_failures": 3,
            "max_identical_patches": 1,
            "max_no_progress_attempts": 2,
        },
        deadline_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    )
    _, context, failure_sha = loop._run_checks(request, sequence="initial")
    ledger.record_repair_initial_failure(request.run_id, failure_sha, context)
    ledger.claim_repair_attempt(
        attempt_id=f"{request.run_id}:attempt:1",
        run_id=request.run_id,
        attempt_number=1,
        agent_label=agent.label,
        failure_before_sha256=failure_sha,
        estimated_cost_usd=0.0,
    )

    result = loop.run(request)

    assert result.status == "recovery_required"
    assert result.stop_reason == "proposal_dispatch_unknown"
    assert agent.propose_calls == 0


def test_repair_records_use_relative_paths_and_portable_failure_context(tmp_path):
    root, ledger, git, runner, patches = make_system(
        tmp_path, {"app.py": "def broken(\n"}
    )
    proposal = RepairProposal(
        hypothesis="portable repair",
        files=(
            FilePatch(
                "app.py",
                "def repaired():\n    return True\n",
                expected_sha256=file_sha256(root / "app.py"),
            ),
        ),
    )
    result = make_loop(
        ledger, git, runner, patches, SequenceAgent([proposal])
    ).run(request_for("app.py"))
    assert result.status == "passed"

    with ledger.connect() as con:
        run = con.execute("SELECT * FROM repair_runs").fetchone()
        attempt = con.execute("SELECT * FROM repair_attempts").fetchone()
    serialized = json.dumps(
        {
            "context": run["failure_context_json"],
            "proposal": attempt["proposal_json"],
        }
    )
    assert str(root) not in serialized
    assert json.loads(attempt["proposal_json"])["files"][0]["path"] == "app.py"


def test_repair_policy_rejects_unbounded_or_invalid_limits():
    with pytest.raises(ValueError):
        RepairPolicy(max_attempts=0)
    with pytest.raises(ValueError):
        RepairPolicy(max_cost_usd=float("inf"))
    with pytest.raises(ValueError):
        RepairPolicy(max_wall_seconds=0)
