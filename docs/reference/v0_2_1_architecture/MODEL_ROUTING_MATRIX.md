# MODEL_ROUTING_MATRIX

## 1. Purpose and Operating Position

This module defines the routing and escalation policy for the persistent multi-model work system. It selects an eligible provider/model lane for each task based on:

1. **Data classification and action authority** — hard eligibility gates.
2. **Task type and required tools** — coding, automation, research, data, documents, vision, etc.
3. **Importance, uncertainty, and verification needs** — not merely model self-confidence.
4. **Expected quality-per-dollar and latency** — with the ~$150/month VALUE architecture as the default target.
5. **Observed performance and current model registry data** — not hardcoded provider assumptions.

The router does **not** change the user’s primary goal, approve goal/scope changes, or authorize external/irreversible actions. It chooses a model route only after the task contract, policy engine, budget reservation, and data-classification gate have approved the task.

The operational default is deliberately simple:

> **Use direct OpenAI and Anthropic APIs as core lanes; use an inexpensive eligible lane first when objective verification is available; escalate only when evidence warrants it. Add Gemini, Perplexity, xAI, DeepSeek, OpenRouter, or specialists only where measured value exceeds integration complexity.**

A model is never selected solely because it is newest, cheapest, has a large advertised context window, or self-reports high confidence.

---

## 2. Router Inputs, Hard Gates, and Model Roles

### 2.1 Required task-contract inputs

Every dispatch must have the following validated fields before routing:

| Input | Router use |
|---|---|
| `task_type` | Determines primary route family and verifier |
| `objective` and acceptance criteria | Defines completion and escalation conditions |
| `importance_band` | Sets quality floor, review policy, budget reservation, and human-stop rules |
| `data_classification` | Filters provider/model/tool eligibility before cost optimization |
| `effect_class_ceiling` | Prevents routing from becoming action authorization |
| `latency_class` | `interactive`, `standard`, or `deferred/batch` |
| `tool_requirements` | Browser/search, code execution, file retrieval, vision, structured output, MCP, etc. |
| `estimated_context_size` | Avoids context-tier pricing cliffs and overstuffed prompts |
| `budget_ceiling_usd` | Caps cascade depth and reviewer usage |
| `evidence_required` | Determines whether deterministic retrieval, tests, citations, or independent review are mandatory |

Tasks lacking an explicit `data_classification` are treated as **sensitive by default** and cannot be sent to non-approved or aggregator routes.

### 2.2 Hard routing order

The router applies these filters in this order:

1. **Goal and approval validity:** reject stale contract versions or unapproved scope/effect changes.
2. **Data eligibility:** remove providers, endpoints, regions, caches, hosted tools, and aggregators not approved for the classification.
3. **Action eligibility:** route only to planning/review/execution surfaces allowed by the effect class. Routing does not bypass human approval.
4. **Capability eligibility:** remove models lacking essential tools, output format support, context capacity, or modality.
5. **Budget reservation:** remove routes whose worst permitted attempt plus required verification exceed remaining task/project budget.
6. **Task-performance policy:** choose among remaining routes using the matrix below.
7. **Runtime fallback:** only use explicitly listed fallbacks. Never silently substitute an aggregator or a lower-governance provider.

### 2.3 Logical model roles

Model IDs, prices, cache mechanics, context limits, rate limits, and retirement dates must come from a timestamped, versioned provider registry. The router uses stable **logical roles**, not name-pattern guesses such as “mini,” “flash,” or “reasoning.”

| Logical role | Intended use | Typical providers/candidates | Default availability |
|---|---|---|---|
| `ECONOMY_GENERAL` | Classification, extraction, bounded summaries, simple formatting, low-risk transformations | OpenAI economy tier; Anthropic Haiku-class | Core |
| `MID_GENERAL` | Default complex writing, moderate analysis, routine coding and integration planning | OpenAI mid tier; Anthropic Sonnet-class | Core |
| `FLAGSHIP_REASONING` | Hard coding, difficult debugging, research synthesis, adversarial review | OpenAI flagship; Anthropic Opus-class | Core |
| `PREMIUM_RARE` | Exceptional quality-max escalation only | Anthropic Fable-class if live/eligible; top current OpenAI tier | Conditional |
| `MULTIMODAL_ALT` | Vision, long-context, multimodal or independent-review candidate | Gemini, subject to benchmark and lifecycle review | Conditional |
| `WEB_RESEARCH_SPECIALIST` | Citation-oriented live web investigation | Perplexity Sonar family, subject to fee and quality measurement | Conditional |
| `ALT_AGENTIC` | Independent agentic/coding comparison | xAI/Grok, subject to benchmark and long-context cost guard | Conditional |
| `NON_SENSITIVE_VALUE` | Cheap batch/non-sensitive work only | DeepSeek, direct or approved endpoint only | Conditional; default-deny |
| `AGGREGATOR_SECONDARY` | Pinned access to otherwise unavailable secondary models | OpenRouter or equivalent | Exception only |
| `SPECIALIST_MEDIA` | OCR, image, speech, video | No provider adopted yet | Trigger-gated |

The registry must contain an `effective_model_id`, retrieval timestamp, cost fields, supported tools, data eligibility, context pricing thresholds, batch eligibility, health state, and replacement model. A route is ineligible if the registry is stale beyond the configured refresh period or if a provider has not exposed a verified replacement after retirement.

---

## 3. Decision-Ready Routing Matrix

### 3.1 VALUE architecture matrix — quality-per-dollar near $150/month

This is the default matrix. “First route” means the first substantive generation attempt after deterministic pre-classification; it does not require a paid LLM classification call.

| Workload | First route | Escalate to | Reviewer / verifier | Provider additions justified? | Stop condition |
|---|---|---|---|---|---|
| **Simple prompts** | `ECONOMY_GENERAL` from OpenAI or Anthropic | `MID_GENERAL` only if schema, factuality, or instruction check fails | JSON/schema check, style/lint check, bounded factual check where needed | No | Output meets stated format and no unresolved factual claim remains |
| **Coding / software** | `MID_GENERAL`; use `ECONOMY_GENERAL` only for isolated, low-risk edits or explanation | `FLAGSHIP_REASONING`; then cross-provider reviewer for Band 2–3 or failed tests | Build, unit/integration tests, lint/type checks, diff review, security scan where applicable | Gemini/xAI/DeepSeek only after benchmarked repository-task benefit; DeepSeek non-sensitive only | Tests pass, diff meets acceptance criteria, no unresolved reviewer defect |
| **Automation / integrations** | `MID_GENERAL` with deterministic API/schema references | `FLAGSHIP_REASONING` for multi-system failures, auth edge cases, or non-obvious event semantics | Sandbox execution, contract tests, webhook replay, idempotency test, schema validation | xAI/Gemini only if tool-use benchmark proves better; no aggregator default | Sandbox flow passes and no external effect is attempted without approval |
| **Research / web investigation** | `MID_GENERAL` plus deterministic retrieval plan; low-cost extraction may use `ECONOMY_GENERAL` | `FLAGSHIP_REASONING` for conflicting evidence or synthesis; Perplexity only where web-research benchmark justifies its layered fees | Source log, primary-source preference, citation-to-claim mapping, contradiction check | Perplexity narrowly justified for research; Gemini/xAI search must prove citation quality and cost | Acceptance criteria met, claims are cited, conflicts labeled or resolved |
| **Spreadsheet / structured data** | `MID_GENERAL`; inexpensive lane for clean extraction/classification only | `FLAGSHIP_REASONING` when formulas, joins, reconciliation, or anomaly explanations fail checks | Programmatic calculations, schema validation, reconciliation totals, sample-cell audit | No new provider initially; evaluate specialist OCR only after measured failure trigger | Numeric checks reconcile and output is reproducible |
| **Documents** | `ECONOMY_GENERAL` for templated sections; `MID_GENERAL` for substantive drafting | `FLAGSHIP_REASONING` for high-value synthesis, legal/financial-like complexity, or failed rubric | Template/schema check, citation check, render check, required-section checklist | No | Required sections, format, and evidence requirements pass |
| **Vision / images** | Core-provider native vision/multimodal lane, chosen from eligible OpenAI/Gemini capability registry | `MULTIMODAL_ALT` if extraction confidence is low or visual interpretation conflicts | Field-level extraction audit, image-to-source comparison, human approval for consequential interpretation | No image/OCR specialist yet; dedicated evaluation only after trigger | Required fields meet accuracy threshold or task is escalated/halted |
| **Business strategy** | `MID_GENERAL`, explicitly labeled as assumptions and options | `FLAGSHIP_REASONING` plus independent reviewer for high-impact decision support | Evidence table, assumptions register, alternative analysis | No specialist provider | Recommendations remain advisory; no unsupported “decision” claim |
| **High-uncertainty work** | `MID_GENERAL` or `FLAGSHIP_REASONING` depending on Importance Band; never economy-only if ambiguity is material | Independent cross-provider review, then human review if evidence remains ambiguous | Explicit uncertainty register, competing hypotheses, deterministic evidence where possible | Gemini/xAI are candidates for independent review only after benchmark | Uncertainty falls below acceptance threshold or task is labeled unresolved |

### 3.2 QUALITY-MAX comparison matrix

QUALITY-MAX changes the starting quality floor and review frequency; it does not remove safety, evidence, or stopping rules.

| Workload | QUALITY-MAX first route | Default independent review | Notes |
|---|---|---|---|
| Coding and automation | `FLAGSHIP_REASONING` | Cross-provider review for Band 2–3, major diffs, and failed tests | Parallel competing plans are permitted for complex designs, not trivial edits |
| Research | Flagship model with deterministic multi-pass retrieval | Independent source/citation review; Perplexity or Gemini may provide separately retrieved evidence | Reviewer should be blinded to the primary conclusion where practical |
| Structured data | Flagship model when analysis is nontrivial | Independent calculation or reviewer plus programmatic reconciliation | Numerical verifier remains authoritative |
| Documents | Mid or flagship based on stakes | Cross-provider review for externally consequential documents | Do not use additional models merely to rephrase |
| Vision/images | Best eligible native multimodal route plus second vision interpretation when material | Independent extraction comparison | Specialist adoption remains trigger-gated |
| High uncertainty | Flagship first, two competing evidence-grounded approaches when Band 3 | Cross-provider adjudication plus human approval for consequential decisions | More spending does not permit autonomous resolution of irreducible ambiguity |

QUALITY-MAX may use `PREMIUM_RARE` only after a flagship attempt fails a meaningful criterion and the task has objective acceptance checks. It is not a general default because the cost increase does not itself demonstrate a workload-specific quality gain.

---

## 4. Workload-Specific Policy Details

### 4.1 Coding and software routing

Coding is the highest-priority workload. The router should distinguish:

- **Bounded code transformation:** rename, small refactor, documentation, isolated test update. Start with economy or mid lane depending on test coverage and importance.
- **Feature implementation:** multi-file work, new API surface, database migration plan, integration changes. Start with `MID_GENERAL`.
- **Hard debugging:** failing tests with unclear cause, concurrency, distributed behavior, security-sensitive changes, repository-wide impact. Start with `FLAGSHIP_REASONING`.
- **Agentic code execution:** only in sandboxed environments with repository snapshots, allowlisted commands, and no production credentials.

The primary escalation trigger is not a model saying “I am unsure.” It is evidence: tests fail, static checks fail, tool output contradicts the proposed fix, the patch exceeds scope, or the generated plan lacks required evidence.

Cross-provider review is valuable only if it receives the diff, test logs, requirements, and independently selected evidence. A second model reviewing an unsupported narrative is not an independent quality control.

### 4.2 Automation and integration routing

Automation tasks have a high risk of hidden side effects. The model route must be separated from execution authority.

- Start routine API mapping, payload generation, and integration documentation in `MID_GENERAL`.
- Require `FLAGSHIP_REASONING` for retries, idempotency design, pagination, auth failures, multi-provider webhook flows, or ambiguous vendor documentation.
- Use sandbox/test credentials and replayable event fixtures before any live execution.
- Require an explicit human approval token for external communication, production changes, purchases, credential/permission changes, or non-reversible writes.

For integrations, an accepted answer requires machine-checkable artifacts where possible: valid schemas, request/response fixtures, idempotency keys, retry behavior, and a rollback path.

### 4.3 Research routing

Research requires enforced retrieval, not provider-discretionary retrieval. For every evidence-required research task:

1. Produce a retrieval plan and claim list.
2. Retrieve sources deterministically through approved tools.
3. Store source snapshots/URLs, timestamps, and source-to-claim mappings externally.
4. Generate synthesis only from the evidence packet plus clearly marked general reasoning.
5. Run contradiction and citation checks before acceptance.

Perplexity is a narrow candidate for live web research because its costs include token charges and search-depth/request fees. Default to low search-context depth in VALUE mode and raise depth only when acceptance criteria require breadth or deeper investigation. The exact current fees must be read from the live provider registry.

Gemini internal File Search and live web grounding should be modeled as separate retrieval passes because validated research indicates they cannot be combined in one request. The orchestrator, not the model, merges the evidence sets.

### 4.4 Data, spreadsheets, and structured analysis

For spreadsheets and data work, the router should prefer deterministic computation over increasingly expensive prose reasoning. The workflow is:

1. Extract and normalize data.
2. Validate schema and types.
3. Compute/reconcile using code or formulas.
4. Ask the model to explain anomalies, assumptions, and results.
5. Re-run deterministic checks on the final output.

Escalate because a reconciliation fails, an input is ambiguous, a formula graph is complex, or a model explanation conflicts with computed results. Do not escalate merely to obtain more confident wording.

### 4.5 Document generation

Documents are medium priority and should not consume flagship capacity by default. Route structured outlines, templates, formatting, and source extraction through economy/mid lanes. Use flagship escalation for difficult evidence synthesis, high-value executive communication, or documents whose acceptance rubric fails after a mid-tier attempt.

Document quality checks include required sections, formatting/render correctness, citation coverage, duplication detection, and consistency with the task contract. The router must not treat fluent prose as evidence of correctness.

### 4.6 Vision and image work

Image work is lower priority. Use core-provider vision capabilities first; do not add a specialist provider based on generic claims.

A dedicated OCR or image-specialist evaluation is triggered only when a representative workload shows that core-provider extraction or generation fails a defined quality threshold, such as:

- dense scans or complex tables fail a field-level accuracy target;
- two of three independent reviewers reject a generated image against a documented quality rubric;
- a workflow requires speech or video as a first-class output.

Until that trigger is met and a specialist is separately priced and security-reviewed, the router uses core multimodal capabilities and routes ambiguous visual interpretations to human review.

---

## 5. Escalation, Disagreement, and Review Policy

### 5.1 Escalation ladder

The standard VALUE escalation ladder is:

1. **Attempt 0 — deterministic preparation:** task classification, retrieval plan, schema setup, test fixture preparation, cost reservation.
2. **Attempt 1 — lowest sufficient eligible lane:** economy for simple bounded work; mid tier for coding, automation, research synthesis, and structured analysis.
3. **Attempt 2 — stronger intra-provider lane:** mid or flagship reasoning route after objective failure or high ambiguity.
4. **Attempt 3 — independent review or cross-provider repair:** required for Band 2–3 according to the task contract; optional sampled review for Band 1.
5. **Stop for human review:** if the escalation cap, retry cap, budget ceiling, or disagreement-repeat limit is reached.

The QUALITY-MAX ladder begins one rung higher and uses cross-provider review more frequently, but retains the same maximum escalation depth of three substantive model stages before human escalation.

### 5.2 Valid escalation triggers

Escalation is permitted when one or more of these conditions holds:

- tests, validation, or tool execution fail;
- output violates schema, acceptance criteria, or scope boundaries;
- retrieval evidence is insufficient, stale, contradictory, or uncited;
- the task’s ambiguity score is high and evidence is missing;
- model/tool output conflicts with deterministic calculations;
- the task is Importance Band 2–3 and the required reviewer has not approved;
- the first model’s calibrated confidence is below a threshold **that has been empirically validated for that model and task class**;
- a route hits recoverable provider errors, context limits, rate limits, or health degradation.

Self-reported confidence alone is never sufficient. Early-token or log-probability confidence is not a deployed control unless target APIs expose it and empirical calibration proves useful.

### 5.3 Disagreement resolution

| Condition | Resolution |
|---|---|
| Tests, schemas, calculations, or source checks determine the answer | Follow deterministic evidence |
| Reviewer finds a concrete defect with artifact references | Repair and rerun the verifier |
| Primary and reviewer disagree but evidence is incomplete | Escalate to an independently retrieved/evidenced review |
| Subjective disagreement on low-impact reversible work | Deliver a clearly labeled provisional result or defer |
| Disagreement concerns external communication, production, money, credentials, sensitive data, or Band 3 work | Halt for human approval; no autonomous tie-break |
| Same sub-task disagrees after one repair cycle | Stop and create a human-review task |
| Budget or escalation cap is reached | Stop; preserve artifacts and request a decision |

The system must never resolve a disagreement by choosing the cheaper, faster, or more verbose answer.

---

## 6. Provider Inclusion and Exclusion Policy

### 6.1 Core direct-provider policy

OpenAI and Anthropic are core providers and should be accessed directly for primary routing. Direct paths avoid unnecessary aggregator markup, extra data handling, and model/version ambiguity.

OpenAI economy-tier pricing has a documented conflict between official-attributed sources in the validated research. The router may use the logical economy role, but the COST_MODEL must apply a sensitivity band until a live billed test and current official page check resolve the discrepancy. No hard budget threshold may rely on the lower price alone.

Anthropic’s Haiku/Sonnet/Opus shape is suitable for economy/mid/flagship lanes, but current IDs, scheduled Sonnet price transitions, cache behavior, and account limits must be refreshed before production locking.

### 6.2 Conditional providers

- **Gemini:** highest-priority third-party benchmark candidate for low-cost triage, multimodality, long-context work, and independent review. Include only after representative-task and data-lifecycle testing.
- **xAI/Grok:** benchmark candidate for agentic coding and tool use. Its long-context repricing behavior must be modeled as a per-request guard; oversized prompts must be compacted or rejected before dispatch.
- **Perplexity:** research specialist only. Use for evidence-oriented web tasks when its measured citation quality and total cost—including depth/request fees—beat native-provider search.
- **DeepSeek:** allowed only for explicitly `internal_non_sensitive` tasks through a default-deny allowlist. It is excluded from sensitive tasks, unknown-classification tasks, and silent fallback paths due to governance uncertainty.
- **OpenRouter/aggregators:** secondary-provider on-ramp only, with provider pinning, explicit fee accounting, and the same data restrictions as the underlying route. Never use it for core OpenAI/Anthropic traffic by default.
- **Local/open-weight models:** deferred at the ~$150 target because continuous or substantial GPU hosting can consume too much budget before maintenance and evaluation costs. Revisit for air-gapped or sensitive-data requirements, not as a default value route.
- **Specialists:** no OCR/image/speech/video vendor is adopted until the trigger-gated evaluation described in §4.6.

---

## 7. Measurement, Refresh, and Decision Gates

The matrix is provisional until benchmarked on representative work. Each route record must log:

- requested and effective provider/model ID;
- registry version and retrieval timestamp;
- task type, importance band, and data classification;
- input, output, cache, reasoning, and tool usage;
- estimated and invoiced cost where available;
- latency, retries, rate-limit/provider errors;
- verifier outcome, reviewer defects, acceptance outcome;
- escalation reason and human intervention rate.

The minimum routing evaluation compares: economy-first cascade, mid-first baseline, flagship-first baseline, selected cross-provider review, and conditional third-party routes. Metrics are acceptance-pass rate, false-accept rate, cost per accepted task, p50/p95 latency, escalation precision, citation quality for research, test pass rate for coding, and human repair time.

A new provider or specialty route is promoted only when it demonstrates a measurable improvement against the simpler baseline on the user’s representative tasks and its added privacy, billing, operational, and routing complexity is accepted.

<!-- ARTIFACT_COMPLETE -->
