# Phase 8 Live Canary Brief

## Context

This is a deliberately small first live canary. Its purpose is to measure the
governed provider path, output quality, schema reliability, cost accounting,
and review agreement before Phase 9 hardening.

## Goal

Create a concise reusable operating brief for reviewing a physical packaging
sample before approving it for a larger production test.

## Acceptance Criteria

- `deliverable-exists`: The declared Markdown brief exists.
- `required-sections`: The brief contains every required content section.
- `actionable-summary`: The brief gives a practical review sequence, measurable checks, and a clear decision record.
- `uncertainty-visible`: The brief labels assumptions and information that must be confirmed.

## Deliverables

- `outputs/phase8_live_canary_brief.md`: One concise Markdown operating brief.

## Required Content

- Sample identification
- Material and construction checks
- Dimension and fit checks
- Print and artwork review
- Test observations
- Decision record
- Assumptions and open questions

## Constraints

- `workspace-confined`: Write only within the project workspace.
- `declared-artifact-only`: Write only the declared Markdown deliverable.
- `no-external-side-effects`: Do not contact or modify an external system other than the approved model providers.

## Out of Scope

- Supplier research
- Claims about a real packaging sample
- Shell commands or code execution
- Email, repository, or other external mutations
- Production approval

## Execution Policy

- Profile: `governed-live-v1`
- Authority: `live-network`
- Budget USD: `0.50`
- Max tasks: `2`
- Max iterations: `4`
- Max no progress: `1`
- Max runtime seconds: `300`
