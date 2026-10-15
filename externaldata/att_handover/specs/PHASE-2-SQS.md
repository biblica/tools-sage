# ATT Phase 2 - SQS Reference Data Service

## Goal
Move reference identity, distribution and extensibility into SQS without changing ATT analysis contracts.

## Principle
Phase 2 changes distribution and administration, not ATT core logic.

```text
Phase 1: shipped file -> reference package -> ATT
Phase 2: SQS -> reference package -> local cache -> ATT
```

## SQS responsibilities
- Source Registry
- source/reference identity
- metadata
- versioning
- checksums
- licensing/entitlement classification
- index generation pipeline
- validation
- approval/publishing workflow
- deprecation/revocation
- package distribution
- client cache/version resolution

## Advanced operator ingestion
Lifecycle:

```text
DRAFT
  -> VALIDATING
  -> INDEXED
  -> REVIEWED
  -> APPROVED
  -> PUBLISHED
  -> DEPRECATED
```

Suggested roles:
- SQS_OPERATOR: upload/register and validate
- SQS_REFERENCE_ADMIN: approve/publish
- SQS_SUPERADMIN: replace/deprecate/revoke canonical sources

## Ingestion types

### FULL_TEXT
SQS may retain source text and indexes where permitted.

### INDEX_ONLY
SQS may process supplied text but retains only permitted derived data.

### EXTERNAL_REFERENCE
SQS stores identity, metadata, checksum and compatible indexes while text remains external/local.

## Canonical metadata
- source_id
- display_name
- language
- edition/version
- source_type
- versification
- textual_tradition if applicable
- publisher/owner
- license_class
- provenance
- checksum
- index_schema_version
- resource_version
- status

## Future OL migration
Existing OL resources may later register under the same SQS Source Registry and package/version model.
This is a future extensibility feature and not an ATT Phase 1 dependency.

## Compatibility requirement
Phase 2 must serve the same canonical reference package schema defined in Phase 1.
ATT should not care whether the package came from the local SAGE distribution or SQS.
