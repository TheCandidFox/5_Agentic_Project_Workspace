from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ledger import Ledger
from revision_contracts import parse_review
from revision_cycle import RevisionCycle, RevisionPolicy


def _passing_review(artifact: str, criteria: tuple[str, ...]) -> str:
    return json.dumps({
        "schema_version": "phase10-review-v1",
        "artifact_sha256": hashlib.sha256(artifact.encode()).hexdigest(),
        "overall_verdict": "PASS",
        "findings": [],
        "criterion_results": {key: "PASS" for key in criteria},
        "summary": "All deterministic offline criteria pass.",
        "recommended_next_action": "Preserve the accepted artifact.",
    }, separators=(",", ":"))


def run_offline_canary(root: Path, ledger_path: Path) -> dict:
    ledger = Ledger(ledger_path, root)
    cycle = RevisionCycle(ledger, root)
    baseline = "# Offline Phase 10 Fixture\n\nThe artifact is preserved.\n"
    run_id = "phase10-offline-canary-v1"
    version = cycle.start(run_id=run_id, contract_sha256="0" * 64, goal="Prove bounded immutable review and replay offline.", logical_path="outputs/phase10_offline_canary.md", baseline=baseline, policy=RevisionPolicy())
    status = cycle.status(run_id)
    if status["state"] == "BASELINE_PRESERVED":
        cycle.claim_dispatch(run_id, role="review", ordinal=1, quoted_cost_usd=0, idempotency_key=f"{run_id}:review:1")
        review = parse_review(_passing_review(baseline, ("artifact-preserved",)), ("artifact-preserved",), hashlib.sha256(baseline.encode()).hexdigest())
        cycle.record_review(run_id, "offline-review-1", version, review)
    return cycle.status(run_id)


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 10 bounded revision cycle (offline only)")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--ledger", default="ledger.db")
    parser.add_argument("--offline-canary", action="store_true")
    parser.add_argument("--status", metavar="RUN_ID")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    ledger_path = Path(args.ledger)
    if not ledger_path.is_absolute():
        ledger_path = root / ledger_path
    if args.offline_canary:
        result = run_offline_canary(root, ledger_path)
    elif args.status:
        result = RevisionCycle(Ledger(ledger_path, root), root).status(args.status)
    else:
        parser.error("choose --offline-canary or --status RUN_ID")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["state"] == "ACCEPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
