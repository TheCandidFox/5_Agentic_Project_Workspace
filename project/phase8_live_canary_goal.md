# Phase 8 Live Canary: Resumable Catalog Comparison Blueprint

## Context

This live canary evaluates whether a governed composer and independent reviewer can turn a bounded product idea into a coherent, implementation-ready execution blueprint. The scenario is synthetic and intentionally resembles a useful future workload without requiring web research, code execution, or access to private business data. The result will be used to identify Phase 9 needs in planning quality, delegation, handoff completeness, acceptance judgment, recovery context, cost, latency, and operator visibility.

## Goal

Create a concise but implementation-ready overnight execution blueprint for a portable Python tool named Catalog Compare. The future tool will compare an active-catalog CSV with a candidate-catalog CSV by normalized SKU, identify candidate SKUs missing from the active catalog, and write a Markdown report without modifying either input. The blueprint must show how bounded AI roles could plan, implement, validate, review, checkpoint, and safely resume this work while keeping assumptions, human decisions, evidence, and acceptance requirements traceable.

## Acceptance Criteria

- `deliverable-exists`: The declared Markdown blueprint exists and is non-empty.
- `required-sections`: The blueprint contains every required content section as a level-two Markdown heading.
- `objective-fidelity`: The plan remains focused on the synthetic Catalog Compare objective and does not claim that implementation or external research occurred.
- `executable-backlog`: The backlog uses stable task identifiers and gives each task an owner role, purpose, inputs, outputs, dependencies, validation, and completion evidence.
- `dependency-coherence`: The execution order is internally consistent, exposes parallelizable work, and prevents dependent work from starting before its prerequisites are complete.
- `acceptance-traceability`: Every stated success condition and deliverable is mapped to one or more tasks, checks, and durable evidence records.
- `ambiguity-visible`: Assumptions, unresolved questions, defaults, and consequences are explicitly separated instead of being silently invented.
- `bounded-authority`: The plan confines work to declared local files, forbids mutation of input CSVs, and identifies actions that would require human approval.
- `resume-sufficiency`: The failure plan and continuation capsule contain enough state, direction, decisions, artifact references, and next actions for a different worker to resume without repeating completed work.
- `human-gates-visible`: Human decisions and escalation conditions identify when work may continue automatically, when it must pause, and what information the human needs.
- `status-visibility`: The five-segment status view relates the current segment to the overall goal and defines objective evidence for segment completion.
- `implementation-readiness`: A developer could begin implementation from the blueprint without first redesigning its file boundaries, fixtures, task order, or acceptance strategy.

## Deliverables

- `outputs/phase8_live_canary_execution_blueprint.md`: One bounded Markdown execution blueprint for the synthetic Catalog Compare project.

## Required Content

- Overall Goal and Success Definition
- Assumptions and Unresolved Questions
- Deliverables and File Boundaries
- Task Backlog
- Dependencies and Execution Order
- AI Roles and Handoff Protocol
- Acceptance Traceability Matrix
- Test Fixtures and Edge Cases
- Human Decisions and Escalation Gates
- Failure and Recovery Plan
- Continuation and Handoff Capsule
- Five-Segment Status View
- Recommended Next Action

## Constraints

- `workspace-confined`: Write only within the project workspace.
- `declared-artifact-only`: Write only the declared Markdown deliverable.
- `no-external-side-effects`: Do not contact or modify an external system other than the approved model providers.
- `synthetic-evidence-only`: Do not browse, use real supplier or catalog data, or present invented test results as observed evidence.
- `input-immutability`: The proposed future tool must treat both input CSV files as read-only and write only declared outputs or checkpoints.

## Out of Scope

- Implementing or executing the Catalog Compare program
- Accessing real catalogs, credentials, repositories, suppliers, or business systems
- Web research or factual claims requiring external verification
- Selecting a new model route or collaboration profile during this run
- Automatically repairing a reviewer rejection
- Multiple implementation artifacts or external mutations

## Execution Policy

- Profile: `governed-live-v1`
- Authority: `live-network`
- Budget USD: `0.50`
- Max tasks: `2`
- Max iterations: `4`
- Max no progress: `1`
- Max runtime seconds: `300`
