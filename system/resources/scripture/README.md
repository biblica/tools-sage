# Scripture resources

The clean SAGE build contains shared `eng.vrs` and `org.vrs` files plus the governed bundled `@GRK` and `@HEB` resources under `original-language/`. Ordinary translation Project folders do not belong here; they remain in Paratext/PTLite or in `SAGEdata/projects/` when SAGE owns the storage.

Add ordinary Projects through the SAGE Project Inventory. During `sage project init`, SAGE compiles the selected Project language profile, Job-assigned roles, content state, scope, canon, observed coverage, and complete VRS filenames for Operator review. SAGE never infers Project authority from a folder name.

## Required practice

- Keep every SOURCE, DONOR, REFERENCE, WIP, and original-language resource read-only.
- Declare a BIC TARGET explicitly; do not create one by copying a SOURCE directory.
- Use USFM book filenames owned by the target project, not filenames inherited from a source project.
- Record Project scope and canon in SAGE state; folder contents do not expand Job authority.
- Add a Project-specific VRS only after an authoritative Project decision.
- Treat `content_state: LOCKED` as a trust boundary, not as an error.
