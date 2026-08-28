# RWC and Semantic Domain Indexes

SAGE `0.02alpha1` uses one governed SAGE-local semantic-index layer shared by BIC and SAW. RWC means **Rapid Word Correction**.

## Non-negotiable boundaries

- **Local first:** deterministic parsing, lookup, indexing, arithmetic, routing, validation, and reporting happen locally whenever reliable local computation is possible.
- **SEMDOM is classification/retrieval metadata, not translation authority.**
- **Import provenance is not content authority.** FLEx, Combine, RWC seed data, frequency, occurrence, and prior project resources are `PROJECT_INDEX_EVIDENCE`; their provenance limits what they may support.
- `KKH` is the semantic/language namespace. `idKKHv0` is the Paratext/PTLite project/resource identifier. Bindings are explicit.
- Locality alone does not establish authority. Project-index material must be explicitly imported/merged, governed, selected for the project namespace, and used only according to its provenance. The runtime provides no specialized external Greek biblical-workbook import path.

## Evidence states

SAGE recognizes:

1. `SEED`
2. `OBSERVED`
3. `TEAM_CONFIRMED`
4. `ESTABLISHED`
5. `APPROVED`

RWC seed imports enter as `SEED`. FLEx and Combine imports always enter as `OBSERVED`. Import commands cannot grant `TEAM_CONFIRMED`, `ESTABLISHED`, or `APPROVED`.

Stronger states require a governed review action:

```sh
./system/bin/sage rwc review set \
  --language KKH \
  --sense-id SENSE_ID \
  --status TEAM_CONFIRMED \
  --reviewer LC \
  --note "Reviewed with project evidence"
```

Inspect exact local senses before review when needed:

```sh
./system/bin/sage rwc lookup --language KKH --form FORM
```

Review-state changes make the generated index **STALE** for BIC, SAW, and export. Multiple senses may be reviewed against the same unchanged import/authority snapshot before one rebuild; `rwc lookup` overlays pending review states locally. Rebuild once the review batch is complete:

```sh
./system/bin/sage rwc index build --language KKH
```

## Normal initialization workflow

Import or merge only the project-index resources that the Operator has authorized for SAGE-local use. A typical project setup is:

```sh
./system/bin/sage rwc authority semdom --file SemDom.json
./system/bin/sage rwc authority folders --file folder_divisions_specific_first.docx

./system/bin/sage rwc import seed \
  --file KKH-Luke.xlsx \
  --source-id KKH-Luke-RWC \
  --language KKH

# Optional governed lexical project-index snapshot
./system/bin/sage rwc import flex \
  --file KKH-current.lift \
  --source-id KKH-FLEx-current \
  --language KKH

./system/bin/sage rwc bind --project idKKHv0 --language KKH
./system/bin/sage rwc index build --language KKH
```

A configured `@GRK` resource may be bound to an already governed local project-index namespace when such an index exists. SAGE does not import an external Greek biblical-term workbook as Job evidence.

Index building is local. It does not download data, browse the web, or call an AI.

## Freshness contract

Every index build records a fingerprint of:

- active immutable import snapshots and their content hashes;
- selected SIL Semantic Domains authority data;
- selected RapidWords folder metadata;
- explicit reviewed evidence states.

`rwc status` reports one of:

- `CURRENT` — exact inputs still match the build;
- `STALE` — source selection, authority, or review state changed;
- `MISSING` — no generated index manifest exists;
- `INVALID` — index/input integrity cannot be verified.

```sh
./system/bin/sage rwc status --language KKH
```

A bound BIC/SAW project may not consume a `STALE` or `INVALID` semantic index. FLEx/Combine export also fails closed until the index is rebuilt.

## Core local indexes

SAGE generates:

1. **Lexical-head index** — all seed/import headwords used for retrieval and exchange.
2. **Lemma index** — only records with explicit lemma/lexeme authority; seed headwords do not become canonical lemmas by assumption.
3. **Sense/SEMDOM index** — project/reference senses and Semantic Domain classifications.
4. **Surface-form index** — exact local retrieval without treating morphology as separate lexical identity.
5. **Key-term index** — imported key-term markers as reference evidence.
6. **SEMDOM catalog** — selected SIL authority enriched with RapidWords traversal metadata.
7. **Reconciliation index** — stable external LIFT sense-identity duplicates/conflicts; uncertain string similarity is never auto-merged.
8. **Correspondence index** — reserved for governed LWC-sense ↔ LRL-sense relationships.
9. **Construction index** — reserved for sense plus argument/construction evidence.
10. **Decision index** — reserved for governed project translation decisions.
11. **Coverage index** — counts, freshness fingerprint, review counts, and reconciliation diagnostics.

## Stable-identity reconciliation

Multiple active FLEx or Combine snapshots can repeat the same stable external sense ID. SAGE may collapse **consistent repetitions of that stable identity for retrieval**. If two snapshots reuse the same stable external sense ID with materially different lexical/SEMDOM content, SAGE retains the conflict and exposes an `INDEX_IDENTITY_CONFLICT` triage signal.

SAGE does **not** auto-merge seed records or unrelated records merely because spelling, gloss, or SEMDOM appears similar.

## BIC use

Where a Scripture resource has an explicit semantic binding, BIC locally assembles exact semantic evidence before model reasoning. This can include:

- matching surface forms;
- indexed senses/SEMDOM classifications;
- locally established evidence states;
- key-term markers;
- later correspondence/construction/decision evidence.

The model may reason only from the routed local evidence. General linguistic competence can help parse and express that evidence, but model recall cannot supply contextual meaning, lexical meaning, Scripture content, or semantic equivalence. SEMDOM, frequency, seed evidence, or imported FLEx entries cannot themselves authorize a translation choice.

## SAW use

SAW may use local semantic signals to identify places worth interrogation. Multiple indexed senses, semantic dispersion, or stable-identity conflicts are **TRIAGE_ONLY**. A SAW finding still requires verification in the bounded Scripture evidence and follows the configured contemporary-reference/original-language authority rules.

## Advanced source selection

New imports are immutable and activated explicitly by the import process. Superseded snapshots can be deactivated without deleting provenance:

```sh
./system/bin/sage rwc import deactivate --language KKH --source-id OLD_SOURCE
./system/bin/sage rwc import activate --language KKH --source-id NEW_SOURCE
```

Changing active sources or authority selection makes existing indexes stale. These commands belong to advanced source management, not the routine workflow.
