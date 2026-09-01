# Full Process Flow

```text
Start SAGE
  -> preflight Python/runtime dependencies
  -> complete/verify Codex + ChatGPT setup when AI work is required
  -> choose SAGE Projects
  -> choose/create one independent BIC, RTC, or STC Job
  -> create/continue one bounded Run
  -> create immutable governed task/stage
  -> verify hashes and assemble sealed evidence
  -> execute enabled provider
  -> validate structured response
  -> deterministic workflow transition/finalization
```

Every governed analytical task has a persistent `job_id` and `run_id`. Direct CLI shortcuts and natural-language requests resolve through the same `Project -> Job -> Run -> task` grammar; they do not create workflow state without a Project.

## BIC

```text
ONE SOURCE + ONE DONOR -> ONE TARGET

INSPECT
  -> REWRITE
       -> conditional bounded OL second pass only when triggered
  -> SELF-CHECK
  -> bounded merge into the bound TARGET book
  -> governed TARGET commit
```

The model-facing REWRITE/SELF-CHECK artifact remains bounded. Commit replaces only the governed scope in the bound TARGET book and preserves every out-of-scope verse/marker block. Routine INSPECT does not route OL Scripture. A BIC Job has exactly one bound TARGET Project. That TARGET may be stored internally or mapped to one Paratext/PTLite project folder; those are alternative storage bindings for the same TARGET. SOURCE is the sole content authority. DONOR is vocabulary-only evidence and is decontextualized before model routing. Existing TARGET Scripture is not routed during INSPECT/REWRITE.

## Reference Text Comparison (RTC)

```text
WIP + authorized REFERENCE
        |
        v
deterministic preflight / structural triage
        |
        +--> STRUCTURAL ADJUDICATION       [conditional AI stage]
        |
        v
TRANSLATION / MEANING RTC                  [required AI stage]
        |
        +--> SELECTIVE OL ADJUDICATION     [conditional AI stage]
        |
        v
deterministic merge / coverage / finalization
        |
        v
batch finalized Run results into Job report catalog
        |
        +--> reports/<job-id>/<BOOK>/<CCC>/<run-id>_<BOOK>-<CCC>_ACTION-REPORT.md
        `--> reports/<job-id>/<BOOK>/<CCC>/<run-id>_<BOOK>-<CCC>_OPERATOR-NOTE.txt
```

Each AI stage is an isolated governed task inside the same Run. The structural stage covers only routed structural-candidate coordinates; the required meaning stage covers every immutable approved review portion. Structural and meaning stages receive no OL Scripture. The meaning stage may defer an issue only through `SAW_OL_REFERRAL_ADMISSION_V1`: a fundamental incompatible proposition, one of four closed conflict classes, source-dependent and unresolved by routed non-OL evidence, one smallest-scope issue, and unique. Python validates the structured admission and derives its conflict key. Only the selective OL stage receives the exact requested coordinates and configured Job-bound GRK/HEB evidence. Each request becomes its own task and returns exactly one resolution; finalization preserves the request/resolution ledger.

Operator progress reports the stable `Review range`, immutable `Review portion n/N`, and local `Structural check` or `Source check` counters. Stage cases cannot cross approved portions; machine task totals never replace the approved portion denominator.

Run-local tasks, validation receipts, and raw final results remain governed Job provenance.
Deterministic finalization consolidates compatible chapter results, stores the canonical combined
record under Job `report_data/`, and publishes polished files to
`localdata/reports/<job-id>/<BOOK>/<CCC>/`. Every report names the WIP Project,
snapshot date/fingerprint, REFERENCE Project and fingerprint, and `GRK`/`HEB` only when
advanced RTC option `#10` routed that evidence. This output is never a Paratext Project directory.

## Source Text Correspondence (STC)

```text
WIP Project only
  -> choose GRK for NT or HEB for OT
  -> compare bounded WIP + exact OL authority
  -> report by Job / Book / chapter
```

STC never requests, stores, validates, or uses a REFERENCE Project. Its reports name the
actual WIP Project and exact `GRK` or `HEB` authority; generic `WIP`, `source`, or
`GRK:PRIMARY` labels are not operator-facing authority identities.

Targeted Check and standalone Original-Language Review remain parked implementation for
future work and are not menu actions. RTC option `#10` is the supported advanced OL path.
RTC and STC never write external Scripture or Paratext Notes XML. Final note material is
simple copy/paste-ready plain text for the Operator to place into Paratext Notes manually.
