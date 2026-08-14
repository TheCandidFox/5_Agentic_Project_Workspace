# QUALITY_MAX_ARCHITECTURE.md

## Purpose and Scope

This module defines the **quality-max architecture**: the design used when the objective is to maximize the correctness, robustness, and defensibility of output on the user's priority workloads (coding/software, automations/integrations, web research first; data/spreadsheets next; documents medium; strategy/images lower), and where **cost is a secondary constraint rather than the primary one**. It is not a "spend more everywhere" instruction — it is a deliberate set of choices about where added spend and added complexity produce measurable quality gains, with explicit call-outs of where evidence is provider-claim-only, tracker-corroborated-but-not-vendor-audited, or unbenchmarked. This module does not change the user's primary goal, does not relax any human-approval gate defined in the routing, security, or long-running-work tracks, and does not introduce new providers beyond those already evaluated elsewhere in the package.

The quality-max architecture shares its skeleton with the value architecture: the same durable, provider-neutral task ledger; the same task-contract schema, importance bands, and goal-change governance; the same action-authority/effect-class policy; the same data-classification gate. What differs is model-tier defaults, escalation aggressiveness, review cardinality/independence, redundancy policy, and infrastructure resilience purchased. Every provider/model claim below is bound to the versioned registry snapshot in the next section rather than asserted as a standing fact of this module. **A hard rule governs this entire module: no tier, model, or provider may be part of quality-max's *default, production* routing unless it appears in the snapshot with at least AUDIT-CITED evidence and a stated data-classification eligibility rule. Anything weaker is DEFERRED to bench-off/evaluation status only, never production routing, until that bar is met.**

## Provider/Model Registry Snapshot (binding reference for this module)

| Tier used below | Evidence tier | Source / access basis | Registry action required at build time | Production routing status |
|---|---|---|---|---|
| OpenAI flagship (current top-of-family model per live registry) | AUDIT-CITED, not re-verified this pass | OpenAI platform track, developers.openai.com/api/docs/models | Re-pull live registry entry at deploy time; do not assume model ID stability | **Included** as default coding/research/agentic tier |
| OpenAI economy tier | DEFERRED — 5x price conflict between OpenAI's own pages, unresolved | OpenAI platform track §2b/§6 | Do not budget/gate on this tier until a billed test resolves the conflict | Included only for trivial sub-steps; not price-locked |
| Anthropic Opus-class | VERIFIED, multi-source (official pricing page + independent trackers) | Anthropic platform track §2 | Confirm exact model ID/price at implementation time | **Included** as default escalation target |
| Anthropic "Fable 5" (asserted top-of-stack tier) | **DOWNGRADED to DEFERRED this revision.** The naming, GA status, and $10/$50-per-MTok figure rest on a chain of third-party trackers plus a single official pricing-page reference that this module cannot independently confirm, and the product name does not match Anthropic's established Haiku/Sonnet/Opus convention, raising a material naming/identity risk. | Anthropic platform track §1–§2 (evidence chain insufficiently decision-grade) | **Do not route to this tier in production.** Before any future adoption, an implementer must pull Anthropic's own current model/pricing page directly (not a tracker) and confirm exact model identifier, GA/beta status, and price on that date | **Excluded from quality-max default/production routing.** Eligible only for a manual, human-approved, one-off bench evaluation, never an automated escalation path |
| Anthropic Mythos (Preview) | OFFICIAL-SINGLE-SOURCE — existence confirmed via tokenizer note only; access/pricing unconfirmed | Anthropic platform track §1 | Confirm access model before any use | **Excluded** from default candidate set |
| DeepSeek `deepseek-v4-pro` | CONVERGENT TRACKER EVIDENCE only — six trackers agree on price, but no vendor-audited screenshot of DeepSeek's own live price table was taken, and a pending unscheduled price change is officially flagged | Third-party-provider track §2.4 | Directly re-pull api-docs.deepseek.com's own price page (not a tracker) and confirm exact figures before any use | **Excluded from active routing.** Retained only as a fail-closed future-evaluation trigger (see below) — not an active third-opinion lane in this revision |
| Gemini / xAI premium tiers | AUDIT-CITED / PROVIDER CLAIM, exact prices flagged stale-mapped in cost-model track | Gemini/xAI sections, cost-model track §2 | DEFER exact figures to live pricing page | Bench-off candidates only, not price-verified defaults |
| Perplexity Sonar / Deep Research | AUDIT-CITED for the *fee formula* (tokens + search-context-depth fee + Deep-Research surcharges); the exact depth-tier dollar amount was **not independently re-verified** in the underlying research pass | Third-party-provider track §2.3 | Re-pull docs.perplexity.ai pricing page for the exact depth-fee amount before any budget commitment | **DEFERRED to bench-off/manual-approval use only in this revision** (see Perplexity policy below) — not a default production routing path |

**Rule enforced by this module:** any tier not appearing above with at least AUDIT-CITED evidence, or lacking a stated data-classification eligibility rule, is **not eligible** for quality-max default routing. Fable 5, `deepseek-v4-pro`, and Perplexity are all held to this rule in the current revision and are therefore DEFERRED from production routing, as detailed below.

## Provider and Model Defaults

- **OpenAI:** flagship tier per the live model registry for coding, agentic orchestration, and research tasks, used with Background mode for individual long-running calls. Economy/legacy tiers remain in use for high-volume, low-stakes sub-steps even in quality-max — using a flagship model for trivial work is waste, not quality.
- **Anthropic:** Opus-class is the default escalation/primary target for hard, bounded, high-value tasks. **Fable 5 is DEFERRED, not included, in this revision's production routing.** Its inclusion in an earlier draft was found insufficiently substantiated (naming inconsistent with Anthropic's established convention; pricing/GA status not independently confirmed against Anthropic's own current documentation). Until an implementer directly confirms model identity, GA status, and price from Anthropic's own pricing page on a dated basis, quality-max escalates no further than Opus-class automatically; any Fable-class attempt requires a manual, human-approved, logged bench trial outside the automated escalation ladder. **Mythos (Preview) remains excluded** pending confirmation of its access model.
- **Gemini and xAI/Grok:** both are bench-tested on equal footing as second-reviewer/primary-model candidates, evaluated empirically per the EMPIRICAL_EVAL_PLAN's cross-tier bake-off, not assumed superior. Neither is a default primary model ahead of OpenAI/Anthropic absent workload-specific benchmark evidence, and neither's pricing is treated as locked.
- **DeepSeek:** `deepseek-v4-pro` is **excluded from active routing in this revision.** It is retained only as a named, fail-closed future-evaluation trigger: if and only if (a) DeepSeek's own official pricing page is directly re-pulled and confirms the tracker-reported figures on a dated basis, and (b) the data-classification gate (default-deny, non-sensitive-only, audit-logged, per the security and third-party-provider tracks) is implemented and tested to structurally block sensitive-tagged tasks, may it be enabled as a manual-approval third-opinion lane — never a default automatic escalation target. Until both conditions are met, any task otherwise eligible for a "third opinion" instead uses a same-provider stronger-model re-check or a cross-provider (Gemini/xAI) check.
- **Perplexity:** **DEFERRED to bench-off/manual-approval use in this revision**, not a default production routing path for quality-max, because the exact depth-tier fee was not independently re-verified and no data-classification eligibility rule had previously been stated. The following eligibility rule now governs any future or interim use: Perplexity (any tier, including Deep Research) may receive only tasks explicitly tagged `public` or `internal-non-sensitive` at task-decomposition time; **any task lacking an explicit non-sensitive tag is treated as sensitive by default and is structurally unreachable to Perplexity**, enforced at the same default-deny routing layer used for DeepSeek; and no task tagged `sensitive` may reach Perplexity under any circumstance, including reviewer/escalation paths. Perplexity's re-entry into default production routing (rather than manual/bench use) requires: (1) direct re-verification of the exact depth-tier fee from docs.perplexity.ai on a dated basis, and (2) the routing-gate test asserting zero sensitive-tagged tasks reach Perplexity, passing per the third-party-provider track's acceptance measure. Until both pass, quality-max relies on OpenAI/Gemini/xAI native web search and grounding for research tasks instead.
- **Local/open-weight models:** excluded from quality-max's default routing on the same economic-and-evidence basis as the value architecture — reserved for a future sensitive-data or air-gapped requirement only.
- **Specialist providers (image/video/speech/OCR):** not adopted by default in either architecture; quality-max relies on core-provider native multimodal capability until the measurable triggers defined in the third-party-provider track (§2.6) are met.

All model/tier bindings above are read from the same live, versioned provider/price/capability registry used by the value architecture; the snapshot table records only the evidence available at research time and must be re-verified, not treated as a permanent guarantee.

## Routing and Escalation Policy

The routing mechanism — cascade-first, deterministic pre-classification, evidence-first disagreement resolution, importance bands, hard anti-loop caps — is **identical in structure** to the value architecture; what changes at quality-max is starting point and aggressiveness:

- **Model floor is higher per importance band.** Where the value architecture starts Band 1 ("standard") work at the cheapest eligible model, quality-max starts Band 1 at a mid/flagship tier and reserves the cheapest tier only for Band 0 exploratory work.
- **Concrete escalation caps (this revision specifies exact starting values, not a range):** quality-max's initial escalation-depth cap is **4** (versus the value architecture's conservative starting cap of 3), and the disagreement-repeat threshold before mandatory human escalation is **2** (versus the value architecture's 1). The goal-change re-plan cap remains **1** in both architectures — spending more never relaxes anti-loop governance. **Calibration rule:** these starting values are reviewed after the first full run of the routing track's empirical bake-off (false-escalation rate, false-acceptance rate, cost-per-accepted-task); the depth cap may be raised by at most one step per review cycle, capped at an absolute ceiling of 6 without explicit human-approved policy change, and must be lowered immediately if false-escalation rate exceeds the value architecture's observed rate by more than a pre-agreed margin.
- **Escalation triggers earlier and deeper.** Objective/deterministic checks remain the primary trigger — self-reported confidence is still only a secondary, empirically-validated signal — and Band 2–3 tasks trigger cross-provider review near-universally rather than by sampling.
- **Importance banding and goal-change governance are unchanged.** Quality-max buys more *checking*, not more *autonomy*: Band 3 (irreversible/external/financial/credential/sensitive) tasks always require human sign-off before execution regardless of confidence or reviewer agreement.
- **Learned/pre-classification routers remain deferred** in both architectures until benchmarked against a simple rule-based baseline on this project's own task suite and shown to win.

## Independent Review Design

- **Cross-provider review is a validated hypothesis to retain, not a permanent guarantee.** Quality-max runs cross-provider review near-universally on top-priority workload tiers and all Importance Band 2–3 tasks as an **initial experimental policy**. **Continuation rule:** retained as default only if the reviewer-independence test (routing track §6) shows measurable false-acceptance-rate reduction versus deterministic-verifier-only; otherwise downgraded to sampled (matching the value architecture) for that task category, logged as a policy revision.
- **Trace-level review is a triage aid, paired with deterministic evidence, never a sole release gate.** A trace reviewer must cite concrete artifacts (tool I/O, exit codes, test/lint results, diffs, hashes) rather than issue an unsupported verdict, and is trusted as more than advisory only after scoring against a labeled failed/successful-trace set per the routing track's suite.
- **Review independence means more than "a different vendor."** Where feasible, the reviewer is blinded to the original answer, given an independently retrieved evidence packet, and required to use a structured defect taxonomy; objective checks rank above model-judged scores.
- **Debate/multi-agent cross-examination** is available for the highest-stakes deliverables using observable evidence-based arbitration only; the unvalidated "early-token confidence" tie-breaker is explicitly **not adopted**.
- **Calibrated confidence intervals** are used only once empirically demonstrated per model/task class on this system's own data, with recalibration after any model/prompt/tool change.

## Redundancy, Long-Running Execution, and Infrastructure

Quality-max applies **selective, stakes-gated redundancy**: parallel independent implementations for complex code, independent source verification for research, competing plans before irreversible steps, review triggered after a failed verifier — never blanket ensembling.

Long-running work keeps the same durable ledger as the value architecture (Postgres-class state, idempotency keys, budget reservations) but adds: a durable-execution framework (Temporal-class) only if fault-injection testing shows the custom ledger insufficient; Anthropic Managed Agents evaluated strictly behind a provider adapter for isolated, non-authoritative experimental work, never system of record; multi-provider failover only at defined checkpoints; stronger evidence provenance/artifact hashing across multi-day runs.

Infrastructure upgrades from the value tier's single small VM/SQLite pattern to dedicated compute, a passive/cold standby (promoted only via a fencing-token protocol that must pass a host-loss/partition drill before automated failover is enabled), a transactional store once concurrent writers are real, customer-managed encryption keys, and a managed secrets service — staged, trigger-gated upgrades, not purchased on principle alone. Retrieval is upgraded similarly: opt-in GraphRAG only after baseline RAG is shown insufficient, a provider-native index run in parallel with an owned index for comparison, and a more serious Graphify pilot with independent-reviewer cross-check of source-derived vs. inferred edges.

## Cost Profile and the Trade-off Against the Value Architecture

Quality-max is **not** a fixed multiple of the value architecture's budget — no prior worked-example dollar figure is decision-grade; those remain unaudited scenario outputs pending a reproducible workload ledger. What is decision-grade is the *shape* of the trade-off:

- **Model-tier dial:** running flagship-first instead of cascade-first removes the 10–25x price spread the value architecture exploits as its primary lever — the single biggest cost driver in quality-max.
- **Review-cardinality dial:** near-universal cross-provider review on Band 2–3 work roughly doubles token/latency cost on those tasks, independent of model tier — a separable dial, not bundled with model tier.
- **Redundancy dial:** stakes-gated parallel attempts add cost only on tasks flagged high-risk/high-ambiguity.
- **Infrastructure dial:** upgrading to dedicated compute/standby/managed secrets is a fixed monthly increment that should only be paid once stage-transition triggers are met.
- **Deferred-provider dial:** because Fable 5, `deepseek-v4-pro`, and default Perplexity routing are all held out of production in this revision, quality-max's near-term cost profile is closer to "OpenAI flagship + Anthropic Opus + selective Gemini/xAI review" than the broader multi-provider set previously assumed — a materially more conservative, better-evidenced starting point.

The EMPIRICAL_EVAL_PLAN's cross-tier bake-off is the mechanism that converts this trade-off into an actual number; until it runs, quality-max is directionally higher-cost and higher-reliability than the value architecture, magnitude unverified.

## Explicit Differences from the Value Architecture

| Dimension | Value architecture | Quality-max architecture |
|---|---|---|
| Model floor | Cheapest eligible, cascade-first | Mid/flagship first attempt for Band 1+ |
| Review | Deterministic verifier default; cross-provider sampled | Near-universal cross-provider review on Band 2–3, blinded where feasible; downgraded if no measurable benefit |
| Redundancy | None by default | Stakes-gated parallel attempts on high-risk work |
| Escalation depth cap | 3 (conservative start) | **4**, ceiling 6, reviewed each bake-off cycle |
| Disagreement-repeat threshold | 1 | **2** |
| Anthropic Fable 5 | Excluded | **DEFERRED** — excluded from production; manual bench-only pending direct vendor re-verification |
| DeepSeek `deepseek-v4-pro` | Excluded | **DEFERRED** — excluded from active routing; fail-closed future-evaluation trigger only |
| Perplexity | Not used by default | **DEFERRED to bench-off/manual use**; strict non-sensitive-only eligibility rule specified for any future production use |
| Infrastructure | Single small VM, manual failover | Dedicated compute, drill-gated staged failover, managed secrets/KMS |
| Retrieval | Lexical/AST Tier 1, selective semantic Tier 2 | Same base, plus opt-in GraphRAG/owned index, trigger-gated |
| Governance | Unchanged | Unchanged — spending more never relaxes approval gates |

## Risks and Required Empirical Verification

1. **Fable 5 identity/pricing verification** — before any future adoption, directly confirm model ID, GA status, and price from Anthropic's own current pricing page, dated; naming inconsistency with Anthropic's convention must be explicitly resolved, not assumed a rebrand.
2. **DeepSeek `deepseek-v4-pro` vendor confirmation** — directly re-pull DeepSeek's own price page (not a tracker) and confirm the data-classification gate blocks sensitive tasks before any manual-approval use.
3. **Perplexity fee and eligibility verification** — re-pull the exact depth-tier fee and pass the sensitive-task-exclusion routing test before Perplexity re-enters default production routing.
4. **Cross-provider review benefit** — per the reviewer-independence test; decision rule stated above.
5. **Trace-reviewer reliability** — per the labeled-trace scoring test; decision rule stated above.
6. **GraphRAG/Graphify value** — gated on baseline-RAG-insufficiency and egress-verification tests.
7. **Fencing-token failover protocol** — must pass a host-loss/partition drill before automated failover is enabled.
8. **Escalation-cap calibration** — the depth-4/repeat-2 starting values must be reviewed against observed false-escalation/false-acceptance rates after the first bake-off cycle, per the calibration rule above.
9. **Registry currency** — every provider/tier claim in this module's snapshot must be re-verified against the live registry immediately before implementation and periodically thereafter; any tier failing re-verification reverts to DEFERRED status.

This module's role is to specify what quality-max does differently, bind those differences to evidence-graded, fail-closed provider eligibility, and flag that the magnitude of benefit for nearly every added dial — and the eligibility of every provider currently held at DEFERRED — remains unproven pending the evaluations above.

<!-- ARTIFACT_COMPLETE -->
