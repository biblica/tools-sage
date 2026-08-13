# Versification

Every configured file reference includes its extension:

```yaml
versification:
  base_file: org.vrs
  custom_file: custom.vrs
```

`auto` is a resolution instruction, not a filename. During INIT/initialisation SAGE reports whether project-local `custom.vrs` was found, the resolution basis, confidence, override field, and impact.

Base VRS files reside directly under the projects root. A custom VRS may reside only inside its own project. SAGE composes the effective schema, hashes all source files, and routes VRS evidence into analytical tasks.

SAW preflight distinguishes ordinary mapped, merged, split, excluded, note-only, empty, and missing states. Structural candidates must be adjudicated before submission. BIC and SAW cannot silently substitute or centralise a project-local VRS.

A declared `LOCKED` state does not validate the VRS. Conflicting base/custom provenance or unsupported coordinates block the affected project until corrected and reinitialised.
