# Resource rights and provenance

Each configured Scripture project requires one YAML file named `PROJECT_ID.yml` in a `projects` metadata directory.

```yaml
schema_version: '1.0'
project_id: usNIVv2
provenance:
  source_name: Authoritative source title
  source_version: Publisher version or edition
  source_archive_sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
  import_authority_id: IMPORT-DECISION-001
  imported_utc: '2026-08-05T00:00:00Z'
rights:
  status: CONFIRMED
  copyright_holder: Rights holder
  license_identifier: Governed license or agreement identifier
  authority_record_id: RIGHTS-DECISION-001
  import_authorized: true
  redistribution_authorized: true
  distribution_scope: Controlled SAGE evaluation handover
  reviewed_utc: '2026-08-05T00:00:00Z'
```

Generated Scripture uses `rights.status: NOT_APPLICABLE_GENERATED` and additionally requires `rights.generation_authority_record_id`. This does not waive rights for source resources used to generate it.

Run:

```bash
./system/bin/sage resource validate-rights
```

Legacy metadata remains evidence but does not pass schema `1.0` until a responsible human supplies the missing authority fields. SAGE must not infer copyright, license, import authority, or redistribution permission from file presence, project role, or technical validation status.
