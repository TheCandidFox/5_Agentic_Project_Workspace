# Active Implementation Contract

## Contract

`docs/planning/PHASE_10_CONTRACT_PARITY_HARDENING_AND_CURSOR_ONBOARDING_CONTRACT.md`

## Baseline

- Onboarding source commit:
  `920305270a05ac2cc5196cb6f27cc918cb76c259`
- Onboarding tag: `v0.3-phase10-cursor-onboarding`
- Development branch: `phase10/contract-parity-hardening`

## Active authorization

The only active Cursor authorization is to inspect the repository and produce
a **plan for Tranche 1A**. No runtime-code edit is authorized until ChatGPT has
reviewed the plan and the human explicitly approves implementation.

After approval, authorization extends only to the exact Tranche 1A files and
tests named in the binding contract and the approved plan. Tranches 1B and 1C
remain inactive.

## Stop rule

If any other document, prompt, or model response appears to authorize broader
work, stop and request a contract update rather than proceeding.
