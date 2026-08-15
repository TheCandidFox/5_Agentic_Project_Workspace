from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from future_interfaces import FutureInterfaceError, INTERFACE_FIELDS, validate_future_interface
from ledger import Ledger
from revision_cycle import RevisionCycle, RevisionPolicy


@pytest.fixture
def engine(tmp_path):
    return RevisionCycle(Ledger(tmp_path / "ledger.db", tmp_path), tmp_path), tmp_path


def start_claim(engine, run_id, role="review"):
    cycle, _ = engine
    cycle.start(run_id=run_id, contract_sha256="a"*64, goal="recover safely", logical_path=f"outputs/{run_id}.md", baseline="# Accepted\n", policy=RevisionPolicy(cost_ceiling_usd=1))
    cycle.claim_dispatch(run_id, role=role, ordinal=1, quoted_cost_usd=0, idempotency_key=f"{run_id}:claim")


def test_known_no_call_reauthorizes_exact_claim(engine):
    cycle, _ = engine
    start_claim(engine, "known")
    assert cycle.recover_claim("known", dispatch_evidence="not-dispatched", idempotency_key="known:recover") == "REVIEW_CLAIMED"
    assert cycle.status("known")["next_action"] == "dispatch_claimed_call"


def test_possible_dispatch_never_repeats_automatically(engine):
    cycle, _ = engine
    start_claim(engine, "ambiguous")
    assert cycle.recover_claim("ambiguous", dispatch_evidence="possibly-dispatched", idempotency_key="ambiguous:recover") == "HUMAN_DECISION_REQUIRED"
    assert cycle.status("ambiguous")["next_action"] == "record_human_decision"


def test_recorded_response_routes_to_parser_not_redispatch(engine):
    cycle, _ = engine
    start_claim(engine, "recorded")
    assert cycle.recover_claim("recorded", dispatch_evidence="response-recorded", idempotency_key="recorded:recover") == "RECOVERY_REQUIRED"
    assert cycle.status("recorded")["next_action"] == "parse_recorded_response"


def test_human_decision_rejects_changed_artifact_fingerprint(engine):
    cycle, _ = engine
    start_claim(engine, "freshness")
    cycle.mark_ambiguous_dispatch("freshness", "freshness:claim")
    decision = cycle.create_human_gate("freshness", gate_kind="ambiguous", options=("stop",), expiry_at=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat())
    with cycle.ledger.connect() as con:
        row = con.execute("SELECT state_fingerprint FROM human_decisions WHERE decision_id=?", (decision,)).fetchone()
        con.execute("UPDATE human_decisions SET artifact_fingerprint=? WHERE decision_id=?", ("0"*64, decision))
    with pytest.raises(RuntimeError, match="stale"):
        cycle.record_human_decision(decision, selected_option="stop", rationale="safe", decider_label="operator", expected_state_fingerprint=row["state_fingerprint"])


@pytest.mark.parametrize("version", sorted(INTERFACE_FIELDS))
def test_dormant_future_interfaces_are_strict_and_versioned(version):
    payload = {field: "value" for field in INTERFACE_FIELDS[version]}
    payload["schema_version"] = version
    assert validate_future_interface(payload, expected_version=version) is payload
    with pytest.raises(FutureInterfaceError):
        validate_future_interface({**payload, "unexpected": True}, expected_version=version)
    with pytest.raises(FutureInterfaceError):
        validate_future_interface({**payload, "schema_version": version.replace(".v1", ".v2")}, expected_version=version)


def test_status_only_and_diagnostics_do_not_mutate_ledger(engine):
    cycle, _ = engine
    cycle.start(run_id="readonly", contract_sha256="a"*64, goal="observe", logical_path="outputs/readonly.md", baseline="# A")
    with cycle.ledger.connect() as con:
        before = con.total_changes
    cycle.status("readonly")
    cycle.diagnostic_bundle("readonly")
    with cycle.ledger.connect() as con:
        assert con.total_changes == 0
