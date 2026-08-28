# Full Process Flow

```text
Start SAGE
  -> preflight Python/runtime dependencies
  -> complete/verify Codex + ChatGPT setup when AI work is required
  -> choose SAGE Projects
  -> choose/create one independent BIC or SAW Job
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

## SAW Reference Text Comparison (RTC)

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
        +--> reports/<BOOK>/<BOOK>_<CCC>_RTC_ACTION-REPORT.md
        `--> reports/<BOOK>/<BOOK>_<CCC>_RTC_OPERATOR-NOTE.txt
```

Each AI stage is an isolated governed task inside the same Run. The structural stage is covered only for routed structural-candidate coordinates; the required meaning stage covers the complete parent RTC Run scope. Structural and meaning stages receive no OL Scripture. The meaning stage may defer exact issues to OL using request IDs plus reserved deferred finding IDs. Only the selective OL stage receives the exact requested coordinates and configured Job-bound GRK/HEB evidence. It must return one structured OL resolution per request; finalization preserves that request/resolution ledger.

Run-local tasks, validation receipts, and raw final results remain governed Job provenance.
Deterministic finalization consolidates compatible chapter results, stores the canonical combined
record under Job `report_data/`, and publishes polished files to
`localdata/reports/<job-id>/<BOOK>/`. This output is never a Paratext Project directory.

## Separate SAW operations

`Targeted Check` remains one bounded WIP+REFERENCE question with no OL Scripture. `Original-Language Review` remains a separate bounded operation with configured Job-bound GRK/HEB evidence.

SAW never writes external Scripture or Paratext Notes XML. Final note material is simple copy/paste-ready plain text for the Operator to place into Paratext Notes manually.
