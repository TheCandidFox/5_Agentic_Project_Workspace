from __future__ import annotations

import json

import pytest

from ledger import Ledger
from patch_manager import (
    FilePatch,
    PatchConflict,
    PatchError,
    PatchIdempotencyConflict,
    PatchManager,
    PatchRequest,
    file_sha256,
)
from workspace_guard import WorkspaceGuard, WorkspaceViolation


def make_manager(tmp_path, **limits):
    root = tmp_path / "candidate"
    root.mkdir()
    ledger = Ledger(root / "ledger.db", project_root=root)
    return root, ledger, PatchManager(WorkspaceGuard(root), ledger, **limits)


def request_for(*files, key="patch-key", patch_id="patch-1"):
    return PatchRequest(
        patch_id=patch_id,
        idempotency_key=key,
        actor="test-agent",
        reason="controlled test repair",
        files=files,
        task_id="task-1",
    )


def test_apply_replace_and_create_records_hashes_and_restart_safe_backups(tmp_path):
    root, ledger, manager = make_manager(tmp_path)
    existing = root / "existing.py"
    existing.write_text("value = 1\n", encoding="utf-8")
    original_bytes = existing.read_bytes()
    before = file_sha256(existing)

    result = manager.apply(
        request_for(
            FilePatch("existing.py", "value = 2\n", expected_sha256=before),
            FilePatch("created.py", "created = True\n"),
        )
    )

    assert result.status == "applied"
    assert result.replayed is False
    assert existing.read_text(encoding="utf-8") == "value = 2\n"
    assert (root / "created.py").read_text(encoding="utf-8") == "created = True\n"
    stored = ledger.get_patch(idempotency_key="patch-key")
    assert stored["status"] == "applied"
    assert [item["path"] for item in stored["files"]] == [
        "created.py",
        "existing.py",
    ]
    replacement = next(
        item for item in stored["files"] if item["path"] == "existing.py"
    )
    assert replacement["backup_blob"] == original_bytes
    with ledger.connect() as con:
        event_payloads = [
            json.loads(row["payload_json"])
            for row in con.execute(
                "SELECT payload_json FROM events WHERE event_type LIKE 'patch_%'"
            ).fetchall()
        ]
    assert all("value =" not in json.dumps(payload) for payload in event_payloads)

    restarted = PatchManager(
        WorkspaceGuard(root),
        Ledger(root / "ledger.db", project_root=root),
    )
    rolled_back = restarted.rollback("patch-1")
    assert rolled_back.status == "rolled_back"
    assert existing.read_text(encoding="utf-8") == "value = 1\n"
    assert not (root / "created.py").exists()


def test_apply_replays_same_request_and_rejects_changed_idempotent_request(tmp_path):
    root, _, manager = make_manager(tmp_path)
    target = root / "app.py"
    target.write_text("old\n", encoding="utf-8")
    request = request_for(
        FilePatch("app.py", "new\n", expected_sha256=file_sha256(target))
    )

    first = manager.apply(request)
    replay = manager.apply(request)

    assert first.replayed is False
    assert replay.replayed is True
    with pytest.raises(PatchIdempotencyConflict):
        manager.apply(
            request_for(
                FilePatch(
                    "app.py",
                    "different\n",
                    expected_sha256=file_sha256(target),
                )
            )
        )


def test_preimage_mismatch_and_reserved_paths_fail_before_durable_claim(tmp_path):
    root, ledger, manager = make_manager(tmp_path)
    target = root / "app.py"
    target.write_text("unchanged\n", encoding="utf-8")

    with pytest.raises(PatchConflict, match="pre-image"):
        manager.apply(
            request_for(FilePatch("app.py", "changed\n", expected_sha256="0" * 64))
        )
    with pytest.raises(WorkspaceViolation):
        manager.apply(request_for(FilePatch("logs/runtime.py", "bad\n")))
    with pytest.raises(WorkspaceViolation):
        manager.apply(request_for(FilePatch(".env", "SECRET=bad\n")))

    assert target.read_text(encoding="utf-8") == "unchanged\n"
    with ledger.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM patch_transactions").fetchone()[0] == 0


def test_partial_apply_failure_restores_prior_files_and_records_terminal_failure(
    tmp_path, monkeypatch
):
    root, ledger, manager = make_manager(tmp_path)
    first = root / "first.py"
    second = root / "second.py"
    first.write_text("first-old\n", encoding="utf-8")
    second.write_text("second-old\n", encoding="utf-8")
    original_write = manager._atomic_write
    calls = 0

    def fail_second(path, content, mode):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated second write failure")
        original_write(path, content, mode)

    monkeypatch.setattr(manager, "_atomic_write", fail_second)
    with pytest.raises(PatchError, match="simulated second write failure"):
        manager.apply(
            request_for(
                FilePatch("first.py", "first-new\n", file_sha256(first)),
                FilePatch("second.py", "second-new\n", file_sha256(second)),
            )
        )

    assert first.read_text(encoding="utf-8") == "first-old\n"
    assert second.read_text(encoding="utf-8") == "second-old\n"
    assert ledger.get_patch(patch_id="patch-1")["status"] == "failed_rolled_back"


def test_rollback_refuses_to_overwrite_a_post_patch_external_change(tmp_path):
    root, ledger, manager = make_manager(tmp_path)
    target = root / "app.py"
    target.write_text("before\n", encoding="utf-8")
    manager.apply(
        request_for(FilePatch("app.py", "patched\n", file_sha256(target)))
    )
    target.write_text("external change\n", encoding="utf-8")

    with pytest.raises(PatchConflict, match="changed"):
        manager.rollback("patch-1")

    assert target.read_text(encoding="utf-8") == "external change\n"
    assert ledger.get_patch(patch_id="patch-1")["status"] == "applied"


def test_patch_limits_are_enforced_before_writes(tmp_path):
    root, ledger, manager = make_manager(
        tmp_path,
        max_file_bytes=5,
        max_total_bytes=8,
    )
    with pytest.raises(ValueError, match="exceeds 5"):
        manager.apply(request_for(FilePatch("too_large.py", "123456")))
    with pytest.raises(ValueError, match="exceeds 8"):
        manager.apply(
            request_for(
                FilePatch("one.py", "12345"),
                FilePatch("two.py", "6789"),
            )
        )
    assert not (root / "too_large.py").exists()
    with ledger.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM patch_transactions").fetchone()[0] == 0
