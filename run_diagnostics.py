from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from ledger import Ledger, utc_now
from project_contract import load_project_contract
from workspace_guard import WorkspaceGuard


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


def _rows(connection, sql: str, parameters: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql, parameters).fetchall()]


def _segment(name: str, status: str, evidence: str) -> dict[str, str]:
    return {"name": name, "status": status, "evidence": evidence}


def _task_status(tasks: Mapping[str, Mapping[str, Any]], key: str) -> str:
    record = tasks.get(key)
    return str(record["status"]) if record is not None else "missing"


def _five_segments(
    run: Mapping[str, Any], tasks: Mapping[str, Mapping[str, Any]]
) -> tuple[list[dict[str, str]], str]:
    compose = _task_status(tasks, "compose-markdown")
    review = _task_status(tasks, "review-markdown")
    run_status = str(run["status"])
    outcome = str(run["outcome"] or "none")

    compose_state = (
        "complete" if compose == "completed" else "active" if compose == "running" else "blocked"
        if compose in {"failed", "blocked"}
        else "pending"
    )
    review_state = (
        "complete" if review == "completed" else "active" if review == "running" else "blocked"
        if review in {"failed", "blocked"}
        else "pending"
    )
    handoff_state = (
        "complete"
        if run_status == "completed" and outcome == "PASS"
        else "blocked"
        if run_status in {"failed", "blocked", "recovery_required"}
        else "active"
        if run_status == "paused"
        else "pending"
    )
    segments = [
        _segment("Govern", "complete", "Contract and policy were durably claimed."),
        _segment("Plan", "complete", f"Durable backlog contains {run['task_count']} tasks."),
        _segment("Compose", compose_state, f"compose-markdown status={compose}"),
        _segment("Verify", review_state, f"review-markdown status={review}"),
        _segment(
            "Handoff",
            handoff_state,
            f"project status={run_status}; outcome={outcome}",
        ),
    ]
    if run_status == "completed" and outcome == "PASS":
        relationship = "Acceptance passed; package the evidence and continuation record."
    elif review == "pending" and compose == "completed":
        relationship = "Resume the bounded reviewer attempt while preserving composer work."
    elif run_status == "recovery_required":
        relationship = "Resolve the ambiguous state before any redispatch or new paid call."
    elif run_status in {"failed", "blocked"}:
        relationship = "Use the recorded failure to choose repair, human decision, or stop."
    else:
        relationship = "Complete the active bounded task to advance governed acceptance."
    return segments, relationship


def build_diagnostic_bundle(
    ledger: Ledger,
    *,
    project_root: str | Path,
    run_id: str,
) -> dict[str, Any]:
    if not isinstance(run_id, str) or not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError("run_id contains unsupported characters")
    root = Path(project_root).resolve()
    with ledger.connect() as connection:
        row = connection.execute(
            "SELECT * FROM project_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown project run: {run_id}")
        run = dict(row)
        tasks = _rows(
            connection,
            """
            SELECT ordinal,task_key,title,kind,status,attempt_count,max_attempts,
                   actual_cost_usd,error,started_at,completed_at,updated_at
            FROM backlog_tasks WHERE run_id=? ORDER BY ordinal
            """,
            (run_id,),
        )
        dispatches = _rows(
            connection,
            """
            SELECT task_key,attempt_number,status,actual_cost_usd,error,
                   request_sha256,started_at,completed_at,updated_at
            FROM task_dispatches WHERE run_id=? ORDER BY started_at
            """,
            (run_id,),
        )
        provider_calls = _rows(
            connection,
            """
            SELECT task_key,attempt_number,execution_mode,provider,model,
                   prompt_template_version,prompt_sha256,response_schema,
                   max_output_tokens,quoted_cost_usd,status,provider_request_id,
                   response_sha256,input_tokens,output_tokens,estimated_cost_usd,
                   latency_ms,stop_reason,failure_kind,error,response_excerpt,
                   response_excerpt_sha256,started_at,completed_at,updated_at
            FROM provider_calls WHERE run_id=? ORDER BY started_at
            """,
            (run_id,),
        )
        artifacts = _rows(
            connection,
            """
            SELECT task_key,path,content_sha256,content_bytes,media_type,created_at
            FROM project_artifacts WHERE run_id=? ORDER BY path
            """,
            (run_id,),
        )
        events = _rows(
            connection,
            """
            SELECT event_type,payload_json,created_at FROM events
            WHERE task_id=? ORDER BY id
            """,
            (run_id,),
        )
        acceptance_id = run.get("acceptance_evaluation_id")
        acceptance: dict[str, Any] | None = None
        if acceptance_id:
            acceptance_row = connection.execute(
                "SELECT * FROM acceptance_runs WHERE evaluation_id=?",
                (acceptance_id,),
            ).fetchone()
            if acceptance_row is not None:
                acceptance = dict(acceptance_row)
                acceptance["criteria"] = _rows(
                    connection,
                    """
                    SELECT criterion_key,description,required,verdict,
                           evidence_keys_json,unresolved_action
                    FROM acceptance_criteria WHERE evaluation_id=?
                    ORDER BY criterion_key
                    """,
                    (acceptance_id,),
                )
                acceptance["constraints"] = _rows(
                    connection,
                    """
                    SELECT constraint_key,description,violated,evidence_keys_json
                    FROM acceptance_constraints WHERE evaluation_id=?
                    ORDER BY constraint_key
                    """,
                    (acceptance_id,),
                )

    task_map = {str(item["task_key"]): item for item in tasks}
    segments, relationship = _five_segments(run, task_map)
    try:
        contract = load_project_contract(
            WorkspaceGuard(root), str(run["contract_path"])
        )
        overall_goal = contract.goal
    except Exception:
        overall_goal = f"Complete governed project contract {run['contract_id']}."

    provider_cost = sum(
        float(item["estimated_cost_usd"] or 0) for item in provider_calls
    )
    project_cost = float(run["cost_usd"] or 0)
    failure_kinds = [
        str(item["failure_kind"])
        for item in provider_calls
        if item.get("failure_kind")
    ]
    recommendations: list[str] = []
    if str(run["status"]) == "completed" and str(run["outcome"]) == "PASS":
        recommendations.append(
            "No recovery action is required; preserve the accepted artifact and diagnostic bundle."
        )
    elif "response-truncated" in failure_kinds:
        recommendations.append(
            "Retry only the failed task if attempt, no-progress, time, and remaining-budget policy permit it."
        )
    if "transport-ambiguous" in failure_kinds or str(run["status"]) == "recovery_required":
        recommendations.append(
            "Require operator reconciliation; do not automatically redispatch an ambiguous call."
        )
    if abs(provider_cost - project_cost) > 1e-9:
        recommendations.append(
            "Reconcile project cost with failed-but-billable provider calls."
        )
    if not recommendations:
        recommendations.append("No recovery action is required; preserve the completed evidence.")

    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "run": {
            key: run[key]
            for key in (
                "run_id",
                "contract_id",
                "contract_path",
                "contract_sha256",
                "graph_sha256",
                "profile",
                "status",
                "outcome",
                "task_count",
                "completed_task_count",
                "iteration_count",
                "no_progress_count",
                "stop_reason",
                "error",
                "started_at",
                "deadline_at",
                "completed_at",
                "updated_at",
            )
        },
        "overall_goal": overall_goal,
        "segments": segments,
        "current_step_relationship": relationship,
        "cost": {
            "project_recorded_usd": project_cost,
            "provider_billable_usd": provider_cost,
            "difference_usd": round(provider_cost - project_cost, 12),
        },
        "tasks": tasks,
        "dispatches": dispatches,
        "provider_calls": provider_calls,
        "artifacts": artifacts,
        "acceptance": acceptance,
        "events": [
            {
                "event_type": item["event_type"],
                "payload": json.loads(str(item["payload_json"])),
                "created_at": item["created_at"],
            }
            for item in events
        ],
        "recommended_actions": recommendations,
    }


def write_diagnostic_bundle(
    guard: WorkspaceGuard,
    bundle: Mapping[str, Any],
    *,
    output_path: str | Path,
) -> tuple[str, str]:
    serialized = json.dumps(
        dict(bundle),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
    ) + "\n"
    if len(serialized.encode("utf-8")) > 1_000_000:
        raise ValueError("diagnostic bundle exceeds 1000000 bytes")
    authorized = guard.authorize_write(output_path, expect_directory=False)
    authorized.path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=".diagnostic-",
        dir=authorized.path.parent,
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, authorized.path)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return authorized.relative_path, digest


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a redacted project diagnostic bundle")
    parser.add_argument("--run-id")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--ledger", default="ledger.db")
    parser.add_argument("--output")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.project_root).resolve()
    ledger_path = Path(args.ledger)
    if not ledger_path.is_absolute():
        ledger_path = root / ledger_path
    ledger = Ledger(ledger_path, project_root=root)
    run_id = args.run_id
    if run_id is None:
        if not args.latest:
            raise SystemExit("supply --run-id or --latest")
        with ledger.connect() as connection:
            row = connection.execute(
                "SELECT run_id FROM project_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            raise SystemExit("no project run is available")
        run_id = str(row["run_id"])
    bundle = build_diagnostic_bundle(ledger, project_root=root, run_id=run_id)
    output = args.output or f"logs/diagnostics/{run_id}.json"
    path, digest = write_diagnostic_bundle(
        WorkspaceGuard(root), bundle, output_path=output
    )
    print(f"Diagnostic bundle: {path}")
    print(f"SHA-256: {digest}")
    print(
        "Cost: project=${project_recorded_usd:.6f}; "
        "provider=${provider_billable_usd:.6f}; difference=${difference_usd:.6f}".format(
            **bundle["cost"]
        )
    )
    for index, segment in enumerate(bundle["segments"], start=1):
        print(f"[{segment['status'].upper()}] {index}/5 {segment['name']}: {segment['evidence']}")
    print("Current step:", bundle["current_step_relationship"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
