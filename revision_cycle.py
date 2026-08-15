from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from ledger import Ledger, utc_now
from revision_contracts import Finding, ReviewEnvelope, canonical_json, sha256_text
from workspace_guard import WorkspaceGuard


TERMINAL = frozenset({"ACCEPTED", "BOUNDED_STOP", "CANCELLED"})
TRANSITIONS = {
    "INTAKE_VALIDATED": {"BASELINE_PRESERVED"},
    "BASELINE_PRESERVED": {"REVIEW_CLAIMED", "BOUNDED_STOP", "CANCELLED"},
    "REVIEW_CLAIMED": {"REVIEW_RECORDED", "HUMAN_DECISION_REQUIRED", "RECOVERY_REQUIRED"},
    "REVIEW_RECORDED": {"REVISION_PLANNED", "ACCEPTED", "HUMAN_DECISION_REQUIRED", "BOUNDED_STOP"},
    "REVISION_PLANNED": {"REVISION_CLAIMED", "BOUNDED_STOP"},
    "REVISION_CLAIMED": {"CANDIDATE_PRESERVED", "HUMAN_DECISION_REQUIRED", "RECOVERY_REQUIRED", "BOUNDED_STOP"},
    "CANDIDATE_PRESERVED": {"CANDIDATE_VALIDATED", "HUMAN_DECISION_REQUIRED"},
    "CANDIDATE_VALIDATED": {"COMPARISON_RECORDED", "HUMAN_DECISION_REQUIRED", "BOUNDED_STOP"},
    "COMPARISON_RECORDED": {"REVIEW_CLAIMED", "ACCEPTED", "HUMAN_DECISION_REQUIRED", "BOUNDED_STOP"},
    "HUMAN_DECISION_REQUIRED": {"REVISION_PLANNED", "CANCELLED", "BOUNDED_STOP"},
    "RECOVERY_REQUIRED": {"REVIEW_CLAIMED", "REVISION_CLAIMED", "HUMAN_DECISION_REQUIRED", "CANCELLED"},
}


@dataclass(frozen=True)
class RevisionPolicy:
    max_revisions: int = 2
    max_dispatches: int = 5
    max_no_progress: int = 1
    max_runtime_seconds: int = 600
    cost_ceiling_usd: float = 0.0
    max_artifact_bytes: int = 250_000


class RevisionCycle:
    def __init__(self, ledger: Ledger, project_root: str | Path):
        self.ledger = ledger
        self.root = Path(project_root).resolve()
        self.guard = WorkspaceGuard(self.root)

    @staticmethod
    def _id(prefix: str, payload: str) -> str:
        return f"{prefix}-{sha256_text(payload)[:24]}"

    def start(self, *, run_id: str, contract_sha256: str, goal: str, logical_path: str, baseline: str, policy: RevisionPolicy = RevisionPolicy()) -> str:
        path = self.guard.authorize_write(logical_path, expect_directory=False).path
        content = baseline.encode("utf-8")
        if len(content) > policy.max_artifact_bytes:
            raise ValueError("baseline exceeds artifact limit")
        digest = hashlib.sha256(content).hexdigest()
        version_id = self._id("artifact", f"{run_id}:{logical_path}:{digest}")
        now = utc_now()
        with self.ledger.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute("SELECT accepted_version_id FROM revision_runs WHERE run_id=?", (run_id,)).fetchone()
            if existing:
                return str(existing["accepted_version_id"])
            con.execute("INSERT INTO revision_runs(run_id,contract_sha256,overall_goal,logical_path,state,accepted_version_id,baseline_version_id,policy_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (run_id, contract_sha256, goal, logical_path, "INTAKE_VALIDATED", version_id, version_id, canonical_json(policy.__dict__), now, now))
            con.execute("INSERT INTO artifact_versions(version_id,run_id,logical_path,parent_version_id,content_bytes,content_sha256,byte_count,media_type,source_task,source_attempt,status,created_at,accepted_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (version_id, run_id, logical_path, None, content, digest, len(content), "text/markdown", "baseline", 0, "accepted", now, now))
            self._transition(con, run_id, "INTAKE_VALIDATED", "BASELINE_PRESERVED", "baseline-preserved", f"start:{run_id}", {"version_id": version_id, "sha256": digest})
            self._capsule(con, run_id, "BASELINE_PRESERVED", "claim_review", {"accepted_version_id": version_id, "accepted_sha256": digest, "goal": goal})
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            self._atomic_write(path, content)
        elif path.read_bytes() != content:
            raise RuntimeError("declared output differs from accepted baseline")
        return version_id

    def _transition(self, con, run_id: str, prior: str, new: str, event: str, key: str, evidence: dict[str, Any]) -> None:
        if new not in TRANSITIONS.get(prior, set()):
            raise RuntimeError(f"invalid revision transition: {prior} -> {new}")
        row = con.execute("SELECT state FROM revision_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row["state"] != prior:
            raise RuntimeError("stale revision state")
        ordinal = con.execute("SELECT COALESCE(MAX(ordinal),0)+1 AS n FROM revision_transitions WHERE run_id=?", (run_id,)).fetchone()["n"]
        transition_id = self._id("transition", f"{run_id}:{key}")
        con.execute("INSERT OR IGNORE INTO revision_transitions(transition_id,run_id,ordinal,prior_state,new_state,event_type,idempotency_key,evidence_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (transition_id, run_id, ordinal, prior, new, event, key, canonical_json(evidence), utc_now()))
        if con.execute("SELECT changes() AS n").fetchone()["n"]:
            con.execute("UPDATE revision_runs SET state=?,updated_at=? WHERE run_id=?", (new, utc_now(), run_id))

    def _capsule(self, con, run_id: str, state: str, next_action: str, details: dict[str, Any]) -> str:
        payload = {"schema_version": "phase10-continuation-v1", "run_id": run_id, "state": state, "next_action": next_action, **details}
        serialized = canonical_json(payload)
        digest = sha256_text(serialized)
        capsule_id = self._id("capsule", digest)
        con.execute("INSERT OR IGNORE INTO continuation_capsules(capsule_id,schema_version,run_id,state,payload_json,payload_sha256,next_action,created_at) VALUES(?,?,?,?,?,?,?,?)", (capsule_id, "phase10-continuation-v1", run_id, state, serialized, digest, next_action, utc_now()))
        return capsule_id

    def claim_dispatch(self, run_id: str, *, role: str, ordinal: int, quoted_cost_usd: float, idempotency_key: str) -> str:
        if quoted_cost_usd < 0:
            raise ValueError("quoted cost cannot be negative")
        with self.ledger.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            run = con.execute("SELECT * FROM revision_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise KeyError(run_id)
            policy = json.loads(run["policy_json"])
            if run["spent_cost_usd"] + run["reserved_cost_usd"] + quoted_cost_usd > policy["cost_ceiling_usd"]:
                self._transition(con, run_id, run["state"], "BOUNDED_STOP", "budget-denied", f"budget:{idempotency_key}", {"quoted_cost_usd": quoted_cost_usd})
                self._capsule(con, run_id, "BOUNDED_STOP", "request_new_authority", {"reason": "budget-exhausted"})
                return "BOUNDED_STOP"
            new_state = "REVIEW_CLAIMED" if role == "review" else "REVISION_CLAIMED"
            prior = run["state"]
            self._transition(con, run_id, prior, new_state, f"{role}-claimed", idempotency_key, {"quoted_cost_usd": quoted_cost_usd, "ordinal": ordinal})
            self._capsule(con, run_id, new_state, "reconcile_possible_dispatch", {"role": role, "ordinal": ordinal, "idempotency_key": idempotency_key})
            con.execute("UPDATE revision_runs SET reserved_cost_usd=reserved_cost_usd+?,updated_at=? WHERE run_id=?", (quoted_cost_usd, utc_now(), run_id))
        return new_state

    def mark_ambiguous_dispatch(self, run_id: str, idempotency_key: str) -> None:
        with self.ledger.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            state = con.execute("SELECT state FROM revision_runs WHERE run_id=?", (run_id,)).fetchone()["state"]
            self._transition(con, run_id, state, "HUMAN_DECISION_REQUIRED", "ambiguous-dispatch", f"ambiguous:{idempotency_key}", {})
            self._capsule(con, run_id, "HUMAN_DECISION_REQUIRED", "record_human_decision", {"reason": "ambiguous-dispatch"})

    def record_review(self, run_id: str, evaluation_id: str, version_id: str, review: ReviewEnvelope) -> str:
        with self.ledger.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            run = con.execute("SELECT * FROM revision_runs WHERE run_id=?", (run_id,)).fetchone()
            if run["state"] != "REVIEW_CLAIMED":
                raise RuntimeError("review was not claimed")
            for finding in review.findings:
                con.execute("INSERT INTO review_findings(finding_id,schema_version,run_id,evaluation_id,version_id,criterion_key,verdict,severity,fingerprint,evidence_json,observed,expected,proposed_action,repair_eligibility,human_decision_reason,source_role,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (finding.finding_id, "phase10-review-v1", run_id, evaluation_id, version_id, finding.criterion_key, finding.verdict, finding.severity, finding.fingerprint, canonical_json(finding.evidence_refs), finding.observed, finding.expected, finding.proposed_action, finding.repair_eligibility, finding.human_decision_reason, "reviewer", "human_pending" if finding.verdict == "HUMAN_DECISION" else "open", utc_now()))
            con.execute("UPDATE revision_runs SET reserved_cost_usd=0,updated_at=? WHERE run_id=?", (utc_now(), run_id))
            self._transition(con, run_id, "REVIEW_CLAIMED", "REVIEW_RECORDED", "review-recorded", f"review:{evaluation_id}", {"verdict": review.overall_verdict})
            if review.overall_verdict == "PASS" and not review.findings:
                self._transition(con, run_id, "REVIEW_RECORDED", "ACCEPTED", "accepted", f"accept:{evaluation_id}", {"version_id": version_id})
                self._capsule(con, run_id, "ACCEPTED", "none", {"accepted_version_id": version_id})
                return "ACCEPTED"
            if any(f.verdict in {"BLOCK", "HUMAN_DECISION"} or f.repair_eligibility != "eligible" for f in review.findings):
                self._transition(con, run_id, "REVIEW_RECORDED", "HUMAN_DECISION_REQUIRED", "review-human-gate", f"gate:{evaluation_id}", {})
                self._capsule(con, run_id, "HUMAN_DECISION_REQUIRED", "record_human_decision", {"evaluation_id": evaluation_id})
                return "HUMAN_DECISION_REQUIRED"
            self._transition(con, run_id, "REVIEW_RECORDED", "REVISION_PLANNED", "revision-planned", f"plan:{evaluation_id}", {"finding_count": len(review.findings)})
            self._capsule(con, run_id, "REVISION_PLANNED", "claim_revision", {"evaluation_id": evaluation_id})
            return "REVISION_PLANNED"

    def preserve_candidate(self, run_id: str, attempt: int, baseline_version_id: str, markdown: str) -> str:
        content = markdown.encode("utf-8")
        with self.ledger.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            run = con.execute("SELECT * FROM revision_runs WHERE run_id=?", (run_id,)).fetchone()
            policy = json.loads(run["policy_json"])
            if len(content) > policy["max_artifact_bytes"]:
                raise ValueError("candidate exceeds artifact limit")
            if attempt > policy["max_revisions"]:
                self._transition(con, run_id, run["state"], "BOUNDED_STOP", "attempt-limit", f"attempt-limit:{run_id}:{attempt}", {})
                return "BOUNDED_STOP"
            digest = hashlib.sha256(content).hexdigest()
            version_id = self._id("artifact", f"{run_id}:{run['logical_path']}:{digest}")
            existing = con.execute("SELECT version_id FROM artifact_versions WHERE run_id=? AND logical_path=? AND content_sha256=?", (run_id, run["logical_path"], digest)).fetchone()
            if existing:
                self._transition(con, run_id, run["state"], "BOUNDED_STOP", "no-progress", f"no-progress:{run_id}:{attempt}", {"candidate_sha256": digest})
                self._capsule(con, run_id, "BOUNDED_STOP", "inspect_no_progress", {"candidate_sha256": digest})
                return "BOUNDED_STOP"
            now = utc_now()
            con.execute("INSERT INTO artifact_versions(version_id,run_id,logical_path,parent_version_id,content_bytes,content_sha256,byte_count,media_type,source_task,source_attempt,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (version_id, run_id, run["logical_path"], baseline_version_id, content, digest, len(content), "text/markdown", "revision", attempt, "candidate", now))
            con.execute("UPDATE revision_runs SET candidate_version_id=?,revision_count=?,reserved_cost_usd=0,updated_at=? WHERE run_id=?", (version_id, attempt, now, run_id))
            self._transition(con, run_id, "REVISION_CLAIMED", "CANDIDATE_PRESERVED", "candidate-preserved", f"candidate:{version_id}", {"sha256": digest})
            self._capsule(con, run_id, "CANDIDATE_PRESERVED", "validate_candidate", {"candidate_version_id": version_id, "candidate_sha256": digest})
            return version_id

    def accept_candidate(self, run_id: str, version_id: str) -> None:
        with self.ledger.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            run = con.execute("SELECT * FROM revision_runs WHERE run_id=?", (run_id,)).fetchone()
            row = con.execute("SELECT * FROM artifact_versions WHERE version_id=? AND run_id=?", (version_id, run_id)).fetchone()
            if not row or hashlib.sha256(bytes(row["content_bytes"])).hexdigest() != row["content_sha256"]:
                raise RuntimeError("candidate content hash mismatch")
            if run["state"] not in {"CANDIDATE_PRESERVED", "CANDIDATE_VALIDATED", "COMPARISON_RECORDED"}:
                raise RuntimeError("candidate cannot be accepted from current state")
            state = run["state"]
            if state == "CANDIDATE_PRESERVED":
                self._transition(con, run_id, state, "CANDIDATE_VALIDATED", "candidate-validated", f"validated:{version_id}", {})
                state = "CANDIDATE_VALIDATED"
            if state == "CANDIDATE_VALIDATED":
                self._transition(con, run_id, state, "COMPARISON_RECORDED", "comparison-improved", f"compare:{version_id}", {"result": "improved"})
                state = "COMPARISON_RECORDED"
            path = self.guard.authorize_write(run["logical_path"], expect_directory=False).path
            self._atomic_write(path, bytes(row["content_bytes"]))
            if hashlib.sha256(path.read_bytes()).hexdigest() != row["content_sha256"]:
                raise RuntimeError("materialized candidate hash mismatch")
            con.execute("UPDATE artifact_versions SET status='superseded',superseded_at=? WHERE version_id=? AND status='accepted'", (utc_now(), run["accepted_version_id"]))
            con.execute("UPDATE artifact_versions SET status='accepted',accepted_at=? WHERE version_id=? AND status='candidate'", (utc_now(), version_id))
            con.execute("UPDATE revision_runs SET accepted_version_id=?,baseline_version_id=?,candidate_version_id=NULL,updated_at=? WHERE run_id=?", (version_id, version_id, utc_now(), run_id))
            self._transition(con, run_id, state, "ACCEPTED", "candidate-accepted", f"accept:{version_id}", {"version_id": version_id, "sha256": row["content_sha256"]})
            self._capsule(con, run_id, "ACCEPTED", "none", {"accepted_version_id": version_id, "accepted_sha256": row["content_sha256"]})

    def consume_capsule(self, capsule_id: str, consumer_token: str) -> dict[str, Any]:
        with self.ledger.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM continuation_capsules WHERE capsule_id=?", (capsule_id,)).fetchone()
            if not row or row["superseded_by"] is not None:
                raise RuntimeError("capsule is missing or superseded")
            if sha256_text(row["payload_json"]) != row["payload_sha256"]:
                raise RuntimeError("capsule integrity check failed")
            if row["consumed_at"] is not None and row["consumer_token"] != consumer_token:
                raise RuntimeError("capsule already consumed")
            con.execute("UPDATE continuation_capsules SET consumed_at=COALESCE(consumed_at,?),consumer_token=COALESCE(consumer_token,?) WHERE capsule_id=?", (utc_now(), consumer_token, capsule_id))
            return json.loads(row["payload_json"])

    def status(self, run_id: str) -> dict[str, Any]:
        with self.ledger.connect() as con:
            run = con.execute("SELECT * FROM revision_runs WHERE run_id=?", (run_id,)).fetchone()
            if not run:
                raise KeyError(run_id)
            capsule = con.execute("SELECT capsule_id,next_action FROM continuation_capsules WHERE run_id=? ORDER BY created_at DESC LIMIT 1", (run_id,)).fetchone()
        segments = {"Govern": "PASS", "Plan": "PASS", "Revise": "PENDING", "Verify": "PENDING", "Handoff": "PENDING"}
        state = run["state"]
        if state in {"REVISION_PLANNED", "REVISION_CLAIMED", "CANDIDATE_PRESERVED"}: segments["Revise"] = "ACTIVE"
        if state in {"CANDIDATE_VALIDATED", "COMPARISON_RECORDED", "REVIEW_CLAIMED", "REVIEW_RECORDED"}: segments["Verify"] = "ACTIVE"
        if state in TERMINAL | {"HUMAN_DECISION_REQUIRED", "RECOVERY_REQUIRED"}: segments["Handoff"] = "PASS" if state == "ACCEPTED" else "ACTIVE"
        return {"run_id": run_id, "goal": run["overall_goal"], "state": state, "segments": segments, "spent_cost_usd": run["spent_cost_usd"], "reserved_cost_usd": run["reserved_cost_usd"], "revision_count": run["revision_count"], "accepted_version_id": run["accepted_version_id"], "candidate_version_id": run["candidate_version_id"], "capsule_id": None if not capsule else capsule["capsule_id"], "next_action": "none" if not capsule else capsule["next_action"]}

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
