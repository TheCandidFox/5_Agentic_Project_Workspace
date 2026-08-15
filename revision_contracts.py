from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


class RevisionContractError(ValueError):
    pass


VERDICTS = frozenset({"PASS", "REPAIR", "BLOCK", "HUMAN_DECISION"})
SEVERITIES = frozenset({"none", "low", "medium", "high", "critical"})
ELIGIBILITY = frozenset({"eligible", "ineligible", "not-applicable"})


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _object(text: str, *, maximum: int = 500_000) -> Mapping[str, Any]:
    if not isinstance(text, str) or len(text.encode("utf-8")) > maximum:
        raise RevisionContractError("response is empty or exceeds its byte limit")
    decoder = json.JSONDecoder()
    try:
        value, end = decoder.raw_decode(text)
    except json.JSONDecodeError as exc:
        raise RevisionContractError("response must contain one valid JSON object") from exc
    if text[end:].strip() or not isinstance(value, dict):
        raise RevisionContractError("response must contain exactly one JSON object")
    return value


def _exact(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise RevisionContractError(f"{name} fields do not match the strict schema")


def _text(value: Any, name: str, maximum: int = 2_000, empty: bool = False) -> str:
    if not isinstance(value, str) or "\x00" in value or (not empty and not value.strip()):
        raise RevisionContractError(f"{name} must be safe text")
    if len(value.encode("utf-8")) > maximum:
        raise RevisionContractError(f"{name} exceeds {maximum} bytes")
    return value.strip()


@dataclass(frozen=True)
class Finding:
    finding_id: str
    criterion_key: str
    verdict: str
    severity: str
    evidence_refs: tuple[str, ...]
    observed: str
    expected: str
    proposed_action: str
    repair_eligibility: str
    human_decision_reason: str | None

    @property
    def fingerprint(self) -> str:
        return sha256_text(canonical_json({
            "criterion_key": self.criterion_key,
            "verdict": self.verdict,
            "severity": self.severity,
            "evidence_refs": self.evidence_refs,
            "observed": " ".join(self.observed.split()),
            "expected": " ".join(self.expected.split()),
            "proposed_action": " ".join(self.proposed_action.split()),
        }))


@dataclass(frozen=True)
class ReviewEnvelope:
    artifact_sha256: str
    overall_verdict: str
    findings: tuple[Finding, ...]
    criterion_results: Mapping[str, str]
    summary: str
    recommended_next_action: str


def parse_review(text: str, required_criteria: Iterable[str], artifact_sha256: str) -> ReviewEnvelope:
    value = _object(text)
    _exact(value, {"schema_version", "artifact_sha256", "overall_verdict", "findings", "criterion_results", "summary", "recommended_next_action"}, "review")
    if value["schema_version"] != "phase10-review-v1" or value["artifact_sha256"] != artifact_sha256:
        raise RevisionContractError("review schema or artifact hash mismatch")
    required = tuple(required_criteria)
    results = value["criterion_results"]
    if not isinstance(results, dict) or tuple(results) != required or any(v not in VERDICTS for v in results.values()):
        raise RevisionContractError("criterion coverage must be complete and stable")
    raw_findings = value["findings"]
    if not isinstance(raw_findings, list) or len(raw_findings) > 64:
        raise RevisionContractError("findings must be a bounded array")
    findings: list[Finding] = []
    ids: set[str] = set()
    for raw in raw_findings:
        if not isinstance(raw, dict):
            raise RevisionContractError("finding must be an object")
        _exact(raw, {"finding_id", "criterion_key", "verdict", "severity", "evidence_refs", "observed", "expected", "proposed_action", "repair_eligibility", "human_decision_reason"}, "finding")
        fid = _text(raw["finding_id"], "finding_id", 128)
        criterion = _text(raw["criterion_key"], "criterion_key", 64)
        refs = raw["evidence_refs"]
        if fid in ids or criterion not in required or not isinstance(refs, list) or not refs or len(refs) > 16:
            raise RevisionContractError("finding identity, criterion, or evidence is invalid")
        ids.add(fid)
        verdict, severity, eligibility = raw["verdict"], raw["severity"], raw["repair_eligibility"]
        reason = raw["human_decision_reason"]
        if verdict not in VERDICTS or severity not in SEVERITIES or eligibility not in ELIGIBILITY:
            raise RevisionContractError("finding enums are invalid")
        if (verdict == "REPAIR") != (eligibility == "eligible"):
            raise RevisionContractError("repair verdict and eligibility contradict")
        if verdict == "HUMAN_DECISION" and not isinstance(reason, str):
            raise RevisionContractError("human decision finding requires a reason")
        findings.append(Finding(fid, criterion, verdict, severity, tuple(_text(x, "evidence_ref", 256) for x in refs), _text(raw["observed"], "observed"), _text(raw["expected"], "expected"), _text(raw["proposed_action"], "proposed_action"), eligibility, None if reason is None else _text(reason, "human_decision_reason")))
    for criterion, verdict in results.items():
        related = [f for f in findings if f.criterion_key == criterion]
        if verdict == "PASS" and related:
            raise RevisionContractError("PASS criterion cannot contain an open finding")
        if verdict != "PASS" and not related:
            raise RevisionContractError("non-PASS criterion requires a finding")
    overall = value["overall_verdict"]
    if overall not in VERDICTS:
        raise RevisionContractError("overall verdict is invalid")
    return ReviewEnvelope(artifact_sha256, overall, tuple(findings), results, _text(value["summary"], "summary", 2_000), _text(value["recommended_next_action"], "recommended_next_action", 1_000))


@dataclass(frozen=True)
class RevisionProposal:
    baseline_sha256: str
    finding_set_sha256: str
    target_finding_ids: tuple[str, ...]
    rationale: str
    candidate_markdown: str
    claimed_resolved: tuple[str, ...]
    deferred: tuple[str, ...]


def parse_revision(text: str, *, baseline_sha256: str, finding_set_sha256: str, eligible_ids: Iterable[str]) -> RevisionProposal:
    value = _object(text)
    _exact(value, {"schema_version", "baseline_sha256", "finding_set_sha256", "target_finding_ids", "rationale", "candidate_markdown", "claimed_resolved", "deferred"}, "revision")
    if value["schema_version"] != "phase10-revision-v1" or value["baseline_sha256"] != baseline_sha256 or value["finding_set_sha256"] != finding_set_sha256:
        raise RevisionContractError("revision schema or baseline identity mismatch")
    target = value["target_finding_ids"]
    allowed = set(eligible_ids)
    if not isinstance(target, list) or not target or len(target) != len(set(target)) or not set(target) <= allowed:
        raise RevisionContractError("revision targets exceed eligible authority")
    candidate = _text(value["candidate_markdown"], "candidate_markdown", 250_000)
    resolved, deferred = value["claimed_resolved"], value["deferred"]
    if not isinstance(resolved, list) or not isinstance(deferred, list) or not set(resolved + deferred) <= set(target):
        raise RevisionContractError("revision resolution claims are invalid")
    return RevisionProposal(baseline_sha256, finding_set_sha256, tuple(target), _text(value["rationale"], "rationale", 4_000), candidate, tuple(resolved), tuple(deferred))
