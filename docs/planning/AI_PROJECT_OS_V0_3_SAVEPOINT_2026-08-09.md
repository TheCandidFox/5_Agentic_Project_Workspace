# AI Project Operating System — Local v0.3 Save Point

**Checkpoint date:** August 9, 2026  
**Status:** Requirements sufficiently defined to begin local v0.3 bootstrap work  
**Purpose:** Resume development without reconstructing the prior discussion.

---

## 1. Current State

A known-good **local v0.2 durable orchestrator** has been built, tested, and frozen separately.

The frozen v0.2 system has demonstrated:

- Four-stage OpenAI → Anthropic → OpenAI → Anthropic execution.
- Durable SQLite task/step state.
- Telemetry and estimated cost tracking.
- Per-task idempotency.
- Resume without duplicate paid work.
- Pre-dispatch budget denial.
- Recovery from a genuine mid-run provider failure.
- Sensitive-data blocking in the current local version.
- Local lexical + Python AST/symbol retrieval.
- Controlled validator calibration from prior v0.2.x work.

Validated live behavior included:

- Same completed task rerun: all four stages reused; no new API calls.
- Zero-budget new task: denied before provider dispatch.
- Intentional Anthropic model failure after stage 1: stage 1 remained checkpointed and was reused on rerun.
- Recovery test finished with exactly four successful provider telemetry rows despite five budget reservations.

The known-good v0.2 folder/ZIP must remain untouched.

---

## 2. Development Strategy

Do **not** replace v0.2.

Use:

1. Frozen v0.2 as the known-good reference.
2. A separate `v0.3_candidate` working copy.
3. Prefer local Git inside the candidate folder for checkpoints, branches, diffs, and rollback.
4. GitHub is optional and deferred; local Git is sufficient for the first candidate.
5. Human approval is required before a candidate becomes the new known-good version.
6. Cloud deployment is deferred until the local candidate is proven against representative workloads.

---

## 3. North Star

The desired system should feel less like submitting isolated AI jobs and more like managing competent collaborators.

The user should be able to define and bound a project, leave, and have the system:

- continue useful work;
- choose eligible work from a backlog;
- research what it needs;
- execute what it is authorized to execute;
- observe failures;
- repair or adapt within limits;
- preserve state;
- verify progress;
- avoid catastrophic changes;
- expose blockers rather than stalling the entire session;
- remain inside cost/authority boundaries;
- produce evidence and artifacts;
- explain what happened when the user returns.

Longer-term, the user should be able to check progress remotely from a phone or normal ChatGPT/Claude interface.

---

## 4. Memory Decision — Question 17

### Policy

Err toward **remembering too much**, not too little.

Storage is currently cheaper than rediscovery.

### Memory Classes

1. **Canonical**
2. **Working Memory**
3. **Archive**
4. **Ephemeral**

Canonical includes project contracts, acceptance criteria, explicit user decisions, source-of-truth declarations, verified behavior, architectural decisions, reusable code/knowledge, and final artifacts.

Working Memory includes current hypotheses, task notes, recent handoffs, intermediate research, unresolved questions, and active summaries.

Archive includes raw model responses, superseded plans, old implementation attempts, detailed logs, raw API responses, and failed experiments that may matter later.

Ephemeral includes repetitive searches, duplicate reasoning, transient formatting steps, and clearly redundant scratch material.

### Critical distinction

**Stored does not mean trusted.**  
**Stored does not mean loaded into model context.**

Persistence policy and context/retrieval policy must remain separate.

### Knowledge trust metadata

Durable knowledge should eventually carry metadata such as:

- source/provenance;
- creation date;
- project;
- status: unverified / supported / verified / disputed / superseded;
- confidence;
- version/applicable date;
- last checked;
- memory class.

### Periodic health review

A future health process should classify retained information as:

- KEEP
- COMPRESS
- ARCHIVE
- PROMOTE
- INVESTIGATE
- DELETE-CANDIDATE

Deletion should initially be conservative and preferably human-reviewed.

---

## 5. Plan-Rewrite Decision — Question 18

Agents have **broad authority below the goal/constraint layer**.

They may autonomously:

- add tasks;
- split tasks;
- merge tasks;
- reorder tasks;
- remove/deprioritize tasks;
- discover dependencies;
- replace tactics;
- revise estimates;
- create new backlog items.

They may do so when changes remain connected to the parent goal and stay within budget, authority, and explicit constraints.

### Explicit human instructions are hard boundaries

If the user explicitly says, for example:

> Use AWS Lambda.

The agents may not silently switch the implementation to Fargate.

If strong evidence suggests the explicit instruction is materially inferior, the system should:

1. preserve the evidence;
2. define comparison metrics;
3. continue eligible work that does not violate the explicit instruction;
4. create a human-decision/backlog item;
5. surface the issue at the next user check-in;
6. wait for explicit authorization before changing the hard instruction.

The general rule is:

- **Backlog authority:** broad.
- **Goal authority:** restricted.
- **Explicit constraints:** immutable until the user changes them.

---

## 6. New Core Requirements Added

### Conversational status access

Eventually the user should be able to ask from a phone, ChatGPT, Claude, or dashboard:

- What are you doing now?
- What has finished?
- What is blocked?
- What did you find?
- Show me artifact X.
- How much has this cost?
- How much budget remains?
- What will you work on next?

Answers should come from external canonical project state, not from a single chat history.

### Autonomous terminal/repair loop

For authorized local development work, the system should eventually be able to:

1. run a command;
2. capture stdout/stderr/exit code;
3. interpret the failure;
4. inspect relevant files/config;
5. form a repair hypothesis;
6. patch candidate files;
7. rerun the command/test;
8. determine whether the repair worked;
9. iterate within bounded retry/time/cost limits;
10. preserve checkpoints and escalate rather than loop forever.

### Cost-aware model routing

Models should be chosen by expected capability, reliability, context/tool needs, latency, cost, and prior performance.

Use the least expensive approach expected to satisfy the task's required quality.

Do not assume every task needs multiple LLMs.

### Pre-run forecasts

Before substantial work, estimate:

- likely runtime;
- expected cost;
- low/high range;
- major uncertainty;
- expected model/tool usage;
- expected verification cost.

The previous `$150/month` figure is a **default operating target**, not an absolute ceiling.

High-value projects may receive explicit project-level budget overrides.

### Validation and truth governance

No individual LLM is truth.

The system should prefer:

1. deterministic/reproducible evidence;
2. authoritative primary sources;
3. observed experiments;
4. corroborated evidence;
5. independent semantic review;
6. reasoned inference;
7. explicit UNKNOWN/human decision when evidence remains insufficient.

Truth labels:

- VERIFIED
- SUPPORTED
- INFERRED
- DISPUTED
- UNKNOWN

Agreement between two LLMs does **not** automatically mean VERIFIED.

### Version control

For candidate development:

- use separate candidate workspace;
- use local Git when practical;
- create commits/checkpoints;
- inspect diffs;
- revert bad changes;
- preserve known-good states;
- do not automatically merge candidate work into the approved baseline.

### Continuous improvement

The system should learn from validator failures, recurring errors, repair procedures, model/provider performance, cost behavior, task decomposition, and stopping behavior.

But operational code should not rewrite itself merely because an LLM suggested a change.

Improvement flow:

`Observation → Lesson Candidate → Proposed Change → Controlled Test → Regression Suite → Promotion`

Over-refinement is itself a failure mode.

---

## 7. Local v0.3 Definition of Success

Do not optimize specifically for the user's next Excel project.

The local candidate should demonstrate general capability across several workload types.

A successful local candidate should be able to:

1. accept a Markdown project contract;
2. parse goal, deliverables, hard constraints, permissions, and stopping rules;
3. create and revise a backlog;
4. select an execution strategy;
5. select models/tools based on task and cost;
6. execute permitted local commands/tools;
7. observe failures without manual terminal copy/paste;
8. attempt bounded repair;
9. run validation;
10. classify evidence/truth;
11. preserve checkpoints;
12. recover from interruption;
13. respect budget and authority;
14. create artifacts/evidence;
15. stop/escalate instead of endlessly looping;
16. produce a useful status/morning report.

Capabilities that inherently require a cloud control plane may remain research/design outputs, provided the local architecture is designed so those capabilities can be added without a fundamental rewrite.

---

## 8. Five-Benchmark Acceptance Strategy

Run **five and only five** small, varied benchmark projects before calling the local candidate ready for the real workbook project.

Suggested benchmark families:

1. **Code repair**
2. **Structured data**
3. **Bounded technical research**
4. **Planning under explicit constraints**
5. **Adaptive topology + validator benchmark**

### Interpretation

- 5/5: strong candidate for real out-of-sample workbook test.
- 3–4/5: preserve candidate, diagnose failures, human review before more work.
- 0–2/5: architecture requires material revision.

Do not keep spending indefinitely to force all five to pass.

The user's real Excel/macro-analysis project should remain **out-of-sample** until after this benchmark suite.

---

## 9. Tonight / Next Session Plan

### Before overnight run

1. Create `v0.3_candidate` from frozen v0.2.
2. Add the minimal bootstrap layer described in the companion bootstrap design.
3. Run bootstrap tests.
4. Re-review the overnight contract after the bootstrap exists.
5. Estimate expected duration and cost.
6. User supplies/approves OpenAI and Anthropic budget ceilings with safety margins.
7. Launch the overnight contract.

### Overnight run

Research broadly, implement conservatively.

### Cloud

Do not deploy the canonical system to cloud during this phase.

Research and architecture for cloud are allowed.

Actual cloud migration follows successful local validation.

---

## 10. Unresolved Inputs for Tomorrow

These are intentionally not guessed:

- Exact OpenAI API balance available.
- Exact Anthropic API balance available.
- Safety reserve to leave in each account.
- Final project-level hard budget ceiling.
- Whether the bootstrap implementation changes any requirements in the overnight contract.
- Exact benchmark task contents generated for the five-test suite.
- Whether any additional provider should actually be implemented after current research.

---

## 11. Resume Instruction

When this file is provided to a future session:

1. Do not restart requirements discovery.
2. Treat frozen local v0.2 as known-good and immutable.
3. Review the companion bootstrap design.
4. Build/test the local bootstrap layer in a separate v0.3 candidate workspace.
5. Re-review the overnight contract after bootstrap implementation.
6. Estimate cost/duration.
7. Obtain user budget authorization.
8. Run the overnight contract.
9. Preserve results for morning review.
10. Keep the user's real Excel project out-of-sample until the candidate has completed the controlled benchmark suite.
