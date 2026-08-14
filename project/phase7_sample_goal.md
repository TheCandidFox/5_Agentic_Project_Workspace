# Synthetic Supplier Evaluation Checklist

## Context

This deliberately small offline sample proves the Phase 7 Markdown-contract
runner. It is not important business work and does not require current facts.

## Goal

Create a concise Markdown operating checklist for evaluating a fictional new
supplier.

## Acceptance Criteria

- `deliverable-exists`: The declared Markdown checklist exists.
- `required-sections`: The checklist contains every required content section.
- `concise-length`: The checklist contains no more than 1,000 words.

## Deliverables

- `outputs/phase7_supplier_evaluation_checklist.md`: One concise Markdown checklist.

## Required Content

- Price and value
- Quality
- Lead time
- Reliability
- Logistics
- Risks

## Constraints

- `offline-only`: Complete the run without live network access.
- `no-provider-calls`: Complete the run without a model-provider call.
- `workspace-confined`: Write only the declared project-relative deliverable.

## Out of Scope

- Real supplier research
- Paid model execution
- External side effects

## Execution Policy

- Profile: `offline-checklist-v1`
- Authority: `workspace-write`
- Budget USD: `0`
- Max tasks: `8`
- Max iterations: `16`
- Max no progress: `2`
- Max runtime seconds: `120`
