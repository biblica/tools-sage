# SAGE Project-Management Logs

This directory is the source-controlled project-management ledger for SAGE. It tracks work against
the release identity in the root `VERSION` file without mixing planning records with mutable
Operator data, Job evidence, or generated reports.

## Files

- [Build Issues](BUILD-ISSUES.md) records build, packaging, test-environment, and release-gate
  problems that need diagnosis or resolution.
- [TODO](TODO.md) records accepted, actionable work that has not yet been implemented and verified.
- [Implemented Updates](IMPLEMENTED-UPDATES.md) is the append-only completion log for verified
  changes.
- [Milestones](MILESTONES.md) rolls issues, work, and completed updates into release-level PM
  outcomes.
- [Release Cleanup](RELEASE-CLEANUP.md) is the repeatable release-closeout checklist and exact
  evidence record.
- [Versioning Policy](VERSIONING-POLICY.md) governs product-version spelling, promotion gates,
  release states, tags, artifact names, synchronized surfaces, and historical-label handling.

## Authority boundaries

- `VERSION` remains the canonical current version; `VERSIONING-POLICY.md` governs how it changes.
- `system/config/CHANGELOG.md` remains the compact version-by-version product changelog.
- `docs/advanced/release/RELEASE-NOTES.md` remains the release-facing summary.
- `system/config/DEVELOPMENT-STATUS.md` remains the internal capability and qualification statement.
- `system/config/NEXT-DEVELOPMENT-WORK.md` remains the internal higher-level development roadmap.
- These files provide the operational PM trace between those documents.

## Entry rules

1. Use ISO dates (`YYYY-MM-DD`) and a stable ID that is never reused.
2. Record the target version and milestone on every issue, TODO, and implemented update.
3. Link a TODO to its originating build issue when applicable.
4. Do not delete closed records. Update their status and add closure evidence.
5. When work is verified, close the TODO, add an Implemented Update entry, and update its milestone.
6. Run Release Cleanup for every release attempt and attach its exact-source evidence to the
   milestone.
7. Summarize release-significant completed work in the changelog and release notes.
8. Apply the Versioning Policy before changing any product identity or creating a release tag.

Tracked records use Markdown rather than `.log` files because `.log` is reserved for generated
runtime diagnostics and excluded from source control.
