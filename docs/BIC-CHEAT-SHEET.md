# BIC cheat sheet

Use BIC to rewrite one bounded LWC SOURCE into a generated TARGET. A separate DONOR contributes vocabulary evidence only.

```text
SOURCE + DONOR -> TARGET
```

SOURCE is the sole content/translation authority. DONOR is lexical evidence only. TARGET is a write destination and pre-existing TARGET Scripture is not routed during INSPECT or REWRITE.

**Evidence invariant:** content evidence is SAGE-local and governed. Use only sealed SOURCE, lexical-only DONOR, explicitly routed OL, authorized project-index evidence, and derived packs traceable to those sources. Model recall/pretraining, external Scripture/translations/lexicons/commentary, web/search, and unstated facts are prohibited as evidence. General model competence is limited to orthography, morphology, grammar, and syntax and may not supply missing content.

## Natural-language entry

```bash
./system/bin/sage --settings FILE.yml request "Prepare 3 John from KKH to BOL"
```

Confirm SOURCE, DONOR, TARGET, scope, and canonical command before execution.

## Preparation

```bash
./system/bin/sage --settings FILE.yml status
./system/bin/bic --settings FILE.yml status
```

If RWC/SEMDOM evidence is bound to a Scripture resource, confirm its index is `CURRENT`. Recovery/reset commands are not routine preparation.

## Required operation order

```text
INSPECT
-> submit INSPECT
-> optional memory-review provenance
-> REWRITE
-> submit REWRITE and stage candidate
-> isolated SELF-CHECK
-> submit SELF-CHECK and journaled TARGET commit (bounded merge)
-> optional generation publication
```

## 1. INSPECT

```bash
./system/bin/bic --settings FILE.yml inspect \
  --source idKKHv0 \
  --donor usNIVv2 \
  --target usBOLx1 \
  --scope "3JN 1:1-15"

./system/bin/bic --settings FILE.yml submit \
  --task SAGEdata/.system/workflows/bic/output/active/INSPECT_TASK_ID/task-manifest.json
```

INSPECT receives bounded SOURCE Scripture, SOURCE grammar/evidence, and a decontextualized DONOR vocabulary packet. It does not receive donor verse text, pre-existing TARGET Scripture, or routine OL Scripture.

## 2. Optional memory-review provenance

```bash
./system/bin/sage --settings FILE.yml memory review \
  --scope "3JN 1:1-15" \
  --decision-id REVIEW_ID \
  --reviewer "REVIEWER_NAME" \
  --decision APPROVED_FOR_REWRITE
```

This records human attention only. It does not gate REWRITE or promote individual memory records to `APPROVED_FOR_USE`.

## 3. REWRITE

```bash
./system/bin/bic --settings FILE.yml rewrite \
  --source idKKHv0 \
  --donor usNIVv2 \
  --target usBOLx1 \
  --scope "3JN 1:1-15" \
  --grammar-override-id GRAMMAR_REVIEW_ID

./system/bin/bic --settings FILE.yml submit \
  --task SAGEdata/.system/workflows/bic/output/active/REWRITE_TASK_ID/task-manifest.json
```

REWRITE applies the complete protected BIC contract. SOURCE remains exclusive content authority. DONOR may help with vocabulary but may not supply wording, sequence, syntax, propositions, participant structure, or discourse. Existing TARGET Scripture is not input evidence.

A successful REWRITE submission returns `STAGED_VALIDATED` or `STAGED_VALIDATED_WITH_CHALLENGES`; it does not commit TARGET.

Conditional OL evidence may be opened only under the pinned material-risk policy. v0.01beta releases each material challenge separately as a micro-adjudication: raw SOURCE and applicable OL Scripture are restricted to that challenge's single verse, only relevant local evidence is routed, and a `VERB_CHOICE` referral asks only for the disputed verb's verbal sense/function. The provider returns a bounded semantic decision/optional one-verse replacement; SAGE merges it into the existing REWRITE locally instead of re-sending and regenerating all REWRITE outputs. Surrounding Scripture is not added automatically. Linguistic risk never asks the Operator to choose or override a candidate.

## 4. SELF-CHECK

```bash
./system/bin/bic --settings FILE.yml self-check \
  --source idKKHv0 \
  --donor usNIVv2 \
  --target usBOLx1 \
  --scope "3JN 1:1-15" \
  --predecessor-task SAGEdata/.system/workflows/bic/output/active/REWRITE_TASK_ID/task-manifest.json \
  --grammar-override-id GRAMMAR_REVIEW_ID

./system/bin/bic --settings FILE.yml submit \
  --task SAGEdata/.system/workflows/bic/output/active/SELF_CHECK_TASK_ID/task-manifest.json
```

SELF-CHECK receives the sealed REWRITE candidate because that candidate is the object under check. A successful submission journal-commits only the governed scope into the bound TARGET book; all out-of-scope TARGET content and an existing mapped Paratext book filename are preserved. This does not make pre-existing TARGET Scripture an authority source. SELF-CHECK also receives the bounded SOURCE and governed evidence required by the protected contract, but no first-pass rationale.


## Scope restart, history, and revert

```bash
./system/bin/sage --settings FILE.yml project restart-scope --job BIC_JOB_ID --scope "3JN 1:1-15"
./system/bin/sage --settings FILE.yml project target-history --job BIC_JOB_ID --scope "3JN 1:1-15"
./system/bin/sage --settings FILE.yml project revert-target-scope --job BIC_JOB_ID --scope "3JN 1:1-15"
```

`Restart Scope` discards/restarts incomplete analytical Run state and does **not** edit committed TARGET Scripture. `Revert TARGET Scope` is the explicit translation rollback operation and restores only the selected scope to its immediately preceding committed state. General recover/reset/stale-lock/index-rebuild operations never serve as TARGET undo commands.

## 5. Optional generation publication

```bash
./system/bin/sage --settings FILE.yml generation publish --project usBOLx1
```

A technical generation is not linguistic approval.

## Non-negotiable controls

- BIC binds one bound SOURCE resource, one bound DONOR resource, and one bound TARGET resource; the three resources are distinct.
- A BIC project may configure one Greek resource and/or one Hebrew resource. Neither is routine INSPECT evidence; the applicable configured OL resource is required only if REWRITE actually triggers a bounded OL check.
- Apply the protected rewrite-detail and verb-selection contracts byte-for-byte as pinned.
- Use `REWRITE` as the sole canonical BIC target-text production operation.
- Use only memory already marked `APPROVED_FOR_USE`.
- `APPROVED_FOR_USE` BIC memory must originate from governed INSPECT evidence for the same Job; generic lexicon imports cannot acquire Job content authority through approval.
- Treat DONOR strictly as vocabulary evidence; never route donor Scripture text.
- Never read pre-existing TARGET Scripture during INSPECT/REWRITE.
- Treat lexical burden as a tie-breaker after semantic hard gates.
- Local semantic/index evidence is retrieval/triage evidence, not translation authority.
- Recreate an invalid task instead of editing `ACT.md` or `task-manifest.json`.

Recoverable missing or ambiguous Operator input is `INPUT_REQUIRED`. Reserve `BLOCKED` for confirmed in-scope technical or integrity failure.
