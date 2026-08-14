from __future__ import annotations

from pathlib import Path

import pytest

from project_contract import (
    AuthorityLevel,
    ProjectContractError,
    load_project_contract,
    parse_project_contract,
)
from workspace_guard import WorkspaceGuard


VALID_CONTRACT = """# Offline Checklist

## Goal

Create a small checklist.

## Acceptance Criteria

- `deliverable-exists`: The checklist exists.
- `required-sections`: Every requested section is present.
- `concise-length`: The result contains at most 1,000 words.

## Deliverables

- `outputs/checklist.md`: A Markdown checklist.

## Required Content

- Price
- Quality

## Constraints

- `offline-only`: Do not use the network.

## Execution Policy

- Profile: `offline-checklist-v1`
- Authority: `workspace-write`
- Budget USD: `0`
- Max tasks: `8`
- Max iterations: `16`
- Max no progress: `2`
- Max runtime seconds: `120`
"""


def test_parses_contract_and_normalizes_line_endings():
    lf = parse_project_contract(VALID_CONTRACT, source_path="project/sample.md")
    crlf = parse_project_contract(
        VALID_CONTRACT.replace("\n", "\r\n"),
        source_path="project/sample.md",
    )

    assert lf == crlf
    assert lf.contract_id.startswith("contract-")
    assert lf.policy.authority_ceiling == AuthorityLevel.WORKSPACE_WRITE
    assert lf.policy.budget_usd == 0
    assert lf.deliverables[0].path == "outputs/checklist.md"
    assert [item.criterion_key for item in lf.acceptance_criteria] == [
        "deliverable-exists",
        "required-sections",
        "concise-length",
    ]


def test_safe_defaults_apply_when_optional_policy_is_absent():
    markdown = VALID_CONTRACT.split("## Execution Policy", 1)[0]
    contract = parse_project_contract(markdown)

    assert contract.policy.profile == "offline-checklist-v1"
    assert contract.policy.authority_ceiling == AuthorityLevel.WORKSPACE_WRITE
    assert contract.policy.budget_usd == 0
    assert contract.policy.max_tasks == 8


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("## Goal", "## Objective", "unknown project-contract section"),
        ("## Deliverables", "## Goal\n\nDuplicate.\n\n## Deliverables", "duplicate"),
        ("`outputs/checklist.md`", "`../checklist.md`", "unsafe deliverable"),
        ("`outputs/checklist.md`", "`.env`", "below outputs"),
        ("`deliverable-exists`", "`Deliverable Exists`", "kebab-case"),
        ("offline-checklist-v1", "live-agent", "unsupported"),
        ("Max tasks: `8`", "Max tasks: `0`", "between 1 and 64"),
    ],
)
def test_rejects_malformed_or_unsafe_contracts(old: str, new: str, message: str):
    with pytest.raises(ProjectContractError, match=message):
        parse_project_contract(VALID_CONTRACT.replace(old, new, 1))


def test_rejects_missing_required_section_and_content_outside_sections():
    with pytest.raises(ProjectContractError, match="missing required"):
        parse_project_contract(VALID_CONTRACT.split("## Required Content", 1)[0])

    with pytest.raises(ProjectContractError, match="outside a named section"):
        parse_project_contract(VALID_CONTRACT.replace("# Offline Checklist", "# Offline Checklist\nstray"))


def test_rejects_duplicate_keys_html_and_code_fences():
    duplicate = VALID_CONTRACT.replace(
        "- `required-sections`: Every requested section is present.",
        "- `deliverable-exists`: Duplicate key.",
    )
    with pytest.raises(ProjectContractError, match="duplicate key"):
        parse_project_contract(duplicate)
    with pytest.raises(ProjectContractError, match="HTML"):
        parse_project_contract(VALID_CONTRACT.replace("Create a small checklist.", "<b>Goal</b>"))
    with pytest.raises(ProjectContractError, match="fenced code"):
        parse_project_contract(VALID_CONTRACT + "\n```text\nblocked\n```\n")


def test_load_contract_is_workspace_confined_and_utf8(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    project = root / "project"
    project.mkdir()
    goal = project / "goal.md"
    goal.write_text(VALID_CONTRACT, encoding="utf-8")
    guard = WorkspaceGuard(root)

    loaded = load_project_contract(guard, "project/goal.md")
    assert loaded.source_path == "project/goal.md"

    with pytest.raises(PermissionError):
        load_project_contract(guard, "../outside.md")

    invalid = project / "invalid.md"
    invalid.write_bytes(b"\xff\xfe")
    with pytest.raises(ProjectContractError, match="UTF-8"):
        load_project_contract(guard, "project/invalid.md")


def test_governed_live_profile_requires_positive_budget_authority_and_controls():
    live = (
        Path(__file__).resolve().parents[1]
        / "project"
        / "phase8_live_canary_goal.md"
    ).read_text(encoding="utf-8")
    contract = parse_project_contract(live, source_path="project/live.md")
    assert contract.policy.profile == "governed-live-v1"
    assert contract.policy.authority_ceiling == AuthorityLevel.LIVE_NETWORK
    assert contract.policy.budget_usd == 0.5

    with pytest.raises(ProjectContractError, match="live-network"):
        parse_project_contract(
            live.replace("Authority: `live-network`", "Authority: `workspace-write`")
        )
    with pytest.raises(ProjectContractError, match="greater than 0"):
        parse_project_contract(live.replace("Budget USD: `0.50`", "Budget USD: `0`"))
    with pytest.raises(ProjectContractError, match="missing required constraints"):
        parse_project_contract(
            live.replace(
                "- `declared-artifact-only`: Write only the declared Markdown deliverable.\n",
                "",
            )
        )
