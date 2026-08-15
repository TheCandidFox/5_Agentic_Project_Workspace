# Future Autonomous Execution and Trajectory Interfaces

## Preserved product requirement

A later phase must remove routine terminal transcription from supervised and
overnight work. The system should execute previously authorized commands,
capture their results, evaluate deterministic evidence, and continue when the
result is unambiguous. Human involvement remains mandatory for changed goals,
expanded authority, destructive actions, ambiguous dispatch, disputed intent,
and material product-direction choices.

A separate trajectory-stabilization role should periodically challenge the
plan, surface blocking questions, and recommend useful features. Nonblocking
recommendations enter a future-work queue and do not expand the active goal.
Blocking questions pause at a state-bound human gate.

## Dormant versioned interfaces

- `CommandExecutionRequest.v1`
- `CommandEvidence.v1`
- `TrajectoryReview.v1`
- `FeatureRecommendation.v1`
- `BlockingQuestion.v1`
- `HumanDecisionRequired.v1`

Phase 10 validates the names, versions, and strict envelope boundaries only.
It does not activate autonomous shell execution, dynamic planning, background
operation, or provider-authored authority.

## Later implementation constraints

Command execution must remain confined to approved executable aliases,
arguments, working directories, timeouts, output limits, idempotency keys, and
authority fingerprints. Output is untrusted evidence until validated and
redacted. Trajectory review may recommend but never silently modify the active
contract, budget, providers, tools, deliverables, or acceptance criteria.
