# EMPIRICAL_EVAL_PLAN

## 1. Purpose and Decision Scope

This plan defines the empirical evaluations required to choose model, provider, retrieval, review, and routing policies for the persistent multi-model work system. It is deliberately workload-specific: generic coding, reasoning, or leaderboard benchmarks may inform candidate selection, but they must not determine production routing defaults.

The evaluation objective is to identify the **lowest-complexity routing policy that meets acceptance targets** for the user’s highest-priority work:

1. Coding/software
2. Automations and integrations
3. Web research and investigation
4. Structured data and spreadsheets
5. Document generation
6. Lower-priority strategy and image work, evaluated only when a real workload trigger exists

The primary comparison is:

- **VALUE architecture:** quality-per-dollar near a $150/month API target.
- **QUALITY-MAX architecture:** highest defensible output quality, with cost measured but not treated as the primary constraint.

This plan does not assume that a more expensive model, a cross-provider reviewer, a retrieval system, or an agent framework improves outcomes. Each is a hypothesis to test against representative tasks, objective evidence, measured cost, latency, reliability, and human repair effort.

All current evaluation data must use non-sensitive or purpose-built synthetic data. Until a provider-by-feature retention and data-classification matrix is verified at implementation time, no sensitive data is eligible for these tests.

---

## 2. Evaluation Principles and Experimental Controls

### 2.1 Core principles

1. **Use representative held-out work.** Tasks must resemble actual repositories, APIs, research questions, spreadsheets, and documents the user expects to handle. Do not use vendor demonstrations or benchmark prompts as the primary score source.

2. **Measure accepted outcomes, not eloquence.** A response counts as successful only when it passes the task’s defined acceptance criteria. A polished explanation with a broken patch, unsupported citation, invalid workflow, or incorrect spreadsheet result is a failure.

3. **Separate generation from verification.** Whenever possible, evaluate:
   - primary model output,
   - deterministic verification,
   - reviewer verdict,
   - human reference verdict.
   
   This allows measurement of reviewer false acceptance and false rejection rather than treating a model judge as ground truth.

4. **Keep candidate conditions comparable.** Use the same task contract, allowed tools, time limit, retrieval corpus, context packet, acceptance criteria, and maximum output constraints for all candidate models unless the experiment explicitly evaluates one of those variables.

5. **Evaluate routing policies, not only models.** The candidate unit is usually a route such as:
   - economy model → deterministic checks → escalate on failure;
   - mid-tier model → deterministic checks;
   - flagship model → independent provider review;
   - specialist research endpoint → citation verification.
   
   A flagship model may be best in isolation but lose on accepted-task cost once a cheaper cascade is considered.

6. **Use a live provider registry.** Candidate model IDs, capability flags, pricing, batch eligibility, tool availability, and retention constraints must be read from a dated registry at run time. No evaluation result should be generalized across materially different model versions or pricing configurations.

7. **Treat provider claims and generic benchmarks as candidate-generation evidence only.** They can justify adding a model to the evaluation pool, not granting it a default route.

### 2.2 Required run metadata

Every evaluation run must persist the following in the provider-neutral task ledger:

```json
{
  "eval_run_id": "EVAL-2026-001",
  "task_id": "CODE-017",
  "task_contract_version": "CODE-017.v1",
  "task_type": "coding",
  "difficulty_band": "standard|hard|critical",
  "provider": "provider_name",
  "requested_model": "exact_model_id",
  "served_model": "if exposed by provider",
  "access_path": "direct|aggregator|cloud_partner",
  "prompt_template_version": "sha256-or-semver",
  "tool_schema_version": "sha256-or-semver",
  "retrieval_mode": "none|lexical_ast|provider_file_search|owned_rag|web_search|hybrid",
  "corpus_snapshot_hash": "hash",
  "input_tokens": 0,
  "cache_write_tokens": 0,
  "cache_read_tokens": 0,
  "output_tokens": 0,
  "reasoning_tokens": 0,
  "tool_calls": [],
  "estimated_cost_usd": 0.0,
  "billed_cost_usd": 0.0,
  "latency_ms": 0,
  "retries": 0,
  "error_class": null,
  "acceptance_result": "pass|fail|partial|human_review",
  "reviewer_result": "accept|reject|uncertain",
  "human_repair_minutes": 0
}
```

`billed_cost_usd` is authoritative where invoice or usage data is available. Estimated cost is retained for admission-control and route-selection analysis. Differences between estimated and billed cost are themselves an evaluation metric.

### 2.3 Fairness and repeatability controls

- Pin repository commit, fixture data, source snapshots, tool versions, and task instructions.
- Record retrieval result IDs, text chunks, URL snapshots, and source access timestamps.
- Disable uncontrolled memory carryover between tasks unless testing persistent memory specifically.
- Run at least one repeat for nondeterministic tasks; use more repeats for close routing decisions.
- Randomize task order and model order where provider rate limits permit.
- Do not reveal the original answer to an independent reviewer when blind review is feasible.
- Keep external side effects sandboxed. No production deployment, purchase, credential change, external communication, or destructive integration action is permitted during baseline evaluation.

---

## 3. Representative Benchmark Suite

The initial suite should contain **40–60 held-out tasks**, stratified by workload priority and difficulty. A smaller smoke suite may be used first to validate the harness, but it cannot determine production routing.

### 3.1 Coding and software evaluation

Coding receives the largest evaluation allocation because it is the highest-priority workload and has strong objective acceptance mechanisms.

| Task family | Representative task | Acceptance criteria | Primary measurements |
|---|---|---|---|
| Multi-file bug fix | Diagnose and repair a failing behavior across 3–8 files | Existing and added tests pass; no regression; minimal relevant diff | acceptance rate, tests passed, diff quality, repair minutes |
| Feature implementation | Add a bounded feature with API and unit-test requirements | Required tests pass; interface contract preserved; lint/type checks pass | accepted-task cost, tool reliability, latency |
| Refactor | Extract/restructure a component without behavior change | Full test suite passes; complexity or duplication target met | unnecessary-change rate, regression rate |
| Debugging from logs | Identify root cause from logs, stack trace, and repo context | Cause matches seeded defect; fix or repro is valid | retrieval correctness, diagnosis accuracy |
| Repository investigation | Answer “where/how is this behavior implemented?” | Correct file/symbol/call-path citations | AST/lexical retrieval recall and precision |
| Security-adjacent code review | Find seeded unsafe patterns in authorized test code | Precision/recall against seeded findings; no unsupported claims | reviewer value, false-negative rate |

Each coding task should include a known baseline implementation or a human-validated acceptance packet. For patch tasks, acceptance is not complete until code executes in a sandbox and the required tests, linting, static analysis, and schema checks run successfully.

**Coding retrieval experiment:** Compare at minimum:

1. full relevant-file context selected manually;
2. lexical search + AST/symbol retrieval;
3. lexical/AST retrieval plus selective semantic document retrieval;
4. Graphify or equivalent code graph, if the Graphify pilot is enabled.

Graphify remains a pilot candidate only. Its code-graph claims, local-only behavior, semantic-mode egress behavior, and retrieval advantage over grep plus AST lookup require direct measurement on actual repositories. It is not a baseline assumption.

### 3.2 Automation and integration evaluation

Automation tasks must measure tool use, state handling, error recovery, and safe execution—not merely whether a model can describe an API.

| Task family | Representative task | Acceptance criteria |
|---|---|---|
| Webhook integration | Build and debug a sandbox webhook receiver and sender | Signature verification, retries, idempotency behavior, test events processed once |
| API workflow | Integrate two sandbox APIs with pagination, rate limits, and mapping | Correct records created/updated; schema validated; no duplicates |
| OAuth-like credential flow | Implement a mocked authorization/token-refresh flow | Credentials never logged; refresh and expiry paths tested |
| Workflow repair | Diagnose a failing existing automation from logs and traces | Root cause correct; retry/backoff behavior valid; tests pass |
| Data synchronization | Reconcile source and destination records | Reconciliation report matches expected truth set; no unintended writes |

Automation evaluation must inject realistic failures: 429 responses, timeouts after remote acceptance, duplicate webhook delivery, malformed payloads, provider 5xx errors, expired credentials, and worker restart. Success requires correct durable recovery, not merely a successful first run.

The harness must separately score:

- tool-call JSON validity;
- API request correctness;
- idempotency and duplicate-write prevention;
- policy compliance;
- recovery after interruption;
- proportion of tasks requiring human repair.

No candidate may receive autonomy credit for proposing an action that would require approval in production. Evaluation execution remains sandboxed and honors the task contract’s effect-class ceiling.

### 3.3 Research and web investigation evaluation

Research quality must be scored by evidence quality and factual support, not prose style or citation count.

Representative tasks should include:

- comparison of current APIs, products, or regulations;
- investigation of a changing technical claim;
- synthesis of conflicting sources;
- research memo that distinguishes fact, provider claim, inference, and uncertainty;
- answer requiring primary-source prioritization;
- narrow competitive or implementation research relevant to coding, automation, or data work.

Each research task requires a source packet or a human-researched reference answer. The scorecard must include:

| Metric | Definition |
|---|---|
| Citation precision | Share of citations that actually support the adjacent claim |
| Citation recall | Share of material factual claims that have adequate citations |
| Primary-source rate | Share of decisive claims supported by official, original, regulatory, or otherwise primary sources |
| Freshness | Whether dated claims meet the task’s stated as-of requirement |
| Contradiction handling | Whether conflicting evidence is surfaced rather than silently flattened |
| Unsupported-claim rate | Material claims with no sufficient source |
| Retrieval provenance | Whether the cited source was actually retrieved and recorded |

Research candidates include general frontier models with web tools, Gemini grounding where eligible, xAI web/X search where eligible, and Perplexity/Sonar as a narrow retrieval specialist. These are evaluated as separate access paths, not assumed equivalent.

Perplexity’s layered pricing and any provider’s web-search tool fees must be recorded as explicit non-token cost fields. The comparison is **cost per accepted evidence-backed memo**, not input/output token cost alone.

### 3.4 Structured data and spreadsheet evaluation

Structured-data tasks should use realistic CSV, XLSX, and database-export fixtures containing seeded edge cases:

- missing values;
- duplicate keys;
- date/time-zone ambiguity;
- mixed currencies or units;
- outliers;
- formula errors;
- inconsistent categories;
- multi-sheet joins.

Representative tasks:

1. Clean and normalize a messy spreadsheet under a documented schema.
2. Produce an analysis with reconciled totals and exception list.
3. Build or repair formulas without altering protected cells.
4. Explain an observed trend while distinguishing correlation from causation.
5. Generate a reproducible transformation script and validation report.

Acceptance must use deterministic checks where possible:

- expected totals and row counts;
- formula evaluation;
- schema validation;
- comparison to a canonical output;
- numeric tolerance thresholds;
- audit trail of transformations.

The main quality metric is **numeric correctness**, not narrative quality. Models that produce plausible explanations but incorrect totals fail.

### 3.5 Document generation evaluation

Document tasks are medium priority and should be tested after coding, automation, research, and data routes are stable.

Representative tasks include:

- technical implementation plan from validated evidence;
- change proposal with risks and rollback plan;
- concise decision memo;
- structured user-facing documentation derived from code and source material.

Acceptance criteria should include required sections, faithful use of supplied evidence, no fabricated citations, consistency with source facts, readability, and format validity. Human scoring may be used here, but reviewers should use a predefined rubric and be blinded to provider identity where practical.

### 3.6 Lower-priority image and strategy evaluation

No specialist image, video, speech, OCR, or strategy provider is added by default. Open a dedicated evaluation only when a trigger occurs:

- core-provider image output fails an agreed quality bar in a real deliverable;
- dense scan or complex table extraction misses the agreed field-accuracy target;
- audio or video becomes a first-class deliverable;
- strategy outputs affect a decision with measurable downstream outcome.

Until then, these categories receive a minimal exploratory test allocation and cannot displace priority-workload evaluation budget.

---

## 4. Quality, Acceptance, and Reviewer Evaluation

### 4.1 Acceptance hierarchy

The following evidence hierarchy governs scoring:

1. **Deterministic execution evidence:** tests, linters, type checks, schema validators, numeric reconciliation, API logs, sandbox state.
2. **Source-grounded evidence:** source snapshots, direct quotes, citation verification, provenance.
3. **Structured human review:** blinded rubric-based review for subjective or ambiguous criteria.
4. **Model reviewer verdict:** useful as triage or a secondary signal, never sole release evidence.

A task is marked:

- **Pass:** all required deterministic and/or rubric criteria met.
- **Partial:** useful output but at least one required criterion missed.
- **Fail:** incorrect, unsupported, unsafe, invalid, or materially incomplete.
- **Human review:** evidence is insufficient to resolve a high-impact or subjective disagreement.

### 4.2 Independent-review value experiment

Cross-provider review is a hypothesis, not a default proof of quality. For a stratified sample of coding, automation, research, and data tasks, compare:

1. deterministic verification only;
2. self-review by the same model;
3. stronger same-provider review;
4. cross-provider review;
5. deterministic verification plus blinded cross-provider review;
6. human reference review.

Measure:

- false acceptance rate: invalid output accepted;
- false rejection rate: valid output rejected;
- defect catch rate;
- added cost and latency;
- reviewer agreement with the human reference;
- reviewer ability to cite concrete evidence.

A reviewer only earns routing value if it lowers false acceptance materially enough to justify its cost and latency for the relevant task/importance band. “Different provider” alone is not evidence of independence.

### 4.3 Confidence and escalation signals

Do not route based solely on model self-reported confidence. Evaluate confidence only as one feature alongside objective evidence:

- test failure;
- invalid schema or tool call;
- retrieval coverage below threshold;
- contradictory source set;
- multiple failed attempts;
- large diff or high dependency count;
- high importance band;
- observed calibration score.

For each model/task type, produce reliability curves comparing reported confidence with actual acceptance. Any confidence threshold used in production must be recalibrated after material model, prompt, tool, or task-distribution changes.

---

## 5. Cost, Latency, Reliability, and Retrieval Correctness

### 5.1 Full cost accounting

Each route must include:

```text
total task cost =
  input token cost
+ cache-write cost
+ cache-read cost
+ output and billed reasoning-token cost
+ web/search request fees
+ file-search/vector storage and retrieval fees
+ container or code-execution fees
+ embedding/indexing cost
+ aggregator fees
+ retry and failed-attempt cost
+ reviewer and adjudication cost
```

Use actual billed records where possible. The evaluator must flag a route if estimated cost differs materially from billed cost, because pricing conflict, hidden reasoning tokens, long-context repricing, tool fees, or caching assumptions can invalidate the budget model.

The unresolved OpenAI economy-tier pricing conflict must be settled with a small billed test before it is used as a $150/month routing input. Likewise, provider pricing, long-context thresholds, cache behavior, batch eligibility, and tool charges must be refreshed before each major evaluation cycle.

### 5.2 Latency measurements

Record:

- queue delay;
- time to first output or first actionable tool call;
- end-to-end completion time;
- deterministic verification time;
- reviewer completion time;
- retry and recovery time;
- p50, p95, and p99 latency by route.

For interactive work, measure user-visible completion time. For deferrable work, measure deadline compliance and total cost. Batch is eligible only for independent, non-interactive, non-sensitive map-stage work; it is not a substitute for a multi-turn agent loop.

### 5.3 Reliability and recovery tests

Every candidate route used for long-running work must pass fault injection:

- provider timeout after request submission;
- provider 429 and 5xx;
- duplicate or delayed webhook;
- worker crash before and after dispatch recording;
- database restart;
- network loss;
- expired worker lease;
- context limit reached;
- task pause and resume after at least 24 hours;
- budget reserve exhaustion;
- duplicate tool-delivery attempt.

Success criteria:

- no duplicate external sandbox writes;
- no lost completed result;
- no silent budget breach;
- idempotent state recovery;
- bounded retry count;
- clear transition to human review when recovery is unsafe.

### 5.4 Retrieval correctness evaluation

Retrieval is successful only if the system actually used relevant evidence and accurately represented it.

For each retrieval-required task, measure:

- **Recall@k:** whether the needed source, file, symbol, or chunk appeared in the retrieved set.
- **Precision@k:** proportion of retrieved items relevant to the task.
- **Grounded-answer rate:** accepted answers whose material claims are traceable to retrieved evidence.
- **Citation entailment:** whether cited passages support the claimed conclusion.
- **Provenance completeness:** source/version/hash retained for each material claim.
- **Retrieval-use compliance:** whether the model received and cited retrieved evidence rather than answering from unsupported prior knowledge.
- **Context efficiency:** retrieved tokens and cost per accepted answer.

For internal-plus-web research, test two-pass retrieval explicitly when a provider cannot combine internal file search and live web grounding in one request. The orchestrator, not the model, must preserve provenance and merge the evidence packets.

---

## 6. Routing Experiments and Decision Rules

### 6.1 Candidate routing policies

Evaluate these policies against the same benchmark suite:

1. **Single-model baseline:** one mid/flagship core model, deterministic checks only.
2. **Simple rules baseline:** task-type and importance-band routing with fixed eligible tiers.
3. **Value cascade:** economy tier → deterministic check → mid tier → flagship or cross-provider review when required.
4. **Quality-max route:** flagship primary model → deterministic check → independent cross-provider review for high-value tasks.
5. **Research-specialist route:** general model with controlled retrieval versus Perplexity/native search/Gemini grounding/xAI web tools.
6. **Retrieval variants:** no retrieval, lexical/AST, provider-native retrieval, owned retrieval, hybrid retrieval.
7. **Direct API versus aggregator path:** only for an eligible non-sensitive sample, measuring model parity, cost, latency, failures, and observability.

A learned router may be tested only after the rule-based cascade baseline exists. It is adopted only if it beats that baseline on held-out tasks, not merely on training or synthetic data.

### 6.2 Route eligibility gates

Before quality/cost comparison, every route must satisfy:

- task data classification permits the provider and feature;
- requested model is present in the dated live registry;
- required tools and structured-output support are available;
- expected maximum cost fits the task and monthly budget reservation;
- latency fits the task deadline;
- route can provide required evidence/provenance;
- task effect class is compatible with sandbox/approval policy.

Any route failing a gate is ineligible, regardless of benchmark quality.

### 6.3 Decision thresholds

A model or route may become a provisional default for a task class only when it meets all of the following:

1. At least **15 held-out tasks** in that class, with additional tasks for high variance.
2. Acceptance rate is not materially below the best eligible route. Initial materiality threshold: no more than **5 percentage points lower**, subject to human review for small samples.
3. False acceptance remains below the task-class safety threshold:
   - coding/data: near-zero for deterministic failures;
   - research: no material unsupported claims in accepted outputs;
   - automation: zero duplicate or unauthorized sandbox writes;
   - high-impact tasks: human-reviewed until sufficient evidence exists.
4. Median accepted-task cost is lower than the competing route by a meaningful amount, initially **15% or more**, unless latency or quality justifies the premium.
5. p95 latency meets the declared task deadline.
6. Reliability testing shows recoverable behavior without duplicate side effects.
7. Retrieval-required tasks meet minimum retrieval recall and provenance targets.

If no route clears these thresholds, retain a conservative mid/flagship route and mark the class for additional evaluation rather than forcing a low-cost default.

---

## 7. Evaluation Phases, Stop Rules, and Required Empirical Gates

### Phase A — Harness validation

Build the task ledger, sandbox, cost collector, retrieval logger, and deterministic validators. Run 5–10 smoke tasks to prove that results, token usage, tool fees, acceptance evidence, and failures are captured correctly.

**Gate:** no routing conclusion may be drawn until billed/estimated cost reconciliation and acceptance capture work end to end.

### Phase B — Core provider and tier bake-off

Evaluate direct OpenAI and Anthropic routes first, then Gemini, xAI, DeepSeek for explicitly non-sensitive tasks, and narrowly scoped Perplexity research routes. Use the task suite weighted toward coding, automation, and research.

**Gate:** determine whether each added provider produces a measured specialty advantage sufficient to justify routing and operational complexity.

### Phase C — Retrieval and review experiments

Run coding retrieval, document retrieval, web research, independent-review, and cache-ROI experiments. Verify whether provider-native retrieval, owned retrieval, Graphify, and cross-provider review improve accepted outcomes rather than just increasing apparent sophistication.

**Gate:** enable only retrieval and review mechanisms that improve acceptance, safety, or accepted-task cost for a defined task class.

### Phase D — Long-running fault injection

Execute staged multi-hour tasks and induced failure scenarios against the durable ledger and provider adapters.

**Gate:** no autonomous long-running route is enabled until it passes recovery and idempotency criteria.

### Phase E — Budget simulation and shadow routing

Replay observed workload mix through candidate VALUE and QUALITY-MAX policies using actual measured usage distributions, including tool costs, retries, cache rates, and review frequency.

**Gate:** the VALUE policy must remain within a conservative monthly budget band around $150 under realistic and high-usage scenarios, without relying on unresolved prices, best-case cache rates, or unmeasured escalation assumptions.

### Stop rules

Stop a task-class evaluation when:

- the default route and fallback route meet the required evidence threshold;
- material disagreements are documented and routed to human approval where necessary;
- additional runs are unlikely to change the routing decision;
- unresolved issues are explicitly converted into empirical retest triggers.

Do not continue running models simply to consume budget. Reopen an evaluation when a provider materially changes model version, pricing, context behavior, tool behavior, retention eligibility, or when production telemetry shows acceptance, cost, latency, or reliability drift beyond the established control limits.

<!-- ARTIFACT_COMPLETE -->
