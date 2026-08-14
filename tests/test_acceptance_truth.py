from __future__ import annotations

from dataclasses import replace

import pytest

from acceptance_truth import (
    AcceptanceEngine,
    AcceptanceError,
    AcceptanceIdempotencyConflict,
    AcceptanceOutcome,
    AcceptanceRequest,
    ClaimAssessment,
    ConstraintFinding,
    CriterionAssessment,
    CriterionVerdict,
    EvidenceDisposition,
    EvidenceKind,
    EvidenceRef,
    TruthLabel,
    run_acceptance_calibration,
)
from ledger import Ledger


def supporting_evidence(
    *,
    key="tests-pass",
    kind=EvidenceKind.DETERMINISTIC_VALIDATION,
    reference="validation:tests-pass",
):
    return EvidenceRef(
        evidence_key=key,
        kind=kind,
        disposition=EvidenceDisposition.SUPPORTS,
        summary="The required deterministic check passed.",
        reference=reference,
        observed_at="2026-08-14T12:00:00+00:00",
    )


def passing_request(
    *, evaluation_id="evaluation-1", idempotency_key="acceptance:key:v1"
):
    evidence = supporting_evidence()
    return AcceptanceRequest(
        evaluation_id=evaluation_id,
        task_id="task-acceptance",
        objective="Accept a known-good deterministic deliverable.",
        idempotency_key=idempotency_key,
        evidence=(evidence,),
        claims=(
            ClaimAssessment(
                claim_key="test-result",
                statement="The required tests passed.",
                truth_label=TruthLabel.VERIFIED,
                evidence_keys=(evidence.evidence_key,),
            ),
        ),
        criteria=(
            CriterionAssessment(
                criterion_key="required-tests",
                description="The required tests pass.",
                required=True,
                verdict=CriterionVerdict.PASS,
                evidence_keys=(evidence.evidence_key,),
            ),
        ),
    )


def test_acceptance_pass_is_durable_and_idempotently_replayed(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db", project_root=tmp_path)
    engine = AcceptanceEngine(ledger)
    request = passing_request()

    first = engine.evaluate(request)
    replayed = engine.evaluate(replace(request, evaluation_id="ignored-replay-id"))

    assert first.outcome == AcceptanceOutcome.PASS
    assert first.replayed is False
    assert first.summary.startswith("PASS: 1/1")
    assert first.claims[0].truth_label == TruthLabel.VERIFIED
    assert replayed.evaluation_id == request.evaluation_id
    assert replayed.replayed is True
    with ledger.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM acceptance_runs").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM acceptance_evidence").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM acceptance_claims").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM acceptance_criteria").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM acceptance_constraints").fetchone()[0] == 0
        payloads = [
            row[0]
            for row in con.execute(
                "SELECT payload_json FROM events WHERE event_type LIKE 'acceptance_%'"
            ).fetchall()
        ]
    assert payloads
    assert str(tmp_path) not in "".join(payloads)
    assert "0005_acceptance_truth" in ledger.schema_migration_ids()


def test_changed_acceptance_request_conflicts_with_durable_key(tmp_path):
    engine = AcceptanceEngine(Ledger(tmp_path / "ledger.db"))
    request = passing_request()
    engine.evaluate(request)

    with pytest.raises(AcceptanceIdempotencyConflict):
        engine.evaluate(replace(request, objective="Different semantics"))


def test_truth_labels_require_structurally_eligible_evidence(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    engine = AcceptanceEngine(ledger)
    semantic = supporting_evidence(
        key="review",
        kind=EvidenceKind.SEMANTIC_REVIEW,
        reference="review:model-agreement",
    )
    weak_verified = replace(
        passing_request(evaluation_id="weak", idempotency_key="weak:v1"),
        evidence=(semantic,),
        claims=(
            ClaimAssessment(
                claim_key="agreement",
                statement="Two models agreed.",
                truth_label=TruthLabel.VERIFIED,
                evidence_keys=("review",),
            ),
        ),
        criteria=(
            CriterionAssessment(
                criterion_key="reviewed",
                description="Semantic review supports the output.",
                required=True,
                verdict=CriterionVerdict.PASS,
                evidence_keys=("review",),
            ),
        ),
    )
    with pytest.raises(AcceptanceError, match="lacks uncontradicted strong evidence"):
        engine.evaluate(weak_verified)

    contradicting = EvidenceRef(
        evidence_key="contradiction",
        kind=EvidenceKind.PRIMARY_SOURCE,
        disposition=EvidenceDisposition.CONTRADICTS,
        summary="A primary source contradicts the statement.",
        reference="source:contradiction",
    )
    disputed_without_support = replace(
        weak_verified,
        evaluation_id="disputed-invalid",
        idempotency_key="disputed-invalid:v1",
        evidence=(contradicting,),
        claims=(
            ClaimAssessment(
                claim_key="invalid-dispute",
                statement="The statement is disputed.",
                truth_label=TruthLabel.DISPUTED,
                evidence_keys=("contradiction",),
                rationale="Only contradicting evidence is present.",
            ),
        ),
        criteria=(
            CriterionAssessment(
                criterion_key="unresolved",
                description="The claim is unresolved.",
                required=True,
                verdict=CriterionVerdict.UNKNOWN,
                evidence_keys=("contradiction",),
            ),
        ),
    )
    with pytest.raises(AcceptanceError, match="requires support and contradiction"):
        engine.evaluate(disputed_without_support)

    with pytest.raises(ValueError, match="INFERRED"):
        ClaimAssessment(
            claim_key="inference",
            statement="An inferred statement.",
            truth_label=TruthLabel.INFERRED,
        )


def test_acceptance_aggregation_prioritizes_constraints_repair_and_unresolved(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db")
    engine = AcceptanceEngine(ledger)
    support = supporting_evidence()
    failure = EvidenceRef(
        evidence_key="failed-check",
        kind=EvidenceKind.DETERMINISTIC_VALIDATION,
        disposition=EvidenceDisposition.CONTRADICTS,
        summary="The required check failed.",
        reference="validation:failed-check",
    )

    repair = AcceptanceRequest(
        evaluation_id="repair",
        task_id="task",
        objective="Repair an incomplete deliverable.",
        idempotency_key="repair:v1",
        evidence=(failure,),
        claims=(),
        criteria=(
            CriterionAssessment(
                criterion_key="failed",
                description="The required check passes.",
                required=True,
                verdict=CriterionVerdict.FAIL,
                evidence_keys=("failed-check",),
            ),
        ),
    )
    assert engine.evaluate(repair).outcome == AcceptanceOutcome.REPAIR

    deferred = AcceptanceRequest(
        evaluation_id="defer",
        task_id="task",
        objective="Defer an unresolved criterion.",
        idempotency_key="defer:v1",
        evidence=(),
        claims=(
            ClaimAssessment(
                claim_key="unknown",
                statement="The result is unknown.",
                truth_label=TruthLabel.UNKNOWN,
                rationale="The required evidence is unavailable.",
            ),
        ),
        criteria=(
            CriterionAssessment(
                criterion_key="unknown",
                description="A value is established.",
                required=True,
                verdict=CriterionVerdict.UNKNOWN,
                unresolved_action=AcceptanceOutcome.DEFER,
            ),
        ),
    )
    assert engine.evaluate(deferred).outcome == AcceptanceOutcome.DEFER

    blocked = replace(
        passing_request(evaluation_id="blocked", idempotency_key="blocked:v1"),
        constraints=(
            ConstraintFinding(
                constraint_key="hard-boundary",
                description="Do not cross the hard boundary.",
                violated=True,
                evidence_keys=(support.evidence_key,),
            ),
        ),
    )
    assert engine.evaluate(blocked).outcome == AcceptanceOutcome.BLOCK


def test_acceptance_rejects_unknown_evidence_and_unsupported_criterion(tmp_path):
    with pytest.raises(ValueError, match="unknown evidence"):
        replace(
            passing_request(),
            claims=(
                ClaimAssessment(
                    claim_key="unknown-ref",
                    statement="References absent evidence.",
                    truth_label=TruthLabel.SUPPORTED,
                    evidence_keys=("missing",),
                ),
            ),
        )

    engine = AcceptanceEngine(Ledger(tmp_path / "ledger.db"))
    unsupported = replace(
        passing_request(),
        evidence=(),
        claims=(),
        criteria=(
            CriterionAssessment(
                criterion_key="unsupported-pass",
                description="A pass without evidence.",
                required=True,
                verdict=CriterionVerdict.PASS,
            ),
        ),
    )
    with pytest.raises(AcceptanceError, match="requires uncontradicted support"):
        engine.evaluate(unsupported)


def test_five_case_calibration_is_stable_and_bounded(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db", project_root=tmp_path)

    first = run_acceptance_calibration(ledger, key_prefix="calibration:test")
    replayed = run_acceptance_calibration(ledger, key_prefix="calibration:test")

    assert first.passed is True
    assert first.expected == (
        AcceptanceOutcome.PASS,
        AcceptanceOutcome.REPAIR,
        AcceptanceOutcome.PASS,
        AcceptanceOutcome.BLOCK,
        AcceptanceOutcome.HUMAN_DECISION,
    )
    assert first.first_round == first.second_round
    assert replayed.passed is True
    with ledger.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM acceptance_runs").fetchone()[0] == 10
