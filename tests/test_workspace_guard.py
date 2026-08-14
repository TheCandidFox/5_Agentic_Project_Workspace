from __future__ import annotations

import os
from pathlib import Path

import pytest

from workspace_guard import AccessMode, WorkspaceGuard, WorkspaceViolation


def make_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "candidate"
    root.mkdir()
    (root / "docs").mkdir()
    (root / "docs" / "readme.md").write_text("safe", encoding="utf-8")
    return root


def test_allows_existing_read_and_portable_relative_result(tmp_path):
    root = make_workspace(tmp_path)
    guard = WorkspaceGuard(root)

    authorized = guard.authorize_read("docs/readme.md", expect_directory=False)

    assert authorized.path == root / "docs" / "readme.md"
    assert authorized.relative_path == "docs/readme.md"
    assert authorized.access == AccessMode.READ


def test_allows_new_write_target_inside_workspace(tmp_path):
    root = make_workspace(tmp_path)
    guard = WorkspaceGuard(root)

    authorized = guard.authorize_write("generated/new/result.json")

    assert authorized.path == root / "generated" / "new" / "result.json"
    assert authorized.relative_path == "generated/new/result.json"


@pytest.mark.parametrize("value", ["../escape.txt", "docs/../../escape.txt"])
def test_rejects_lexical_parent_traversal(tmp_path, value):
    guard = WorkspaceGuard(make_workspace(tmp_path))

    with pytest.raises(WorkspaceViolation, match="parent traversal"):
        guard.authorize_write(value)


def test_rejects_absolute_path_outside_workspace(tmp_path):
    root = make_workspace(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    guard = WorkspaceGuard(root)

    with pytest.raises(WorkspaceViolation, match="outside workspace"):
        guard.authorize_read(outside)


@pytest.mark.parametrize(
    "value, message",
    [
        ("safe.txt:secret-stream", "alternate data streams"),
        ("NUL.txt", "reserved device name"),
        ("docs/trailing. ", "unsafe trailing character"),
    ],
)
def test_rejects_windows_path_edge_cases(tmp_path, value, message):
    guard = WorkspaceGuard(make_workspace(tmp_path))

    with pytest.raises(WorkspaceViolation, match=message):
        guard.authorize_write(value)


@pytest.mark.parametrize(
    "name",
    [".env", ".ENV", ".env.local", ".env.production", "secrets.env"],
)
def test_protects_secret_names_for_read_and_write(tmp_path, name):
    root = make_workspace(tmp_path)
    (root / name).write_text("secret", encoding="utf-8")
    guard = WorkspaceGuard(root)

    with pytest.raises(WorkspaceViolation, match="protected workspace path"):
        guard.authorize_read(name)
    with pytest.raises(WorkspaceViolation, match="protected workspace path"):
        guard.authorize_write(name)


def test_env_example_is_not_treated_as_secret_file(tmp_path):
    root = make_workspace(tmp_path)
    example = root / ".env.example"
    example.write_text("placeholder", encoding="utf-8")
    guard = WorkspaceGuard(root)

    assert guard.authorize_read(".env.example").path == example


def test_protects_git_subtree(tmp_path):
    root = make_workspace(tmp_path)
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("config", encoding="utf-8")
    guard = WorkspaceGuard(root)

    with pytest.raises(WorkspaceViolation, match="protected workspace path"):
        guard.authorize_read(".git/config")


def test_immutable_path_is_readable_but_not_writable(tmp_path):
    root = make_workspace(tmp_path)
    reference = root / "docs" / "frozen"
    reference.mkdir()
    artifact = reference / "baseline.md"
    artifact.write_text("baseline", encoding="utf-8")
    guard = WorkspaceGuard(root, immutable_paths=("docs/frozen",))

    assert guard.authorize_read("docs/frozen/baseline.md").path == artifact
    with pytest.raises(WorkspaceViolation, match="immutable workspace path"):
        guard.authorize_write("docs/frozen/baseline.md")
    with pytest.raises(WorkspaceViolation, match="immutable workspace path"):
        guard.authorize_write("docs/frozen/new.md")


def test_missing_read_is_rejected(tmp_path):
    guard = WorkspaceGuard(make_workspace(tmp_path))

    with pytest.raises(FileNotFoundError):
        guard.authorize_read("missing.txt")


def test_directory_and_file_expectations_are_enforced(tmp_path):
    root = make_workspace(tmp_path)
    guard = WorkspaceGuard(root)

    with pytest.raises(NotADirectoryError):
        guard.authorize_directory("docs/readme.md")
    with pytest.raises(IsADirectoryError):
        guard.authorize_read("docs", expect_directory=False)


def test_workspace_root_must_exist_and_be_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        WorkspaceGuard(tmp_path / "missing")

    file_path = tmp_path / "file.txt"
    file_path.write_text("not a directory", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        WorkspaceGuard(file_path)


def test_rejects_symlink_or_junction_escape_when_supported(tmp_path):
    root = make_workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    link = root / "linked-outside"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"link creation is unavailable: {exc}")

    guard = WorkspaceGuard(root)
    with pytest.raises(WorkspaceViolation, match="outside workspace"):
        guard.authorize_read("linked-outside/secret.txt")
