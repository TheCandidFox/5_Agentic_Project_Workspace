from __future__ import annotations

import hashlib
import json
import sqlite3

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
