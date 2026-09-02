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

Adding a Project to SAGE includes an explicit scope confirmation. SAGE proposes the Project's `canons.xml` book list when available; otherwise it proposes the readable canonical top-level `.SFM` set. The Operator may accept that proposal or enter `OT`, `NT`, `FB`, individual USFM IDs, inclusive canonical ranges such as `LUK-ACT`, or unions such as `NT, PSA`. The resolved canonical book set becomes `scope.expected_books`; scope is never inferred from the short-name iteration suffix.

After import, the declared scope remains the authority boundary. A canonical `.SFM` file outside `scope.expected_books` is reported as out-of-scope inventory, retained in the whole-Project resource fingerprint, and excluded from USJ compilation and readiness. It does not block initialization; this permits early WIP material to coexist with the currently declared Project scope. To make that material operational, change the declared scope explicitly.

## Job roles

Roles are assigned by a Job binding, not inferred from or persisted as intrinsic Project roles. SAW binds `WIP` and `REFERENCE`; BIC binds `CONTENT_SOURCE`, `LEXICAL_DONOR`, and `GENERATED_TARGET`. Optional applicable `ORIGINAL_LANGUAGE_GREEK` / `ORIGINAL_LANGUAGE_HEBREW` bindings are also Job-scoped.

The same SAGE Project may serve more than one permitted purpose in different Jobs without duplicate SAGE Project entries.

## Lifecycle state versus access

- `LOCKED`: trusted content not being generated/revised by the current workflow.
- `UNDER_REVIEW`: content currently being generated or reviewed.

Lifecycle does **not** grant filesystem write permission. The SAGE Project Inventory records only maximum capability. Effective access is resolved from the Job: SOURCE, DONOR, REFERENCE, WIP, and OL are read-only; only an explicitly authorized BIC TARGET may write `.SFM`. `.VRS` is always read-only.
