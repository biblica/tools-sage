# ATT Architecture

## 1. Scope boundary
ATT is a recurring-term consistency checker.

ATT does:
- index recurring SOURCE lexical units and phrases;
- map their occurrences to TARGET renderings;
- detect departures from established TARGET recurrence patterns;
- account for morphology, syntax and orthography so normal language variation does not create false positives;
- support translation-brief-defined single and dual reference modes;
- report variations for review.

ATT does not:
- determine whether TARGET is generally semantically faithful;
- validate SOURCE against original languages;
- override the trusted SOURCE with OL evidence;
- perform RTC/STC judgments;
- infer which reference text should be authoritative.

## 2. Core terminology

SOURCE
: The trusted input text against which recurring terminology is indexed.

TARGET
: The translation being reviewed for consistency.

PRIMARY_REFERENCE
: The primary trusted reference translation specified by the Translation Brief.

SECONDARY_REFERENCE
: An additional trusted reference specified by the Translation Brief.

OL
: Original-language resources. Not part of ATT core authority unless OL itself is configured as SOURCE.

REFERENCE_PACKAGE
: A versioned, immutable bundle containing a prebuilt SOURCE recurrence index and metadata.

PROJECT_OVERLAY
: Local, mutable project data such as custom terms, custom phrases, approved exceptions and project-specific policies.

## 3. Analysis streams

### Stream A - Lexical recurrence
Subclasses:
- A1 named entities / proper nouns
- A2 key concepts / terminology
- A3 key verbs
- A4 monitored lexical families

Primary unit:
`SOURCE lemma / normalized term / source recurrence family`

The implementation should not assume exact string equality where morphology or orthography varies.

### Stream B - Phrase recurrence
Subclasses:
- B1 fixed / recurring phrases
- B2 creeds / confessional formulae
- B3 technical or community jargon
- B4 rhetorical / discourse formulae

Primary unit:
`SOURCE phrase family / normalized recurring expression`

Phrase findings are separate from lexical findings even when they overlap.

## 4. Shared processing pipeline

```text
SOURCE PACKAGE / SOURCE TEXT
          |
          v
NORMALIZATION + TOKENIZATION
          |
          v
SOURCE RECURRENCE INDEX
          |
          +-------------------+
          |                   |
          v                   v
    LEXICAL RUN          PHRASE RUN
          |                   |
          +---------+---------+
                    v
             TARGET ALIGNMENT
                    |
                    v
       TARGET RENDERING GROUPS
                    |
                    v
         CONSISTENCY FINDINGS
                    |
                    v
       RECONCILIATION / REPORT
```

## 5. Normalization principles

ATT must distinguish between:
- semantic / lexical identity;
- morphology;
- syntax;
- orthography;
- phrase-level realization.

Expected normal variants should not be reported as inconsistent.

Suggested classifications:
- CONSISTENT
- MORPHOLOGICAL_VARIANT
- ORTHOGRAPHIC_VARIANT
- APPROVED_RENDERING_VARIANT
- CONTEXTUAL_VARIANT
- UNIQUE_RENDERING
- POSSIBLE_INCONSISTENCY

ATT's role is detection and classification, not general semantic adjudication.

## 6. Run topology from Translation Brief

### SINGLE
```text
SOURCE -> TARGET -> ATT findings
```

### DUAL_HIERARCHICAL
```text
PRIMARY -> TARGET -> core finding
SECONDARY -> correlation against finding
```

Primary defines the baseline. Secondary does not override it.

### DUAL_COAUTHORITATIVE
```text
SOURCE A -> TARGET -> ATT-A
SOURCE B -> TARGET -> ATT-B
                
        RECONCILIATION
```

Where the references differ, report the divergence rather than manufacture one expected answer.

## 7. Static vs local dynamic data

### Canonical static resources
Prebuilt, immutable, versioned, shipped with SAGE.

### Local project data
Dynamic and local only.
Stored under project input/config paths.
Must never mutate canonical indexes.

Local term/phrase input is resolved exclusively against the configured SOURCE.

## 8. Persistence model

Indexes are durable reference state.
Runs are disposable/auditable analysis events.

A run should record at minimum:
- run_id
- source_ref_id(s)
- source version(s)
- target checksum/version
- reference package version(s)
- ruleset version
- timestamp
- findings

## 9. Unified finding model

Suggested fields:
- finding_id
- run_id
- stream: lexical | phrase | combined
- source_ref_id
- source_term_or_phrase_id
- source_location(s)
- target_location(s)
- finding_type
- expected_pattern
- observed_pattern
- recurrence_count
- dominant_rendering
- variant_rendering
- confidence
- correlation_status
- exception_status
- rationale

## 10. Design rule to lock

ATT evaluates consistency of recurring SOURCE material in TARGET. It inherits authority from the Translation Brief and never substitutes another textual authority during normal ATT execution.
