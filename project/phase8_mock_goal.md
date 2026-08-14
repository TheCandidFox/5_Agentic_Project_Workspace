# Simulated Phase 8 Canary Brief

## Context

This synthetic contract exercises the governed provider path with an injected
offline fixture. It does not call a model or require current facts.

## Goal

Create a concise operating brief for reviewing a fictional packaging sample.

## Acceptance Criteria

- `deliverable-exists`: The declared Markdown brief exists.
- `required-sections`: The brief contains every required content section.
- `actionable-summary`: The brief gives a clear review sequence and decision record.

## Deliverables

- `outputs/phase8_mock_canary_brief.md`: One concise Markdown operating brief.

## Required Content

- Sample identification
- Visual inspection
- Dimension checks
- Print review
- Decision record

## Constraints

- `workspace-confined`: Write only within the project workspace.
- `declared-artifact-only`: Write only the declared Markdown deliverable.
- `no-external-side-effects`: Do not contact or modify an external system.

## Out of Scope

- Live provider calls
- Current supplier research
- Shell commands
- External writes

## Execution Policy

- Profile: `governed-live-v1`
- Authority: `live-network`
- Budget USD: `0.50`
- Max tasks: `2`
- Max iterations: `4`
- Max no progress: `1`
- Max runtime seconds: `300`
