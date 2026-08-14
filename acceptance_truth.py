from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from ledger import Ledger, utc_now


class AcceptanceError(RuntimeError):
    """Base class for deterministic acceptance-governance failures."""


class AcceptanceIdempotencyConflict(AcceptanceError):
    """One acceptance key was reused for a different evaluation request."""


class AcceptanceRunNotReplayable(AcceptanceError):
    """A failed acceptance run cannot be retried under the same key."""


class TruthLabel(str, Enum):
    VERIFIED = "VERIFIED"
    SUPPORTED = "SUPPORTED"
    INFERRED = "INFERRED"
    DISPUTED = "DISPUTED"
    UNKNOWN = "UNKNOWN"


class AcceptanceOutcome(str, Enum):
    PASS = "PASS"
    REPAIR = "REPAIR"
    BLOCK = "BLOCK"
    HUMAN_DECISION = "HUMAN_DECISION"
    DEFER = "DEFER"


class EvidenceKind(str, Enum):
    DETERMINISTIC_VALIDATION = "DETERMINISTIC_VALIDATION"
    OBSERVATION = "OBSERVATION"
    PRIMARY_SOURCE = "PRIMARY_SOURCE"
    CORROBORATED_SOURCE = "CORROBORATED_SOURCE"
    SEMANTIC_REVIEW = "SEMANTIC_REVIEW"
    HUMAN_DECISION = "HUMAN_DECISION"


class EvidenceDisposition(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    NEUTRAL = "NEUTRAL"


class CriterionVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    DISPUTED = "DISPUTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _safe_text(name: str, value: Any, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be a non-empty safe string")
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return normalized


def _optional_text(name: str, value: Any, *, maximum: int) -> str | None:
    if value is None:
        return None
    return _safe_text(name, value, maximum=maximum)


def _timestamp(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _safe_text(name, value, maximum=64)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return normalized


def _evidence_keys(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{name} must be a tuple")
    normalized = tuple(
        _safe_text(f"{name} item", item, maximum=120) for item in values
    )
    if len({item.casefold() for item in normalized}) != len(normalized):
        raise ValueError(f"{name} must not contain duplicates")
    return normalized


@dataclass(frozen=True)
class EvidenceRef:
    evidence_key: str
    kind: EvidenceKind
    disposition: EvidenceDisposition
    summary: str
    reference: str
    observed_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_key",
            _safe_text("evidence_key", self.evidence_key, maximum=120),
        )
        if not isinstance(self.kind, EvidenceKind):
            raise TypeError("evidence kind must be an EvidenceKind")
        if not isinstance(self.disposition, EvidenceDisposition):
            raise TypeError("evidence disposition must be an EvidenceDisposition")
        object.__setattr__(
            self, "summary", _safe_text("evidence summary", self.summary, maximum=2_000)
        )
        object.__setattr__(
            self, "reference", _safe_text("evidence reference", self.reference, maximum=1_000)
        )
        object.__setattr__(
            self, "observed_at", _timestamp("observed_at", self.observed_at)
        )


@dataclass(frozen=True)
class ClaimAssessment:
    claim_key: str
    statement: str
    truth_label: TruthLabel
    evidence_keys: tuple[str, ...] = ()
    rationale: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "claim_key", _safe_text("claim_key", self.claim_key, maximum=120)
        )
        object.__setattr__(
            self, "statement", _safe_text("claim statement", self.statement, maximum=4_000)
        )
        if not isinstance(self.truth_label, TruthLabel):
            raise TypeError("truth_label must be a TruthLabel")
        object.__setattr__(
            self,
            "evidence_keys",
            _evidence_keys("claim evidence_keys", self.evidence_keys),
        )
        rationale = _optional_text("claim rationale", self.rationale, maximum=4_000)
        object.__setattr__(self, "rationale", rationale)
        if self.truth_label == TruthLabel.INFERRED and not rationale:
            raise ValueError("INFERRED claims require an explicit rationale")


@dataclass(frozen=True)
class CriterionAssessment:
    criterion_key: str
    description: str
    required: bool
    verdict: CriterionVerdict
    evidence_keys: tuple[str, ...] = ()
    unresolved_action: AcceptanceOutcome = AcceptanceOutcome.HUMAN_DECISION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "criterion_key",
            _safe_text("criterion_key", self.criterion_key, maximum=120),
        )
        object.__setattr__(
            self,
            "description",
            _safe_text("criterion description", self.description, maximum=4_000),
        )
        if not isinstance(self.required, bool):
            raise TypeError("criterion required must be a boolean")
        if not isinstance(self.verdict, CriterionVerdict):
            raise TypeError("criterion verdict must be a CriterionVerdict")
        object.__setattr__(
            self,
            "evidence_keys",
            _evidence_keys("criterion evidence_keys", self.evidence_keys),
        )
        if self.unresolved_action not in {
            AcceptanceOutcome.HUMAN_DECISION,
            AcceptanceOutcome.DEFER,
        }:
            raise ValueError("unresolved_action must be HUMAN_DECISION or DEFER")


@dataclass(frozen=True)
class ConstraintFinding:
    constraint_key: str
    description: str
    violated: bool
    evidence_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "constraint_key",
            _safe_text("constraint_key", self.constraint_key, maximum=120),
        )
        object.__setattr__(
            self,
            "description",
            _safe_text("constraint description", self.description, maximum=4_000),
        )
        if not isinstance(self.violated, bool):
            raise TypeError("constraint violated must be a boolean")
        object.__setattr__(
            self,
            "evidence_keys",
            _evidence_keys("constraint evidence_keys", self.evidence_keys),
        )
        if self.violated and not self.evidence_keys:
            raise ValueError("a constraint violation requires evidence")


@dataclass(frozen=True)
class AcceptanceRequest:
    evaluation_id: str
    task_id: str
    objective: str
    idempotency_key: str
    evidence: tuple[EvidenceRef, ...]
    claims: tuple[ClaimAssessment, ...]
    criteria: tuple[CriterionAssessment, ...]
    constraints: tuple[ConstraintFinding, ...] = ()

    def __post_init__(self) -> None:
        for name, maximum in (
            ("evaluation_id", 200),
            ("task_id", 200),
            ("idempotency_key", 500),
        ):
            object.__setattr__(
                self, name, _safe_text(name, getattr(self, name), maximum=maximum)
            )
        object.__setattr__(
            self, "objective", _safe_text("objective", self.objective, maximum=4_000)
        )
        for name, value, expected in (
            ("evidence", self.evidence, EvidenceRef),
            ("claims", self.claims, ClaimAssessment),
            ("criteria", self.criteria, CriterionAssessment),
            ("constraints", self.constraints, ConstraintFinding),
        ):
            if not isinstance(value, tuple) or not all(
                isinstance(item, expected) for item in value
            ):
                raise TypeError(f"{name} must be a tuple of {expected.__name__} values")
        if not self.criteria:
            raise ValueError("acceptance requires at least one criterion")
        self._require_unique("evidence", [item.evidence_key for item in self.evidence])
        self._require_unique("claims", [item.claim_key for item in self.claims])
        self._require_unique("criteria", [item.criterion_key for item in self.criteria])
        self._require_unique(
            "constraints", [item.constraint_key for item in self.constraints]
        )
        known = {item.evidence_key.casefold() for item in self.evidence}
        for label, assessments in (
            ("claim", self.claims),
            ("criterion", self.criteria),
            ("constraint", self.constraints),
        ):
            for assessment in assessments:
                for key in assessment.evidence_keys:
                    if key.casefold() not in known:
                        raise ValueError(f"{label} references unknown evidence: {key}")

    @staticmethod
    def _require_unique(name: str, values: list[str]) -> None:
        if len({value.casefold() for value in values}) != len(values):
            raise ValueError(f"acceptance {name} identities must be unique")


@dataclass(frozen=True)
class AcceptanceResult:
    evaluation_id: str
    task_id: str
    objective: str
    outcome: AcceptanceOutcome
    summary: str
    evidence: tuple[EvidenceRef, ...]
    claims: tuple[ClaimAssessment, ...]
    criteria: tuple[CriterionAssessment, ...]
    constraints: tuple[ConstraintFinding, ...]
    replayed: bool = False


def acceptance_request_sha256(request: AcceptanceRequest) -> str:
    payload = asdict(request)
    payload.pop("evaluation_id", None)
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class AcceptanceStore:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    @staticmethod
    def _event(con, task_id: str, event_type: str, payload: Mapping[str, Any], now: str) -> None:
        con.execute(
            """
            INSERT INTO events(task_id,event_type,payload_json,created_at)
            VALUES(?,?,?,?)
            """,
            (task_id, event_type, json.dumps(dict(payload), sort_keys=True), now),
        )

    def claim(
        self, request: AcceptanceRequest, *, request_sha256: str
    ) -> tuple[bool, dict[str, Any]]:
        now = utc_now()
        with self.ledger.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute(
                "SELECT * FROM acceptance_runs WHERE idempotency_key=?",
                (request.idempotency_key,),
            ).fetchone()
            if existing is not None:
                record = dict(existing)
                if record["request_sha256"] != request_sha256:
                    raise AcceptanceIdempotencyConflict(
                        "acceptance idempotency key belongs to a different request"
                    )
                return False, record
            con.execute(
                """
                INSERT INTO acceptance_runs(
                    evaluation_id,task_id,objective,idempotency_key,request_sha256,
                    status,started_at,updated_at
                ) VALUES(?,?,?,?,?,'evaluating',?,?)
                """,
                (
                    request.evaluation_id,
                    request.task_id,
                    request.objective,
                    request.idempotency_key,
                    request_sha256,
                    now,
                    now,
                ),
            )
            self._event(
                con,
                request.task_id,
                "acceptance_started",
                {
                    "evaluation_id": request.evaluation_id,
                    "evidence_count": len(request.evidence),
                    "claim_count": len(request.claims),
                    "criterion_count": len(request.criteria),
                    "constraint_count": len(request.constraints),
                },
                now,
            )
            row = con.execute(
                "SELECT * FROM acceptance_runs WHERE evaluation_id=?",
                (request.evaluation_id,),
            ).fetchone()
            assert row is not None
            return True, dict(row)

    def complete(
        self,
        request: AcceptanceRequest,
        *,
        outcome: AcceptanceOutcome,
        summary: str,
        evaluation_id: str | None = None,
    ) -> None:
        durable_id = evaluation_id or request.evaluation_id
        now = utc_now()
        with self.ledger.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            run = con.execute(
                "SELECT * FROM acceptance_runs WHERE evaluation_id=?", (durable_id,)
            ).fetchone()
            if run is None or run["status"] != "evaluating":
                raise AcceptanceError("acceptance run is not ready for completion")
            for evidence in request.evidence:
                record_id = self._record_id(durable_id, "evidence", evidence.evidence_key)
                con.execute(
                    """
                    INSERT INTO acceptance_evidence(
                        evidence_record_id,evaluation_id,evidence_key,kind,
                        disposition,summary,reference,observed_at
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        record_id,
                        durable_id,
                        evidence.evidence_key,
                        evidence.kind.value,
                        evidence.disposition.value,
                        evidence.summary,
                        evidence.reference,
                        evidence.observed_at,
                    ),
                )
            for claim in request.claims:
                record_id = self._record_id(durable_id, "claim", claim.claim_key)
                con.execute(
                    """
                    INSERT INTO acceptance_claims(
                        claim_record_id,evaluation_id,claim_key,statement,truth_label,
                        rationale,evidence_keys_json
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        record_id,
                        durable_id,
                        claim.claim_key,
                        claim.statement,
                        claim.truth_label.value,
                        claim.rationale,
                        self._keys_json(claim.evidence_keys),
                    ),
                )
            for criterion in request.criteria:
                record_id = self._record_id(
                    durable_id, "criterion", criterion.criterion_key
                )
                con.execute(
                    """
                    INSERT INTO acceptance_criteria(
                        criterion_record_id,evaluation_id,criterion_key,description,
                        required,verdict,unresolved_action,evidence_keys_json
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        record_id,
                        durable_id,
                        criterion.criterion_key,
                        criterion.description,
                        int(criterion.required),
                        criterion.verdict.value,
                        criterion.unresolved_action.value,
                        self._keys_json(criterion.evidence_keys),
                    ),
                )
            for constraint in request.constraints:
                record_id = self._record_id(
                    durable_id, "constraint", constraint.constraint_key
                )
                con.execute(
                    """
                    INSERT INTO acceptance_constraints(
                        constraint_record_id,evaluation_id,constraint_key,description,
                        violated,evidence_keys_json
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (
                        record_id,
                        durable_id,
                        constraint.constraint_key,
                        constraint.description,
                        int(constraint.violated),
                        self._keys_json(constraint.evidence_keys),
                    ),
                )
            cursor = con.execute(
                """
                UPDATE acceptance_runs
                SET status='completed',outcome=?,summary=?,completed_at=?,updated_at=?,
                    error=NULL
                WHERE evaluation_id=? AND status='evaluating'
                """,
                (outcome.value, summary, now, now, durable_id),
            )
            if cursor.rowcount != 1:
                raise AcceptanceError("acceptance completion state changed concurrently")
            self._event(
                con,
                str(run["task_id"]),
                "acceptance_completed",
                {
                    "evaluation_id": durable_id,
                    "outcome": outcome.value,
                    "claim_count": len(request.claims),
                    "criterion_count": len(request.criteria),
                    "constraint_count": len(request.constraints),
                },
                now,
            )

    @staticmethod
    def _record_id(evaluation_id: str, kind: str, key: str) -> str:
        return hashlib.sha256(
            f"{evaluation_id}\x00{kind}\x00{key}".encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _keys_json(keys: tuple[str, ...]) -> str:
        return json.dumps(list(keys), separators=(",", ":"), ensure_ascii=False)

    def fail(self, evaluation_id: str, error: str) -> None:
        now = utc_now()
        safe_error = _safe_text("acceptance error", error, maximum=4_000)
        with self.ledger.connect() as con:
            run = con.execute(
                "SELECT task_id,status FROM acceptance_runs WHERE evaluation_id=?",
                (evaluation_id,),
            ).fetchone()
            if run is None or run["status"] != "evaluating":
                return
            con.execute(
                """
                UPDATE acceptance_runs
                SET status='failed',error=?,completed_at=?,updated_at=?
                WHERE evaluation_id=? AND status='evaluating'
                """,
                (safe_error, now, now, evaluation_id),
            )
            self._event(
                con,
                str(run["task_id"]),
                "acceptance_failed",
                {"evaluation_id": evaluation_id, "error": safe_error},
                now,
            )

    def load_result(self, evaluation_id: str, *, replayed: bool) -> AcceptanceResult:
        with self.ledger.connect() as con:
            run = con.execute(
                "SELECT * FROM acceptance_runs WHERE evaluation_id=?", (evaluation_id,)
            ).fetchone()
            if run is None or run["status"] != "completed":
                raise AcceptanceRunNotReplayable("acceptance run is not completed")
            evidence_rows = con.execute(
                """
                SELECT * FROM acceptance_evidence
                WHERE evaluation_id=? ORDER BY evidence_key
                """,
                (evaluation_id,),
            ).fetchall()
            claim_rows = con.execute(
                """
                SELECT * FROM acceptance_claims
                WHERE evaluation_id=? ORDER BY claim_key
                """,
                (evaluation_id,),
            ).fetchall()
            criterion_rows = con.execute(
                """
                SELECT * FROM acceptance_criteria
                WHERE evaluation_id=? ORDER BY criterion_key
                """,
                (evaluation_id,),
            ).fetchall()
            constraint_rows = con.execute(
                """
                SELECT * FROM acceptance_constraints
                WHERE evaluation_id=? ORDER BY constraint_key
                """,
                (evaluation_id,),
            ).fetchall()
        evidence = tuple(
            EvidenceRef(
                evidence_key=str(row["evidence_key"]),
                kind=EvidenceKind(str(row["kind"])),
                disposition=EvidenceDisposition(str(row["disposition"])),
                summary=str(row["summary"]),
                reference=str(row["reference"]),
                observed_at=row["observed_at"],
            )
            for row in evidence_rows
        )
        claims = tuple(
            ClaimAssessment(
                claim_key=str(row["claim_key"]),
                statement=str(row["statement"]),
                truth_label=TruthLabel(str(row["truth_label"])),
                evidence_keys=tuple(json.loads(row["evidence_keys_json"])),
                rationale=row["rationale"],
            )
            for row in claim_rows
        )
        criteria = tuple(
            CriterionAssessment(
                criterion_key=str(row["criterion_key"]),
                description=str(row["description"]),
                required=bool(row["required"]),
                verdict=CriterionVerdict(str(row["verdict"])),
                unresolved_action=AcceptanceOutcome(str(row["unresolved_action"])),
                evidence_keys=tuple(json.loads(row["evidence_keys_json"])),
            )
            for row in criterion_rows
        )
        constraints = tuple(
            ConstraintFinding(
                constraint_key=str(row["constraint_key"]),
                description=str(row["description"]),
                violated=bool(row["violated"]),
                evidence_keys=tuple(json.loads(row["evidence_keys_json"])),
            )
            for row in constraint_rows
        )
        return AcceptanceResult(
            evaluation_id=str(run["evaluation_id"]),
            task_id=str(run["task_id"]),
            objective=str(run["objective"]),
            outcome=AcceptanceOutcome(str(run["outcome"])),
            summary=str(run["summary"]),
            evidence=evidence,
            claims=claims,
            criteria=criteria,
            constraints=constraints,
            replayed=replayed,
        )


class AcceptanceEngine:
    STRONG_EVIDENCE = frozenset(
        {
            EvidenceKind.DETERMINISTIC_VALIDATION,
            EvidenceKind.OBSERVATION,
            EvidenceKind.PRIMARY_SOURCE,
            EvidenceKind.HUMAN_DECISION,
        }
    )

    def __init__(self, ledger: Ledger) -> None:
        self.store = AcceptanceStore(ledger)

    def evaluate(self, request: AcceptanceRequest) -> AcceptanceResult:
        evidence = {item.evidence_key.casefold(): item for item in request.evidence}
        self._validate_claims(request.claims, evidence)
        self._validate_criteria(request.criteria, evidence)
        self._validate_constraints(request.constraints, evidence)
        fingerprint = acceptance_request_sha256(request)
        claimed, record = self.store.claim(request, request_sha256=fingerprint)
        if not claimed:
            status = str(record["status"])
            if status == "completed":
                return self.store.load_result(
                    str(record["evaluation_id"]), replayed=True
                )
            if status != "evaluating":
                raise AcceptanceRunNotReplayable(
                    f"acceptance run cannot replay from terminal state: {status}"
                )
        evaluation_id = str(record["evaluation_id"])
        try:
            outcome = self._aggregate(request.criteria, request.constraints)
            summary = self._summary(outcome, request.criteria, request.constraints)
            self.store.complete(
                request,
                outcome=outcome,
                summary=summary,
                evaluation_id=evaluation_id,
            )
            return self.store.load_result(evaluation_id, replayed=False)
        except Exception as exc:
            self.store.fail(evaluation_id, f"{type(exc).__name__}: {exc}")
            raise

    @classmethod
    def _validate_claims(
        cls,
        claims: tuple[ClaimAssessment, ...],
        evidence: Mapping[str, EvidenceRef],
    ) -> None:
        for claim in claims:
            items = [evidence[key.casefold()] for key in claim.evidence_keys]
            supports = [
                item for item in items if item.disposition == EvidenceDisposition.SUPPORTS
            ]
            contradicts = [
                item
                for item in items
                if item.disposition == EvidenceDisposition.CONTRADICTS
            ]
            if claim.truth_label == TruthLabel.VERIFIED:
                if contradicts or not any(item.kind in cls.STRONG_EVIDENCE for item in supports):
                    raise AcceptanceError(
                        f"VERIFIED claim lacks uncontradicted strong evidence: {claim.claim_key}"
                    )
            elif claim.truth_label == TruthLabel.SUPPORTED:
                if contradicts or not supports:
                    raise AcceptanceError(
                        f"SUPPORTED claim lacks uncontradicted evidence: {claim.claim_key}"
                    )
            elif claim.truth_label == TruthLabel.INFERRED:
                if contradicts:
                    raise AcceptanceError(
                        f"INFERRED claim has contradicting evidence: {claim.claim_key}"
                    )
            elif claim.truth_label == TruthLabel.DISPUTED:
                if not supports or not contradicts:
                    raise AcceptanceError(
                        f"DISPUTED claim requires support and contradiction: {claim.claim_key}"
                    )

    @staticmethod
    def _validate_criteria(
        criteria: tuple[CriterionAssessment, ...],
        evidence: Mapping[str, EvidenceRef],
    ) -> None:
        for criterion in criteria:
            items = [evidence[key.casefold()] for key in criterion.evidence_keys]
            supports = any(
                item.disposition == EvidenceDisposition.SUPPORTS for item in items
            )
            contradicts = any(
                item.disposition == EvidenceDisposition.CONTRADICTS for item in items
            )
            if criterion.verdict == CriterionVerdict.PASS and (
                not supports or contradicts
            ):
                raise AcceptanceError(
                    f"PASS criterion requires uncontradicted support: {criterion.criterion_key}"
                )
            if criterion.verdict == CriterionVerdict.FAIL and not contradicts:
                raise AcceptanceError(
                    f"FAIL criterion requires contradicting evidence: {criterion.criterion_key}"
                )
            if criterion.verdict == CriterionVerdict.DISPUTED and not (
                supports and contradicts
            ):
                raise AcceptanceError(
                    f"DISPUTED criterion requires support and contradiction: {criterion.criterion_key}"
                )
            if criterion.verdict in {
                CriterionVerdict.UNKNOWN,
                CriterionVerdict.NOT_APPLICABLE,
            } and (supports or contradicts):
                raise AcceptanceError(
                    f"{criterion.verdict.value} criterion cannot hide directional evidence: "
                    f"{criterion.criterion_key}"
                )

    @staticmethod
    def _validate_constraints(
        constraints: tuple[ConstraintFinding, ...],
        evidence: Mapping[str, EvidenceRef],
    ) -> None:
        for constraint in constraints:
            if not constraint.violated:
                continue
            items = [evidence[key.casefold()] for key in constraint.evidence_keys]
            supports = any(
                item.disposition == EvidenceDisposition.SUPPORTS for item in items
            )
            contradicts = any(
                item.disposition == EvidenceDisposition.CONTRADICTS for item in items
            )
            if not supports or contradicts:
                raise AcceptanceError(
                    f"constraint violation requires uncontradicted evidence: {constraint.constraint_key}"
                )

    @staticmethod
    def _aggregate(
        criteria: tuple[CriterionAssessment, ...],
        constraints: tuple[ConstraintFinding, ...],
    ) -> AcceptanceOutcome:
        if any(item.violated for item in constraints):
            return AcceptanceOutcome.BLOCK
        required = [item for item in criteria if item.required]
        if any(item.verdict == CriterionVerdict.FAIL for item in required):
            return AcceptanceOutcome.REPAIR
        unresolved = [
            item
            for item in required
            if item.verdict
            in {
                CriterionVerdict.UNKNOWN,
                CriterionVerdict.DISPUTED,
                CriterionVerdict.NOT_APPLICABLE,
            }
        ]
        if any(
            item.unresolved_action == AcceptanceOutcome.HUMAN_DECISION
            for item in unresolved
        ):
            return AcceptanceOutcome.HUMAN_DECISION
        if unresolved:
            return AcceptanceOutcome.DEFER
        return AcceptanceOutcome.PASS

    @staticmethod
    def _summary(
        outcome: AcceptanceOutcome,
        criteria: tuple[CriterionAssessment, ...],
        constraints: tuple[ConstraintFinding, ...],
    ) -> str:
        required = sum(1 for item in criteria if item.required)
        passing = sum(
            1
            for item in criteria
            if item.required and item.verdict == CriterionVerdict.PASS
        )
        violations = sum(1 for item in constraints if item.violated)
        return (
            f"{outcome.value}: {passing}/{required} required criteria pass; "
            f"hard constraint violations={violations}"
        )


@dataclass(frozen=True)
class CalibrationReport:
    expected: tuple[AcceptanceOutcome, ...]
    first_round: tuple[AcceptanceOutcome, ...]
    second_round: tuple[AcceptanceOutcome, ...]

    @property
    def passed(self) -> bool:
        return self.first_round == self.expected and self.second_round == self.expected


def run_acceptance_calibration(
    ledger: Ledger, *, key_prefix: str = "phase6:acceptance-calibration"
) -> CalibrationReport:
    expected = (
        AcceptanceOutcome.PASS,
        AcceptanceOutcome.REPAIR,
        AcceptanceOutcome.PASS,
        AcceptanceOutcome.BLOCK,
        AcceptanceOutcome.HUMAN_DECISION,
    )
    rounds: list[tuple[AcceptanceOutcome, ...]] = []
    engine = AcceptanceEngine(ledger)
    for round_number in (1, 2):
        outcomes: list[AcceptanceOutcome] = []
        for case_number, request in enumerate(
            _calibration_requests(key_prefix, round_number), start=1
        ):
            result = engine.evaluate(request)
            outcomes.append(result.outcome)
            if result.outcome != expected[case_number - 1]:
                # Continue only through the fixed five-case set; do not recurse.
                continue
        rounds.append(tuple(outcomes))
    return CalibrationReport(
        expected=expected,
        first_round=rounds[0],
        second_round=rounds[1],
    )


def _calibration_requests(
    prefix: str, round_number: int
) -> tuple[AcceptanceRequest, ...]:
    stem = f"{prefix}:round-{round_number}"

    complete_evidence = EvidenceRef(
        evidence_key="tests-pass",
        kind=EvidenceKind.DETERMINISTIC_VALIDATION,
        disposition=EvidenceDisposition.SUPPORTS,
        summary="All required deterministic tests passed.",
        reference="validation:known-complete",
    )
    complete = AcceptanceRequest(
        evaluation_id=f"{stem}:complete",
        task_id="calibration-complete",
        objective="Known complete deliverable.",
        idempotency_key=f"{stem}:complete:v1",
        evidence=(complete_evidence,),
        claims=(
            ClaimAssessment(
                claim_key="complete-claim",
                statement="The deterministic test suite passed.",
                truth_label=TruthLabel.VERIFIED,
                evidence_keys=("tests-pass",),
            ),
        ),
        criteria=(
            CriterionAssessment(
                criterion_key="tests",
                description="Required tests pass.",
                required=True,
                verdict=CriterionVerdict.PASS,
                evidence_keys=("tests-pass",),
            ),
        ),
    )

    incomplete_evidence = EvidenceRef(
        evidence_key="missing-section",
        kind=EvidenceKind.DETERMINISTIC_VALIDATION,
        disposition=EvidenceDisposition.CONTRADICTS,
        summary="A required section is absent.",
        reference="validation:known-incomplete",
    )
    incomplete = AcceptanceRequest(
        evaluation_id=f"{stem}:incomplete",
        task_id="calibration-incomplete",
        objective="Known incomplete deliverable.",
        idempotency_key=f"{stem}:incomplete:v1",
        evidence=(incomplete_evidence,),
        claims=(),
        criteria=(
            CriterionAssessment(
                criterion_key="required-section",
                description="Required section exists.",
                required=True,
                verdict=CriterionVerdict.FAIL,
                evidence_keys=("missing-section",),
            ),
        ),
    )

    uncertainty_evidence = EvidenceRef(
        evidence_key="uncertainty-labeled",
        kind=EvidenceKind.OBSERVATION,
        disposition=EvidenceDisposition.SUPPORTS,
        summary="The unresolved value is explicitly labeled UNKNOWN.",
        reference="observation:uncertainty-label",
    )
    uncertainty = AcceptanceRequest(
        evaluation_id=f"{stem}:uncertainty",
        task_id="calibration-uncertainty",
        objective="Supported uncertainty is represented honestly.",
        idempotency_key=f"{stem}:uncertainty:v1",
        evidence=(uncertainty_evidence,),
        claims=(
            ClaimAssessment(
                claim_key="unknown-value",
                statement="The value cannot be determined from current evidence.",
                truth_label=TruthLabel.UNKNOWN,
                rationale="No authoritative value is available in the fixture.",
            ),
        ),
        criteria=(
            CriterionAssessment(
                criterion_key="label-uncertainty",
                description="Uncertainty is explicitly labeled.",
                required=True,
                verdict=CriterionVerdict.PASS,
                evidence_keys=("uncertainty-labeled",),
            ),
        ),
    )

    violation_evidence = EvidenceRef(
        evidence_key="constraint-observation",
        kind=EvidenceKind.OBSERVATION,
        disposition=EvidenceDisposition.SUPPORTS,
        summary="The fixture changed a path declared immutable.",
        reference="observation:constraint-violation",
    )
    violation = AcceptanceRequest(
        evaluation_id=f"{stem}:violation",
        task_id="calibration-violation",
        objective="Explicit constraint violation blocks acceptance.",
        idempotency_key=f"{stem}:violation:v1",
        evidence=(violation_evidence,),
        claims=(),
        criteria=(
            CriterionAssessment(
                criterion_key="deliverable-shape",
                description="Deliverable shape is otherwise complete.",
                required=True,
                verdict=CriterionVerdict.PASS,
                evidence_keys=("constraint-observation",),
            ),
        ),
        constraints=(
            ConstraintFinding(
                constraint_key="immutable-path",
                description="Do not modify the immutable path.",
                violated=True,
                evidence_keys=("constraint-observation",),
            ),
        ),
    )

    supporting = EvidenceRef(
        evidence_key="alternative-a",
        kind=EvidenceKind.PRIMARY_SOURCE,
        disposition=EvidenceDisposition.SUPPORTS,
        summary="Primary source supports alternative A.",
        reference="source:alternative-a",
    )
    contradicting = EvidenceRef(
        evidence_key="alternative-b",
        kind=EvidenceKind.PRIMARY_SOURCE,
        disposition=EvidenceDisposition.CONTRADICTS,
        summary="A second legitimate source supports incompatible alternative B.",
        reference="source:alternative-b",
    )
    disagreement = AcceptanceRequest(
        evaluation_id=f"{stem}:disagreement",
        task_id="calibration-disagreement",
        objective="Legitimate disagreement is not converted into consensus.",
        idempotency_key=f"{stem}:disagreement:v1",
        evidence=(supporting, contradicting),
        claims=(
            ClaimAssessment(
                claim_key="alternatives",
                statement="Alternative A is preferable.",
                truth_label=TruthLabel.DISPUTED,
                evidence_keys=("alternative-a", "alternative-b"),
                rationale="Authoritative fixtures support incompatible alternatives.",
            ),
        ),
        criteria=(
            CriterionAssessment(
                criterion_key="select-alternative",
                description="Select one supported alternative.",
                required=True,
                verdict=CriterionVerdict.DISPUTED,
                evidence_keys=("alternative-a", "alternative-b"),
                unresolved_action=AcceptanceOutcome.HUMAN_DECISION,
            ),
        ),
    )
    return complete, incomplete, uncertainty, violation, disagreement
