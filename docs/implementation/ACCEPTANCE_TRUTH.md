# Acceptance and Truth Governance — Phase 6 Tranche B

**Status:** implemented and verified offline
**Semantic/model judge:** none
**Provider calls:** none

## Purpose

`acceptance_truth.py` provides deterministic application-owned governance for
evidence, claims, acceptance criteria, and hard constraints. It does not ask a
model to decide whether its own output is correct.

The module separates two questions:

1. What truth posture is structurally warranted by the referenced evidence?
2. What project action follows from criterion and constraint results?

## Truth labels

Supported labels are:

- `VERIFIED`;
- `SUPPORTED`;
- `INFERRED`;
- `DISPUTED`;
- `UNKNOWN`.

Evidence has a type and a disposition. Types include deterministic validation,
observed results, primary sources, corroborated sources, semantic review, and
human decisions. Dispositions are `SUPPORTS`, `CONTRADICTS`, or `NEUTRAL`.

The engine enforces these structural invariants:

- `VERIFIED` requires uncontradicted positive deterministic, observed,
  primary-source, or human evidence;
- `SUPPORTED` requires uncontradicted positive evidence;
- `INFERRED` requires an explicit rationale and cannot conceal contradicting
  evidence;
- `DISPUTED` requires both supporting and contradicting evidence;
- `UNKNOWN` remains permitted when available evidence is insufficient.

Semantic-review or model-agreement evidence alone cannot produce `VERIFIED`.
The engine validates the evidence graph; it does not claim to determine the
meaning or correctness of an arbitrary statement without an authorized
validator or human.

## Acceptance outcomes

Supported outcomes are:

- `PASS`;
- `REPAIR`;
- `BLOCK`;
- `HUMAN_DECISION`;
- `DEFER`.

Aggregation order is fixed:

1. any evidenced hard-constraint violation → `BLOCK`;
2. any failed required criterion → `REPAIR`;
3. any required `UNKNOWN`, `DISPUTED`, or `NOT_APPLICABLE` criterion → its
   declared `HUMAN_DECISION` or `DEFER` action;
4. otherwise → `PASS`.

Optional uncertainty may remain labeled without blocking an otherwise
complete deliverable. A required passing criterion must have uncontradicted
support. A failed criterion must have contradicting evidence. A disputed
criterion must preserve evidence on both sides.

## Durable state

Migration `0005_acceptance_truth` adds:

- `acceptance_runs`;
- `acceptance_evidence`;
- `acceptance_claims`;
- `acceptance_criteria`;
- `acceptance_constraints`.

Every evaluation has a complete request fingerprint and idempotency key.
Reusing the key for changed semantics fails closed. Completed evaluations
replay from SQLite. Deterministic work left in `evaluating` can be safely
recomputed; failed evaluations require new reviewed intent.

Stored records contain evidence identities, types, dispositions, references,
labels, criteria, constraints, and aggregate outcomes. Compact events contain
counts and outcomes, not source bodies, prompts, credentials, or machine paths.

## Controlled calibration

`run_acceptance_calibration()` runs the fixed five-case set twice:

1. known complete → `PASS`;
2. known incomplete → `REPAIR`;
3. honestly labeled uncertainty → `PASS` while retaining `UNKNOWN`;
4. hard-constraint violation → `BLOCK`;
5. legitimate disagreement → `HUMAN_DECISION`.

The calibration passes only when both rounds exactly match the expected
outcomes. It does not add cases, ask a judge to reconsider unchanged evidence,
or recursively validate itself.

## Deliberate limitations

1. Structural evidence eligibility is not semantic fact checking.
2. Evidence references are durable identifiers; the caller is responsible for
   linking them to governed validation, research, observation, or human records.
3. All recorded constraints in this bootstrap abstraction are hard constraints.
   Preferred/soft constraints belong in the later project-contract model.
4. Criterion construction remains an application/contract responsibility. A
   weak criterion can still produce a weak acceptance decision.
5. Semantic reviewers and human decision workflows are represented as evidence
   types but are not invoked by this offline phase.
