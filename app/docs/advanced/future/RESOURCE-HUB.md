# Future Feature — SAGE Resource Hub

## Purpose

SAGE Core must contain only reviewed, tested, approved, release-controlled resources. Operator-
created, experimental, imported, or locally modified resources remain outside Core in `localdata`.
A future Resource Hub will provide the controlled bridge from local contribution to reusable SAGE
resources and plugins.

## Resource classes

| Class | Runtime location | Trust statement |
|---|---|---|
| Core | `SAGE/` | SAGE-reviewed and release-qualified |
| Plugin/extension | `localdata/plugins/` | Separately versioned and validated; not Core |
| User/local resource | `localdata/inputs/resources/` or Project data | Operator-owned; no SAGE Core validation claim |

## Candidate flow

```text
local/user resource
      -> submission package
      -> provenance + license checks
      -> schema/format validation
      -> security/static analysis
      -> compatibility tests
      -> human review
      -> classification
           -> rejected/feedback
           -> community resource
           -> approved plugin
           -> Core candidate
                  -> full Core qualification
                  -> normal release process
                  -> SAGE/
```

The Resource Hub must never write an unreviewed contribution directly into a running Core tree.
Promotion to Core occurs only through the normal source-control, QA, review, and release process.

## Planned capabilities

- contribution manifest, author/contributor metadata, provenance, and licensing;
- automated schema, format, compatibility, and security validation;
- deterministic test fixtures and qualification receipts;
- resource/plugin semantic versioning and dependency declarations;
- review states, rejection reasons, and resubmission;
- package signing/checksum and trust/status display;
- install/update/remove lifecycle for approved plugins;
- isolation/sandbox policy appropriate to plugin capability;
- Core-candidate promotion through pull request and full release gates;
- explicit UI distinction between Core, approved plugin, community/candidate, and local resources.

This is a planned feature, not part of the 0.01beta executable feature set.
