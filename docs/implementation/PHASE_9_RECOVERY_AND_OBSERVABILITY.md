# Phase 9 Bounded Recovery and Operator Observability

**Status:** implemented and verified offline

**Recovery profile:** `governed-live-v2`

**Default state:** provider execution disabled

**Installation/test cost:** `$0.00`

## Why Phase 9 exists

The Phase 8 live canary composed a useful artifact, then its reviewer exhausted
the 3,000-token output limit before completing a strict JSON envelope. Phase 8
correctly avoided an automatic repeat, but treated the measured response as
ambiguous, left task state nonterminal, omitted its billable cost from the
project total, and lacked an operator-oriented recovery record.

Phase 9 implements only the recovery needed for that observed failure. It does
not turn retries into a general-purpose loop.

## Failure classification

The gateway now evaluates response identity, usage, cost, and normalized stop
reason before parsing. A response with `max_tokens`, `max_output_tokens`,
`length`, or an equivalent normalized reason becomes
`response-truncated`. Because a provider response and measured usage exist,
this is a known terminal attempt rather than an ambiguous transport state.

Known measured failures record:

- terminal provider-call status and failure kind;
- request identity, usage, cost, latency, stop reason, and response hash;
- a bounded, secret-redacted response excerpt and its independent hash;
- terminal task-dispatch status and a bounded summary;
- billable cost in telemetry and the project run total.

The excerpt is diagnostic evidence, not a parser fallback. Phase 9 never tries
to repair or accept partial JSON.

An exception before a measurable provider response remains
`transport-ambiguous`. It is not eligible for automatic retry because the
system cannot prove whether the provider executed the request.

## Retry policy

`governed-live-v2` compiles the same two-task DAG as Phase 8:

1. `compose-markdown`, one attempt;
2. `review-markdown`, at most two attempts.

Only a structured failed task result marked retryable can consume the second
reviewer attempt. In this release, the provider gateway marks only
`response-truncated` retryable. Schema errors, identity drift, invalid usage,
cost violations, unsuccessful acceptance, and ambiguous transport state do not
qualify.

The composer artifact is written once. A reviewer failure carries no artifact,
and its retry reads the existing artifact through `DeclaredArtifactWriter`.
Tests verify the artifact hash and composer call count remain unchanged.

## Controlled pause and process restart

The kernel can be configured to pause after recording a known retryable
failure. The pause is durable and uses stop reason
`retryable-failure-paused`. Before explicit resume, the new process verifies:

- the stored run is in that exact controlled pause state;
- no task dispatch remains `claiming`, `dispatching`, or `running`;
- the task graph and contract identities still match;
- remaining attempts and project bounds still permit work.

Resume resets the bounded runtime deadline, records `project_run_resumed`, and
continues from the ready reviewer task. It does not replan or redispatch the
completed composer. Other paused, failed, blocked, or recovery-required states
are not made resumable by this mechanism.

## Prompt and token hardening

The Phase 9 reviewer prompt requires a single compact JSON object, one concise
rationale per item (at most 240 characters), and overall notes capped at 600
characters. It explicitly forbids repetition of the contract or artifact.
The default reviewer maximum rises from 3,000 to 5,000 output tokens. Both the
prompt-template version and token limit are included in the approval
fingerprint.

The higher ceiling is a bounded safety margin, not a completion guarantee. A
second truncation exhausts the reviewer task and stops the run.

## Diagnostics and progress

`run_diagnostics.py` creates an atomic JSON bundle below `logs/`. It includes:

- run policy and terminal state;
- backlog tasks and task dispatches;
- provider call status, classification, usage, cost, latency, and hashes;
- declared artifact identity;
- acceptance result and durable event sequence;
- provider total, project total, and any accounting difference;
- five goal-relative segments and recommended operator actions.

Raw prompts and validated/full provider response JSON are excluded. Response
excerpts remain bounded and redacted. Environment values and API keys are not
read.

The runner also prints five segments: govern, plan, compose, verify, and accept.
Each line connects the current step to the contract's overall goal. This is a
terminal foundation for a future UI rather than the requested final dashboard.

## Offline recovery proof

```powershell
python run_phase9.py --recovery-canary
```

The fixture reproduces the measured Phase 8 sequence: composer success,
reviewer stop at 3,000 output tokens, and then a schema-valid reviewer retry.
It exercises the same gateway, ledger, kernel, acceptance engine, and
diagnostics path with external cost `$0.00`. A repeat command must be a
completed replay with zero new calls.

Separate tests pause after the known reviewer failure, construct a new kernel
and client, resume explicitly, and prove that only reviewer attempt two is
dispatched.

## Current boundary

Phase 9 provides one precise recovery policy and inspectable status. It does
not yet support automatic artifact revision, dynamic DAGs, arbitrary tools,
multi-deliverable work, provider research, multi-agent debates, general
consensus, or unattended live operation. Those features require additional
contracts, evaluators, and safety gates rather than expanding this retry rule.
