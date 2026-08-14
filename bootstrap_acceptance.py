from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BootstrapGateDefinition:
    gate_id: str
    description: str
    evidence_nodes: tuple[str, ...]


@dataclass(frozen=True)
class BootstrapGateResult:
    gate_id: str
    description: str
    passed: bool
    summary: str
    evidence_nodes: tuple[str, ...]


FINAL_BOOTSTRAP_GATES: tuple[BootstrapGateDefinition, ...] = (
    BootstrapGateDefinition(
        gate_id="command-capture",
        description="passing and failing command capture",
        evidence_nodes=(
            "tests/test_command_runner.py::test_captures_success_stdout_and_metadata",
            "tests/test_command_runner.py::test_captures_nonzero_exit_and_stderr",
        ),
    ),
    BootstrapGateDefinition(
        gate_id="workspace-confinement",
        description="workspace confinement and traversal denial",
        evidence_nodes=(
            "tests/test_workspace_guard.py::test_rejects_lexical_parent_traversal",
            "tests/test_workspace_guard.py::test_rejects_absolute_path_outside_workspace",
        ),
    ),
    BootstrapGateDefinition(
        gate_id="patch-rollback",
        description="transactional patch and exact rollback",
        evidence_nodes=(
            "tests/test_patch_manager.py::test_apply_replace_and_create_records_hashes_and_restart_safe_backups",
            "tests/test_patch_manager.py::test_rollback_refuses_to_overwrite_a_post_patch_external_change",
        ),
    ),
    BootstrapGateDefinition(
        gate_id="tiny-repair",
        description="repair of a tiny broken Python fixture",
        evidence_nodes=(
            "tests/test_repair_loop.py::test_tiny_broken_fixture_is_repaired_validated_and_checkpointed",
        ),
    ),
    BootstrapGateDefinition(
        gate_id="bounded-failure",
        description="bounded failure on an unfixable fixture",
        evidence_nodes=(
            "tests/test_repair_loop.py::test_unfixable_attempt_is_rolled_back_and_stops_at_attempt_limit",
        ),
    ),
    BootstrapGateDefinition(
        gate_id="git-checkpoint",
        description="scoped local Git checkpoint",
        evidence_nodes=(
            "tests/test_git_checkpoint.py::test_initialize_branch_checkpoint_and_replay_are_durable",
            "tests/test_git_checkpoint.py::test_patch_checkpoint_and_git_revert_restore_content_and_link_evidence",
        ),
    ),
    BootstrapGateDefinition(
        gate_id="budget-denial",
        description="budget denial before repair-agent dispatch",
        evidence_nodes=(
            "tests/test_repair_loop.py::test_budget_denial_happens_before_agent_dispatch",
        ),
    ),
    BootstrapGateDefinition(
        gate_id="restart-resume",
        description="durable restart/resume without duplicate dispatch",
        evidence_nodes=(
            "tests/test_repair_loop.py::test_restart_resumes_durable_proposal_without_redispatch",
            "tests/test_research_provenance.py::test_offline_research_resumes_from_a_durable_source_without_refetch",
        ),
    ),
    BootstrapGateDefinition(
        gate_id="truth-calibration",
        description="stable acceptance and truth calibration",
        evidence_nodes=(
            "tests/test_acceptance_truth.py::test_five_case_calibration_is_stable_and_bounded",
        ),
    ),
    BootstrapGateDefinition(
        gate_id="research-provenance",
        description="authoritative research capture with provenance and replay",
        evidence_nodes=(
            "tests/test_research_provenance.py::test_fixture_research_records_provenance_telemetry_and_replays",
            "tests/test_research_provenance.py::test_live_http_is_disabled_before_dns_or_transport_dispatch",
        ),
    ),
)


def inspect_gate_evidence(project_root: str | Path) -> dict[str, tuple[str, ...]]:
    root = Path(project_root).resolve()
    definitions = FINAL_BOOTSTRAP_GATES
    issues: dict[str, list[str]] = {item.gate_id: [] for item in definitions}
    gate_ids = [item.gate_id for item in definitions]
    if len(definitions) != 10:
        issues.setdefault("manifest", []).append(
            f"expected exactly 10 gate definitions, found {len(definitions)}"
        )
    if len(set(gate_ids)) != len(gate_ids):
        issues.setdefault("manifest", []).append("gate identifiers are not unique")

    parsed_files: dict[Path, set[str] | str] = {}
    for definition in definitions:
        if not definition.evidence_nodes:
            issues[definition.gate_id].append("gate has no evidence node")
            continue
        for node in definition.evidence_nodes:
            try:
                path_text, function_name = node.split("::", 1)
            except ValueError:
                issues[definition.gate_id].append(
                    f"invalid evidence node format: {node}"
                )
                continue
            path = (root / path_text).resolve()
            try:
                path.relative_to(root)
            except ValueError:
                issues[definition.gate_id].append(
                    f"evidence path escapes project: {path_text}"
                )
                continue
            if path not in parsed_files:
                if not path.is_file():
                    parsed_files[path] = "file is missing"
                else:
                    try:
                        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                    except (OSError, UnicodeError, SyntaxError) as exc:
                        parsed_files[path] = f"cannot parse evidence file: {type(exc).__name__}"
                    else:
                        parsed_files[path] = {
                            item.name
                            for item in tree.body
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        }
            names = parsed_files[path]
            if isinstance(names, str):
                issues[definition.gate_id].append(f"{path_text}: {names}")
            elif function_name not in names:
                issues[definition.gate_id].append(
                    f"evidence function is missing: {node}"
                )
    return {
        gate_id: tuple(values)
        for gate_id, values in issues.items()
        if values
    }


def evaluate_final_bootstrap_gates(
    *,
    project_root: str | Path,
    regression_passed: bool,
    schema_ready: bool,
    calibration_passed: bool,
    research_passed: bool,
) -> tuple[BootstrapGateResult, ...]:
    issues = inspect_gate_evidence(project_root)
    results: list[BootstrapGateResult] = []
    for definition in FINAL_BOOTSTRAP_GATES:
        gate_issues = issues.get(definition.gate_id, ())
        capability_passed = True
        if definition.gate_id == "truth-calibration":
            capability_passed = calibration_passed
        elif definition.gate_id == "research-provenance":
            capability_passed = research_passed
        passed = (
            regression_passed
            and schema_ready
            and capability_passed
            and not gate_issues
            and "manifest" not in issues
        )
        if gate_issues:
            summary = "; ".join(gate_issues)
        elif not schema_ready:
            summary = "required durable schema is not ready"
        elif not regression_passed:
            summary = "complete offline regression suite did not pass"
        elif not capability_passed:
            summary = "capability-specific deterministic acceptance did not pass"
        else:
            summary = "mapped evidence passed in the complete offline suite"
        results.append(
            BootstrapGateResult(
                gate_id=definition.gate_id,
                description=definition.description,
                passed=passed,
                summary=summary,
                evidence_nodes=definition.evidence_nodes,
            )
        )
    return tuple(results)
