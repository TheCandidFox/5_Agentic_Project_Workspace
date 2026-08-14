# Phase 9 Recovery Canary

## Context

The first Phase 8 live canary completed its composer call and preserved a valid Markdown artifact, but the reviewer reached its output-token limit and returned an invalid truncated JSON envelope. Phase 9 must prove that this known, measured response failure can be terminally recorded, charged to the project, retried once at the reviewer boundary, and resumed without redispatching the completed composer.

## Goal

Create and independently review a concise recovery runbook that explains how a bounded multi-provider project preserves completed work, classifies a token-truncated review, retries only the failed reviewer within policy, exposes diagnostics and cost, and shows the operator how the recovery advances the overall goal.

## Acceptance Criteria

- `deliverable-exists`: The declared Markdown recovery runbook exists and is non-empty.
- `required-sections`: The runbook contains every required content section as a level-two Markdown heading.
- `completed-work-preserved`: The runbook clearly prevents redispatch or mutation of successfully completed composer work.
- `known-failure-classified`: A measured max-token response is distinguished from an ambiguous transport or dispatch failure.
- `bounded-retry-visible`: The reviewer-only retry has an explicit attempt limit, remaining-budget gate, and human escalation condition.
- `cost-complete`: Failed-but-billable calls are included in project cost and shown separately from successful task cost.
- `diagnostic-actionable`: The diagnostic record identifies run, task, attempt, route, hashes, stop reason, safe error context, and exact recovery action.
- `status-actionable`: The five-segment view states the overall goal, active segment, completed work, blocked work, and next action.

## Deliverables

- `outputs/phase9_recovery_canary_runbook.md`: One bounded Markdown recovery runbook.

## Required Content

- Overall Goal
- Preserved Work
- Failure Classification
- Reviewer-Only Retry Plan
- Complete Cost Accounting
- Diagnostic Bundle
- Five-Segment Operator Status
- Human Escalation

## Constraints

- `workspace-confined`: Write only within the project workspace.
- `declared-artifact-only`: Write only the declared Markdown deliverable.
- `no-external-side-effects`: Do not contact or modify an external system other than the approved model providers.
- `no-composer-redispatch`: A reviewer recovery must reuse the preserved composer artifact without another composer call.
- `single-reviewer-retry`: At most one additional reviewer attempt may be authorized for a known token-truncation failure.

## Out of Scope

- Replaying or mutating the preserved Phase 8 live run
- Automatically retrying ambiguous transport failures
- Increasing project authority, routes, or budget during recovery
- Implementing selectable collaboration profiles
- Web research, code execution, email, repository pushes, or other external mutations

## Execution Policy

- Profile: `governed-live-v2`
- Authority: `live-network`
- Budget USD: `0.50`
- Max tasks: `2`
- Max iterations: `4`
- Max no progress: `2`
- Max runtime seconds: `300`
