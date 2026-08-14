from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from git_checkpoint import (
    CheckpointRequest,
    GitCheckpointConflict,
    GitCheckpointManager,
)
from ledger import Ledger
from patch_manager import FilePatch, PatchManager, PatchRequest, file_sha256
from workspace_guard import WorkspaceGuard


GIT = os.environ.get("AI_LOOP_GIT_EXECUTABLE") or shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="Git is not installed")


def checkpoint_request(
    checkpoint_id,
    key,
    paths,
    *,
    patch_id=None,
    reason="test checkpoint",
):
    return CheckpointRequest(
        checkpoint_id=checkpoint_id,
        idempotency_key=key,
        actor="test-agent",
        reason=reason,
        paths=paths,
        patch_id=patch_id,
        task_id="task-1",
    )


def make_repository(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    (root / ".gitignore").write_text(
        "ledger.db\nledger.db-shm\nledger.db-wal\nlogs/\n",
        encoding="utf-8",
    )
    ledger = Ledger(root / "ledger.db", project_root=root)
    guard = WorkspaceGuard(root)
    manager = GitCheckpointManager(guard, ledger, git_executable=GIT)
    initialized = manager.initialize_repository(
        initial_branch="main",
        idempotency_key="git:init",
        task_id="task-1",
    )
    assert initialized.branch == "main"
    app = root / "app.py"
    app.write_text("value = 1\n", encoding="utf-8")
    baseline = manager.create_checkpoint(
        checkpoint_request(
            "checkpoint-baseline",
            "git:checkpoint:baseline",
            (".gitignore", "app.py"),
            reason="known good baseline",
        )
    )
    assert baseline.status == "committed"
    return root, ledger, guard, manager, app, baseline


def test_initialize_branch_checkpoint_and_replay_are_durable(tmp_path):
    root, ledger, _, manager, _, baseline = make_repository(tmp_path)

    assert baseline.base_commit is None
    assert len(baseline.commit_hash) in {40, 64}
    replay = manager.create_checkpoint(
        checkpoint_request(
            "checkpoint-baseline",
            "git:checkpoint:baseline",
            (".gitignore", "app.py"),
            reason="known good baseline",
        )
    )
    assert replay.replayed is True
    assert replay.commit_hash == baseline.commit_hash
    assert manager.status().clean is True
    with ledger.connect() as con:
        stored = con.execute("SELECT * FROM git_checkpoints").fetchone()
        command_rows = con.execute("SELECT request_json FROM commands").fetchall()
    assert json.loads(stored["paths_json"]) == [".gitignore", "app.py"]
    serialized = json.dumps([json.loads(row["request_json"]) for row in command_rows])
    assert str(root) not in serialized
    assert "AI Project OS" not in serialized
    assert "ai-project-os@localhost.invalid" not in serialized
    assert "logs/git_hooks_disabled" not in serialized


def test_initialize_creates_nested_repo_when_workspace_is_inside_parent_repo(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    subprocess.run(
        [GIT, "init", "--initial-branch", "main"],
        cwd=parent,
        check=True,
        capture_output=True,
        text=True,
    )
    root = parent / "candidate"
    root.mkdir()
    (root / ".gitignore").write_text(
        "ledger.db\nledger.db-shm\nledger.db-wal\nlogs/\n",
        encoding="utf-8",
    )
    ledger = Ledger(root / "ledger.db", project_root=root)
    manager = GitCheckpointManager(
        WorkspaceGuard(root),
        ledger,
        git_executable=GIT,
    )

    status = manager.initialize_repository(
        initial_branch="main",
        idempotency_key="git:init:nested",
    )

    assert status.branch == "main"
    reported = subprocess.run(
        [GIT, "rev-parse", "--show-toplevel"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert Path(reported).resolve() == root.resolve()


def test_patch_checkpoint_and_git_revert_restore_content_and_link_evidence(tmp_path):
    root, ledger, guard, git_manager, app, baseline = make_repository(tmp_path)
    patch_manager = PatchManager(guard, ledger)
    original = app.read_text(encoding="utf-8")
    patch = patch_manager.apply(
        PatchRequest(
            patch_id="patch-1",
            idempotency_key="patch:1",
            actor="test-agent",
            reason="repair fixture",
            task_id="task-1",
            files=(
                FilePatch(
                    "app.py",
                    "value = 2\n",
                    expected_sha256=file_sha256(app),
                ),
            ),
        )
    )
    assert patch.status == "applied"

    checkpoint = git_manager.create_checkpoint(
        checkpoint_request(
            "checkpoint-patch-1",
            "git:checkpoint:patch-1",
            ("app.py",),
            patch_id="patch-1",
            reason="checkpoint repaired fixture",
        )
    )
    assert checkpoint.base_commit == baseline.commit_hash
    assert checkpoint.status == "committed"
    assert git_manager.status().clean is True

    reverted = git_manager.revert_checkpoint("checkpoint-patch-1")
    assert reverted.status == "reverted"
    assert reverted.revert_commit_hash != checkpoint.commit_hash
    assert app.read_text(encoding="utf-8") == original
    assert ledger.get_patch(patch_id="patch-1")["status"] == "rolled_back"
    assert git_manager.status().clean is True


def test_checkpoint_refuses_unrelated_and_pre_staged_changes(tmp_path):
    root, ledger, _, manager, app, _ = make_repository(tmp_path)
    app.write_text("value = 2\n", encoding="utf-8")
    extra = root / "extra.py"
    extra.write_text("extra = True\n", encoding="utf-8")

    with pytest.raises(GitCheckpointConflict, match="unrelated changes"):
        manager.create_checkpoint(
            checkpoint_request(
                "checkpoint-unrelated",
                "git:checkpoint:unrelated",
                ("app.py",),
            )
        )
    assert ledger.get_git_checkpoint(
        idempotency_key="git:checkpoint:unrelated"
    ) is None

    extra.unlink()
    subprocess.run(
        [GIT, "add", "--", "app.py"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    with pytest.raises(GitCheckpointConflict, match="pre-staged"):
        manager.create_checkpoint(
            checkpoint_request(
                "checkpoint-staged",
                "git:checkpoint:staged",
                ("app.py",),
            )
        )


def test_checkpoint_bypasses_repository_hooks_and_can_create_safe_branch(tmp_path):
    root, _, _, manager, app, _ = make_repository(tmp_path)
    hooks = root / ".git" / "hooks"
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 91\n", encoding="utf-8", newline="\n")
    os.chmod(hook, 0o755)

    branch = manager.create_branch(
        "bootstrap/transaction-test",
        idempotency_key="git:branch:transaction-test",
        task_id="task-1",
    )
    assert branch.branch == "bootstrap/transaction-test"
    app.write_text("value = 3\n", encoding="utf-8")
    checkpoint = manager.create_checkpoint(
        checkpoint_request(
            "checkpoint-hook-safe",
            "git:checkpoint:hook-safe",
            ("app.py",),
        )
    )
    assert checkpoint.status == "committed"

    with pytest.raises(ValueError, match="unsafe"):
        manager.create_branch(
            "../escape",
            idempotency_key="git:branch:unsafe",
        )


def test_revert_refuses_out_of_order_or_dirty_history(tmp_path):
    root, _, _, manager, app, _ = make_repository(tmp_path)
    app.write_text("value = 2\n", encoding="utf-8")
    first = manager.create_checkpoint(
        checkpoint_request(
            "checkpoint-first",
            "git:checkpoint:first",
            ("app.py",),
        )
    )
    app.write_text("value = 3\n", encoding="utf-8")
    second = manager.create_checkpoint(
        checkpoint_request(
            "checkpoint-second",
            "git:checkpoint:second",
            ("app.py",),
        )
    )
    assert second.base_commit == first.commit_hash

    with pytest.raises(GitCheckpointConflict, match="current HEAD"):
        manager.revert_checkpoint("checkpoint-first")
    app.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(GitCheckpointConflict, match="clean worktree"):
        manager.revert_checkpoint("checkpoint-second")
