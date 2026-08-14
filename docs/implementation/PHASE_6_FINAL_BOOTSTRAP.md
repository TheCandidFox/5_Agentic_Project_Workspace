# Phase 6 Final Bootstrap Acceptance

**Status:** implemented and verified offline
**Network/provider calls:** none
**Gate count:** exactly ten

## Entry point

`run_bootstrap_phase6.py` is the final local-bootstrap verification command:

```powershell
python run_bootstrap_phase6.py --status-only
python run_bootstrap_phase6.py
```

Status-only mode:

- applies checksummed additive migrations through `0005`;
- checks SQLite integrity;
- checks the Phase 1–5 foundation and Git conflict state;
- verifies research and acceptance tables/columns;
- verifies that live HTTP is disabled by default;
- parses the ten-gate evidence manifest and confirms each mapped test exists;
- performs no pytest, fixture retrieval, provider call, network request, patch,
  checkpoint, or Git mutation.

Full mode additionally:

- runs the complete guarded Python syntax and pytest suite;
- runs the deterministic authoritative-source fixture and completed replay;
- links that captured source into a `VERIFIED` acceptance decision;
- runs the five acceptance calibration cases twice;
- maps the complete regression result to all ten named gates.

## Ten-gate manifest

`bootstrap_acceptance.py` owns the fixed gate definitions and their specific
pytest evidence nodes:

1. passing and failing command capture;
2. workspace confinement;
3. patch and rollback;
4. tiny-fixture repair;
5. bounded unfixable failure;
6. local Git checkpoint;
7. budget denial before dispatch;
8. restart/resume without duplicate dispatch;
9. acceptance/truth calibration;
10. authoritative research provenance and replay.

The manifest fails closed when it does not contain exactly ten unique gate IDs,
an evidence path escapes the project, a test file is missing/unparseable, or a
mapped test function is absent. A present test name is not enough by itself:
the complete offline regression suite must also pass.

## Research-to-acceptance smoke

The smoke uses one immutable in-memory fixture with:

- HTTPS source URL;
- official-documentation/primary-source metadata;
- applicable version/date;
- timezone-aware retrieval timestamp;
- captured text and SHA-256;
- one sourced fact and exact excerpt.

The runner executes the request twice. The second execution must replay from
SQLite without increasing the fixture retriever call count. The captured source
ID is then referenced as `PRIMARY_SOURCE` evidence in the acceptance engine;
the criterion and claim must reach `PASS`/`VERIFIED`.

No `HttpDocumentRetriever`, provider adapter, key, model client, or remote Git
operation is constructed by the entry point.

## Phase boundary

A passing Phase 6 result means the local execution substrate can research and
govern evidence under deterministic acceptance. It does not mean the system can
yet parse an arbitrary project Markdown contract, create/revise a backlog, or
select/execute paid agents until a goal completes. Those capabilities belong to
the next contract/orchestration phase.
