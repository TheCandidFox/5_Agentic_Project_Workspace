from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from ledger import Ledger
from revision_contracts import RevisionContractError, parse_review, parse_revision
from revision_cycle import RevisionCycle, RevisionPolicy


def review_json(artifact: str, verdict="PASS", finding=None):
    criteria = {"complete": verdict}
    return json.dumps({"schema_version":"phase10-review-v1","artifact_sha256":hashlib.sha256(artifact.encode()).hexdigest(),"overall_verdict":verdict,"findings":[] if finding is None else [finding],"criterion_results":criteria,"summary":"bounded summary","recommended_next_action":"continue safely"}, separators=(",", ":"))


def repair_finding(fid="f-1"):
    return {"finding_id":fid,"criterion_key":"complete","verdict":"REPAIR","severity":"medium","evidence_refs":["artifact:line-1"],"observed":"A required section is absent.","expected":"The required section exists.","proposed_action":"Add the missing section.","repair_eligibility":"eligible","human_decision_reason":None}


@pytest.fixture
def cycle(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db", tmp_path)
    return RevisionCycle(ledger, tmp_path), ledger, tmp_path


def test_migration_is_idempotent_and_constrained(tmp_path):
    ledger = Ledger(tmp_path / "ledger.db", tmp_path)
    assert ledger.schema_migration_ids()[-1] == "0009_bounded_revision_cycle"
    again = Ledger(tmp_path / "ledger.db", tmp_path)
    assert again.applied_schema_migrations == ()
    with pytest.raises(sqlite3.IntegrityError), again.connect() as con:
        con.execute("INSERT INTO revision_runs(run_id,contract_sha256,overall_goal,logical_path,state,policy_json,created_at,updated_at) VALUES('bad','x','g','o','INVALID','{}','n','n')")


def test_strict_review_schema_and_contradictions():
    artifact = "# A"
    good = parse_review(review_json(artifact), ("complete",), hashlib.sha256(artifact.encode()).hexdigest())
    assert good.overall_verdict == "PASS"
    with pytest.raises(RevisionContractError):
        parse_review(review_json(artifact) + " trailing", ("complete",), hashlib.sha256(artifact.encode()).hexdigest())
    bad = json.loads(review_json(artifact)); bad["unknown"] = 1
    with pytest.raises(RevisionContractError): parse_review(json.dumps(bad), ("complete",), hashlib.sha256(artifact.encode()).hexdigest())
    contradictory = repair_finding(); contradictory["repair_eligibility"] = "ineligible"
    with pytest.raises(RevisionContractError): parse_review(review_json(artifact, "REPAIR", contradictory), ("complete",), hashlib.sha256(artifact.encode()).hexdigest())


def test_revision_proposal_cannot_expand_targets():
    payload = {"schema_version":"phase10-revision-v1","baseline_sha256":"a"*64,"finding_set_sha256":"b"*64,"target_finding_ids":["f-2"],"rationale":"repair","candidate_markdown":"# Fixed","claimed_resolved":["f-2"],"deferred":[]}
    with pytest.raises(RevisionContractError): parse_revision(json.dumps(payload), baseline_sha256="a"*64, finding_set_sha256="b"*64, eligible_ids=("f-1",))


def test_pass_accepts_and_replay_is_zero_write(cycle):
    engine, ledger, root = cycle
    baseline = "# Baseline\n"
    version = engine.start(run_id="r1", contract_sha256="a"*64, goal="finish", logical_path="outputs/a.md", baseline=baseline)
    assert engine.start(run_id="r1", contract_sha256="a"*64, goal="finish", logical_path="outputs/a.md", baseline=baseline) == version
    engine.claim_dispatch("r1", role="review", ordinal=1, quoted_cost_usd=0, idempotency_key="r1-review")
    review = parse_review(review_json(baseline), ("complete",), hashlib.sha256(baseline.encode()).hexdigest())
    assert engine.record_review("r1", "e1", version, review) == "ACCEPTED"
    before = (root / "outputs/a.md").read_bytes()
    assert engine.status("r1")["next_action"] == "none"
    assert (root / "outputs/a.md").read_bytes() == before


def test_repair_candidate_is_immutable_until_acceptance(cycle):
    engine, ledger, root = cycle
    baseline = "# Baseline\n"
    version = engine.start(run_id="r2", contract_sha256="a"*64, goal="repair", logical_path="outputs/a.md", baseline=baseline)
    engine.claim_dispatch("r2", role="review", ordinal=1, quoted_cost_usd=0, idempotency_key="review")
    review = parse_review(review_json(baseline, "REPAIR", repair_finding()), ("complete",), hashlib.sha256(baseline.encode()).hexdigest())
    assert engine.record_review("r2", "e1", version, review) == "REVISION_PLANNED"
    engine.claim_dispatch("r2", role="revision", ordinal=1, quoted_cost_usd=0, idempotency_key="revise")
    candidate = engine.preserve_candidate("r2", 1, version, "# Baseline\n\n## Complete\n")
    assert (root / "outputs/a.md").read_text() == baseline
    engine.accept_candidate("r2", candidate)
    assert "## Complete" in (root / "outputs/a.md").read_text()
    with ledger.connect() as con:
        statuses = {r["status"] for r in con.execute("SELECT status FROM artifact_versions WHERE run_id='r2'")}
    assert statuses == {"accepted", "superseded"}


def test_identical_candidate_stops_without_overwrite(cycle):
    engine, _, root = cycle
    baseline = "# Baseline\n"
    version = engine.start(run_id="r3", contract_sha256="a"*64, goal="repair", logical_path="outputs/a.md", baseline=baseline)
    engine.claim_dispatch("r3", role="review", ordinal=1, quoted_cost_usd=0, idempotency_key="review")
    review = parse_review(review_json(baseline, "REPAIR", repair_finding()), ("complete",), hashlib.sha256(baseline.encode()).hexdigest())
    engine.record_review("r3", "e1", version, review)
    engine.claim_dispatch("r3", role="revision", ordinal=1, quoted_cost_usd=0, idempotency_key="revise")
    assert engine.preserve_candidate("r3", 1, version, baseline) == "BOUNDED_STOP"
    assert (root / "outputs/a.md").read_text() == baseline


def test_ambiguous_dispatch_gates_and_capsule_single_consumer(cycle):
    engine, _, _ = cycle
    engine.start(run_id="r4", contract_sha256="a"*64, goal="safe", logical_path="outputs/a.md", baseline="# A")
    engine.claim_dispatch("r4", role="review", ordinal=1, quoted_cost_usd=0, idempotency_key="review")
    engine.mark_ambiguous_dispatch("r4", "review")
    status = engine.status("r4")
    assert status["state"] == "HUMAN_DECISION_REQUIRED"
    engine.consume_capsule(status["capsule_id"], "worker-1")
    engine.consume_capsule(status["capsule_id"], "worker-1")
    with pytest.raises(RuntimeError): engine.consume_capsule(status["capsule_id"], "worker-2")


def test_budget_denial_happens_before_dispatch(cycle):
    engine, ledger, _ = cycle
    engine.start(run_id="r5", contract_sha256="a"*64, goal="bounded", logical_path="outputs/a.md", baseline="# A", policy=RevisionPolicy(cost_ceiling_usd=0))
    assert engine.claim_dispatch("r5", role="review", ordinal=1, quoted_cost_usd=.01, idempotency_key="paid") == "BOUNDED_STOP"
    assert engine.status("r5")["reserved_cost_usd"] == 0


def make_candidate_run(engine, run_id="candidate"):
    baseline = "# Baseline\n"
    version = engine.start(run_id=run_id, contract_sha256="a"*64, goal="repair safely", logical_path=f"outputs/{run_id}.md", baseline=baseline)
    engine.claim_dispatch(run_id, role="review", ordinal=1, quoted_cost_usd=0, idempotency_key=f"{run_id}:review")
    review = parse_review(review_json(baseline, "REPAIR", repair_finding(f"{run_id}-f")), ("complete",), hashlib.sha256(baseline.encode()).hexdigest())
    engine.record_review(run_id, f"{run_id}-eval", version, review)
    engine.claim_dispatch(run_id, role="revision", ordinal=1, quoted_cost_usd=0, idempotency_key=f"{run_id}:revise")
    candidate = engine.preserve_candidate(run_id, 1, version, baseline + "\n## Candidate\n")
    return baseline, version, candidate


def test_regression_gates_and_preserves_accepted_bytes(cycle):
    engine, _, root = cycle
    baseline, _, _ = make_candidate_run(engine, "regress")
    assert engine.compare_candidate("regress", result="regressed", evidence={"criterion": "complete"}) == "HUMAN_DECISION_REQUIRED"
    assert (root / "outputs/regress.md").read_text() == baseline
    assert engine.status("regress")["next_action"] == "record_human_decision"


def test_unchanged_comparison_stops_at_no_progress_bound(cycle):
    engine, _, _ = cycle
    make_candidate_run(engine, "unchanged")
    assert engine.compare_candidate("unchanged", result="unchanged") == "BOUNDED_STOP"
    assert engine.status("unchanged")["next_action"] == "inspect_no_progress"


def test_cancellation_rejects_candidate_and_keeps_accepted(cycle):
    engine, ledger, root = cycle
    baseline, _, candidate = make_candidate_run(engine, "cancel")
    assert engine.cancel("cancel", reason="operator requested stop", idempotency_key="cancel:1") == "CANCELLED"
    assert engine.cancel("cancel", reason="operator requested stop", idempotency_key="cancel:1") == "CANCELLED"
    assert (root / "outputs/cancel.md").read_text() == baseline
    with ledger.connect() as con:
        assert con.execute("SELECT status FROM artifact_versions WHERE version_id=?", (candidate,)).fetchone()["status"] == "rejected"


def test_fresh_human_decision_works_and_stale_or_expired_fails(cycle):
    engine, ledger, _ = cycle
    engine.start(run_id="human", contract_sha256="a"*64, goal="safe", logical_path="outputs/human.md", baseline="# A")
    engine.claim_dispatch("human", role="review", ordinal=1, quoted_cost_usd=0, idempotency_key="human:review")
    engine.mark_ambiguous_dispatch("human", "human:review")
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    decision = engine.create_human_gate("human", gate_kind="ambiguous-dispatch", options=("stop", "cancel"), expiry_at=expiry)
    with ledger.connect() as con:
        fingerprint = con.execute("SELECT state_fingerprint FROM human_decisions WHERE decision_id=?", (decision,)).fetchone()["state_fingerprint"]
    assert engine.record_human_decision(decision, selected_option="stop", rationale="do not repeat an uncertain call", decider_label="operator", expected_state_fingerprint=fingerprint) == "request_new_authority"
    assert engine.status("human")["state"] == "BOUNDED_STOP"

    engine.start(run_id="expired", contract_sha256="a"*64, goal="safe", logical_path="outputs/expired.md", baseline="# A")
    engine.claim_dispatch("expired", role="review", ordinal=1, quoted_cost_usd=0, idempotency_key="expired:review")
    engine.mark_ambiguous_dispatch("expired", "expired:review")
    expired = engine.create_human_gate("expired", gate_kind="ambiguous-dispatch", options=("stop",), expiry_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
    with ledger.connect() as con:
        fp = con.execute("SELECT state_fingerprint FROM human_decisions WHERE decision_id=?", (expired,)).fetchone()["state_fingerprint"]
    with pytest.raises(RuntimeError, match="expired"):
        engine.record_human_decision(expired, selected_option="stop", rationale="late", decider_label="operator", expected_state_fingerprint=fp)


def test_cost_reconciliation_is_exactly_once_and_unknown_usage_gates(cycle):
    engine, _, _ = cycle
    engine.start(run_id="cost", contract_sha256="a"*64, goal="cost", logical_path="outputs/cost.md", baseline="# A", policy=RevisionPolicy(cost_ceiling_usd=1))
    engine.claim_dispatch("cost", role="review", ordinal=1, quoted_cost_usd=.4, idempotency_key="cost:review")
    engine.reconcile_dispatch("cost", quoted_cost_usd=.4, actual_cost_usd=.125, usage_known=True, idempotency_key="cost:review")
    engine.reconcile_dispatch("cost", quoted_cost_usd=.4, actual_cost_usd=.125, usage_known=True, idempotency_key="cost:review")
    status = engine.status("cost")
    assert status["spent_cost_usd"] == .125
    assert status["reserved_cost_usd"] == 0

    engine.start(run_id="unknown-cost", contract_sha256="a"*64, goal="cost", logical_path="outputs/unknown.md", baseline="# A", policy=RevisionPolicy(cost_ceiling_usd=1))
    engine.claim_dispatch("unknown-cost", role="review", ordinal=1, quoted_cost_usd=.4, idempotency_key="unknown:review")
    assert engine.reconcile_dispatch("unknown-cost", quoted_cost_usd=.4, actual_cost_usd=None, usage_known=False, idempotency_key="unknown:review") == "HUMAN_DECISION_REQUIRED"
    assert engine.status("unknown-cost")["reserved_cost_usd"] == .4


def test_materialization_reconciliation_and_sanitized_diagnostics(cycle):
    engine, _, root = cycle
    baseline, _, candidate = make_candidate_run(engine, "reconcile")
    assert engine.reconcile_materialization("reconcile") == "accepted-materialization-intact"
    with engine.ledger.connect() as con:
        content = bytes(con.execute("SELECT content_bytes FROM artifact_versions WHERE version_id=?", (candidate,)).fetchone()["content_bytes"])
    (root / "outputs/reconcile.md").write_bytes(content)
    assert engine.reconcile_materialization("reconcile") == "candidate-materialized-ledger-pending"
    bundle = engine.diagnostic_bundle("reconcile")
    serialized = json.dumps(bundle)
    assert bundle["schema_version"] == "phase10-diagnostic-v1"
    assert "content_bytes" not in serialized
    assert bundle["redaction"]["provider_request_ids"] == "excluded"
