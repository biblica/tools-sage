# Project scope, lifecycle, and Job roles

A SAGE Project declares language metadata, detected scope, lifecycle/content state, coverage policy, and versification. **Workflow roles are not stored as Project identity.**

```yaml
content_state: UNDER_REVIEW
scope:
  testament: PORTIONS
  canon: PROTESTANT_66
  expected_books: [JHN, PHP]
  roles: []
versification:
  base_file: eng.vrs
  custom_file: auto
```

## Scope values

- `FB`: complete Old and New Testaments under the declared canon.
- `OT`: complete Old Testament book set under the declared canon.
- `NT`: complete New Testament book set.
- `PORTIONS`: any smaller or mixed detected set.

Adding a Project to SAGE detects readable canonical top-level `.SFM` files. Scope is derived from those books, never from the short-name iteration suffix. A later validation may report scope drift if the mapped Paratext project changes after the Project was added to SAGE; SAGE does not silently reinterpret Job authority from a folder name.

## Job roles

Roles are assigned by a Job binding, not inferred from or persisted as intrinsic Project roles. SAW binds `WIP` and `REFERENCE`; BIC binds `CONTENT_SOURCE`, `LEXICAL_DONOR`, and `GENERATED_TARGET`. Optional applicable `ORIGINAL_LANGUAGE_GREEK` / `ORIGINAL_LANGUAGE_HEBREW` bindings are also Job-scoped.

The same SAGE Project may serve more than one permitted purpose in different Jobs without duplicate SAGE Project entries.

## Lifecycle state versus access

- `LOCKED`: trusted content not being generated/revised by the current workflow.
- `UNDER_REVIEW`: content currently being generated or reviewed.

Lifecycle does **not** grant filesystem write permission. The SAGE Project Inventory records only maximum capability. Effective access is resolved from the Job: SOURCE, DONOR, REFERENCE, WIP, and OL are read-only; only an explicitly authorized BIC TARGET may write `.SFM`. `.VRS` is always read-only.
