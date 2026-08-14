from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from acceptance_truth import (
    AcceptanceEngine,
    AcceptanceOutcome,
    AcceptanceRequest,
    CalibrationReport,
    ClaimAssessment,
    CriterionAssessment,
    CriterionVerdict,
    EvidenceDisposition,
    EvidenceKind,
    EvidenceRef,
    TruthLabel,
    run_acceptance_calibration,
)
from bootstrap_acceptance import (
    BootstrapGateResult,
    FINAL_BOOTSTRAP_GATES,
    evaluate_final_bootstrap_gates,
    inspect_gate_evidence,
)
from ledger import Ledger
from research_provenance import (
    CitationSpec,
    ClaimSpec,
    ClaimType,
    FixtureDocument,
    FixtureRetriever,
    ResearchPolicy,
    ResearchRequest,
    ResearchRunner,
    RetrievalMode,
    SourceSpec,
    SourceType,
)
from run_bootstrap_bounded import BoundedBootstrapReport, run_bootstrap_bounded


RESEARCH_TABLES = frozenset(
    {"research_runs", "research_sources", "research_claims", "research_citations"}
)
ACCEPTANCE_TABLES = frozenset(
    {
        "acceptance_runs",
        "acceptance_evidence",
        "acceptance_claims",
        "acceptance_criteria",
        "acceptance_constraints",
    }
)


@dataclass(frozen=True)
class ResearchSmokeReport:
    passed: bool
    first_replayed: bool
    replay_replayed: bool
    retrieval_calls: int
    source_count: int
    claim_count: int
    acceptance_outcome: AcceptanceOutcome


@dataclass(frozen=True)
class Phase6BootstrapReport:
    bounded: BoundedBootstrapReport
    integrity: str
    migrations: tuple[str, ...]
    newly_applied_migrations: tuple[str, ...]
    research_tables_ready: bool
    acceptance_tables_ready: bool
    live_http_disabled_by_default: bool
    gate_manifest_ready: bool
    gate_manifest_issues: Mapping[str, tuple[str, ...]]
    status_only: bool
    research_smoke: ResearchSmokeReport | None = None
    calibration: CalibrationReport | None = None
    gates: tuple[BootstrapGateResult, ...] = ()

    @property
    def schema_ready(self) -> bool:
        return (
            "0004_research_provenance" in self.migrations
            and "0005_acceptance_truth" in self.migrations
            and self.research_tables_ready
            and self.acceptance_tables_ready
        )

    @property
    def passed(self) -> bool:
        base = (
            self.bounded.passed
            and self.integrity == "ok"
            and self.schema_ready
            and self.live_http_disabled_by_default
            and self.gate_manifest_ready
        )
        if self.status_only:
            return base
        return (
            base
            and self.research_smoke is not None
            and self.research_smoke.passed
            and self.calibration is not None
            and self.calibration.passed
            and len(self.gates) == 10
            and all(item.passed for item in self.gates)
        )


def _run_research_smoke(ledger: Ledger) -> ResearchSmokeReport:
    url = "https://phase6.example.test/authoritative-docs"
    excerpt = "Phase 6 authoritative fixtures preserve provenance and replay."
    fixture = FixtureDocument(
        url=url,
        title="Phase 6 authoritative documentation fixture",
        text=(
            f"{excerpt} The fixture is deterministic and performs no network request."
        ),
        retrieved_at="2026-08-14T12:00:00+00:00",
        content_type="text/markdown",
    )
    retriever = FixtureRetriever({url: fixture})
    request = ResearchRequest(
        run_id="phase6-authoritative-research-smoke-v1",
        task_id="phase6-bootstrap-acceptance",
        objective="Prove authoritative research provenance and durable replay offline.",
        idempotency_key="phase6:authoritative-research-smoke:v1",
        sources=(
            SourceSpec(
                source_key="phase6-authoritative-fixture",
                url=url,
                title=fixture.title,
                source_type=SourceType.OFFICIAL_DOCUMENTATION,
                is_primary=True,
                applicable_version="v0.3-phase6",
                applicable_date="2026-08-14",
            ),
        ),
        claims=(
            ClaimSpec(
                claim_key="fixture-provenance",
                statement="The Phase 6 fixture preserves provenance and replay.",
                claim_type=ClaimType.SOURCED_FACT,
                citations=(
                    CitationSpec(
                        source_key="phase6-authoritative-fixture",
                        excerpt=excerpt,
                    ),
                ),
            ),
        ),
    )
    runner = ResearchRunner(ledger, retriever, policy=ResearchPolicy())
    first = runner.run(request)
    calls_before_replay = retriever.call_count
    replayed = runner.run(request)

    source = first.sources[0]
    evidence = EvidenceRef(
        evidence_key="phase6-research-source",
        kind=EvidenceKind.PRIMARY_SOURCE,
        disposition=EvidenceDisposition.SUPPORTS,
        summary="The deterministic source capture contains the required excerpt.",
        reference=f"research-source:{source.source_id}",
        observed_at=source.retrieved_at,
    )
    acceptance = AcceptanceEngine(ledger).evaluate(
        AcceptanceRequest(
            evaluation_id="phase6-research-acceptance-smoke-v1",
            task_id="phase6-bootstrap-acceptance",
            objective="Accept the deterministic research-provenance fixture.",
            idempotency_key="phase6:research-acceptance-smoke:v1",
            evidence=(evidence,),
            claims=(
                ClaimAssessment(
                    claim_key="research-provenance",
                    statement="The research source has captured primary-source evidence.",
                    truth_label=TruthLabel.VERIFIED,
                    evidence_keys=(evidence.evidence_key,),
                ),
            ),
            criteria=(
                CriterionAssessment(
                    criterion_key="captured-provenance",
                    description="Research evidence is captured and source-linked.",
                    required=True,
                    verdict=CriterionVerdict.PASS,
                    evidence_keys=(evidence.evidence_key,),
                ),
            ),
        )
    )
    passed = (
        first.status == "completed"
        and first.retrieval_mode == RetrievalMode.OFFLINE_FIXTURE
        and first.cost_usd == 0
        and len(first.sources) == 1
        and len(first.claims) == 1
        and bool(source.content_sha256)
        and source.applicable_version == "v0.3-phase6"
        and source.applicable_date == "2026-08-14"
        and replayed.replayed
        and retriever.call_count == calls_before_replay
        and acceptance.outcome == AcceptanceOutcome.PASS
    )
    return ResearchSmokeReport(
        passed=passed,
        first_replayed=first.replayed,
        replay_replayed=replayed.replayed,
        retrieval_calls=retriever.call_count,
        source_count=len(first.sources),
        claim_count=len(first.claims),
        acceptance_outcome=acceptance.outcome,
    )


def run_bootstrap_phase6(
    *,
    project_root: str | Path,
    ledger_path: str | Path,
    status_only: bool = False,
    git_executable: str | Path | None = None,
    python_executable: str | Path | None = None,
    pytest_environment: Mapping[str, str] | None = None,
) -> Phase6BootstrapReport:
    root = Path(project_root).resolve()
    bounded = run_bootstrap_bounded(
        project_root=root,
        ledger_path=ledger_path,
        status_only=status_only,
        git_executable=git_executable,
        python_executable=python_executable,
        pytest_environment=pytest_environment,
    )
    ledger = Ledger(ledger_path, project_root=root)
    with ledger.connect() as con:
        tables = {
            str(row["name"])
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        research_run_columns = {
            str(row["name"])
            for row in con.execute("PRAGMA table_info(research_runs)").fetchall()
        }
        acceptance_run_columns = {
            str(row["name"])
            for row in con.execute("PRAGMA table_info(acceptance_runs)").fetchall()
        }
    research_ready = RESEARCH_TABLES.issubset(tables) and {
        "retrieval_mode",
        "request_count",
        "bytes_retrieved",
        "cost_usd",
    }.issubset(research_run_columns)
    acceptance_ready = ACCEPTANCE_TABLES.issubset(tables) and {
        "request_sha256",
        "outcome",
        "summary",
    }.issubset(acceptance_run_columns)
    default_policy = ResearchPolicy()
    live_disabled = (
        default_policy.allow_live_http is False and not default_policy.allowed_hosts
    )
    manifest_issues = inspect_gate_evidence(root)
    manifest_ready = len(FINAL_BOOTSTRAP_GATES) == 10 and not manifest_issues

    research_smoke = None
    calibration = None
    gates: tuple[BootstrapGateResult, ...] = ()
    schema_ready = (
        research_ready
        and acceptance_ready
        and "0004_research_provenance" in ledger.schema_migration_ids()
        and "0005_acceptance_truth" in ledger.schema_migration_ids()
    )
    if (
        not status_only
        and bounded.passed
        and ledger.integrity_check() == "ok"
        and schema_ready
        and live_disabled
        and manifest_ready
    ):
        research_smoke = _run_research_smoke(ledger)
        calibration = run_acceptance_calibration(
            ledger,
            key_prefix="phase6:final-bootstrap-calibration",
        )
        phase2 = bounded.transactional.phase2
        regression_passed = phase2 is not None and phase2.passed
        gates = evaluate_final_bootstrap_gates(
            project_root=root,
            regression_passed=regression_passed,
            schema_ready=schema_ready,
            calibration_passed=calibration.passed,
            research_passed=research_smoke.passed,
        )

    return Phase6BootstrapReport(
        bounded=bounded,
        integrity=ledger.integrity_check(),
        migrations=ledger.schema_migration_ids(),
        newly_applied_migrations=bounded.newly_applied_migrations,
        research_tables_ready=research_ready,
        acceptance_tables_ready=acceptance_ready,
        live_http_disabled_by_default=live_disabled,
        gate_manifest_ready=manifest_ready,
        gate_manifest_issues=manifest_issues,
        status_only=status_only,
        research_smoke=research_smoke,
        calibration=calibration,
        gates=gates,
    )


def print_report(report: Phase6BootstrapReport) -> None:
    mode = "status" if report.status_only else "verification"
    print(
        f"Phase 6 final bootstrap offline {mode} "
        "(no provider or network calls)"
    )
    print(
        f"[{'PASS' if report.integrity == 'ok' else 'FAIL'}] "
        f"SQLite integrity: {report.integrity}"
    )
    print(
        f"[{'PASS' if report.bounded.passed else 'FAIL'}] "
        "Phase 1-5 bounded-autonomy foundation"
    )
    migrations = ", ".join(report.migrations) or "none"
    newly = ", ".join(report.newly_applied_migrations) or "none"
    print(
        f"[{'PASS' if report.schema_ready else 'FAIL'}] "
        f"schema migrations: {migrations}; newly_applied={newly}"
    )
    print(
        f"[{'PASS' if report.research_tables_ready else 'FAIL'}] "
        "research provenance tables and telemetry columns"
    )
    print(
        f"[{'PASS' if report.acceptance_tables_ready else 'FAIL'}] "
        "acceptance/truth tables and outcome columns"
    )
    print(
        f"[{'PASS' if report.live_http_disabled_by_default else 'FAIL'}] "
        "live HTTP disabled by default with an empty host allowlist"
    )
    print(
        f"[{'PASS' if report.gate_manifest_ready else 'FAIL'}] "
        f"final bootstrap gate manifest: {len(FINAL_BOOTSTRAP_GATES)}/10 gates"
    )
    for gate_id, issues in sorted(report.gate_manifest_issues.items()):
        for issue in issues:
            print(f"  {gate_id}: {issue}")

    if report.research_smoke is not None:
        smoke = report.research_smoke
        print(
            f"[{'PASS' if smoke.passed else 'FAIL'}] "
            "offline research fixture/replay: "
            f"sources={smoke.source_count}; claims={smoke.claim_count}; "
            f"retrieval_calls={smoke.retrieval_calls}; "
            f"acceptance={smoke.acceptance_outcome.value}"
        )
    if report.calibration is not None:
        outcomes = ",".join(item.value for item in report.calibration.first_round)
        print(
            f"[{'PASS' if report.calibration.passed else 'FAIL'}] "
            f"truth calibration: {outcomes}; stable_repeat="
            f"{report.calibration.first_round == report.calibration.second_round}"
        )
    for index, gate in enumerate(report.gates, start=1):
        print(
            f"[{'PASS' if gate.passed else 'FAIL'}] "
            f"gate {index}/10 {gate.gate_id}: {gate.description}; {gate.summary}"
        )
    if report.status_only:
        print("[INFO] deterministic smoke, calibration, and mapped gates not executed")
    label = "status" if report.status_only else "result"
    print(f"Phase 6 bootstrap {label}: {'PASS' if report.passed else 'FAIL'}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the complete Phase 6 bootstrap offline."
    )
    parser.add_argument("--status-only", action="store_true")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).parent)
    parser.add_argument("--ledger", type=Path, default=Path("ledger.db"))
    parser.add_argument("--git-executable", type=Path)
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    ledger_path = args.ledger
    if not ledger_path.is_absolute():
        ledger_path = root / ledger_path
    environment = {}
    if os.environ.get("PYTHONPATH"):
        environment["PYTHONPATH"] = os.environ["PYTHONPATH"]
    try:
        report = run_bootstrap_phase6(
            project_root=root,
            ledger_path=ledger_path,
            status_only=args.status_only,
            git_executable=args.git_executable or shutil.which("git"),
            python_executable=sys.executable,
            pytest_environment=environment,
        )
        print_report(report)
        return 0 if report.passed else 1
    except Exception as exc:
        safe = f"{type(exc).__name__}: {exc}".replace(str(root), "<workspace>")
        print(
            "Phase 6 final bootstrap offline verification "
            "(no provider or network calls)"
        )
        print(f"[FAIL] {safe[:4_000]}")
        print("Phase 6 bootstrap result: FAIL")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
