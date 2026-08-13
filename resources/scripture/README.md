# Projects directory

The clean SAGE build contains only shared `eng.vrs` and `org.vrs` files here. Scripture project folders belong in a populated workspace or controlled resource handover, not in the code-only build.

Register each project in the selected ecosystem YAML file. During `sage project init`, SAGE compiles the project language profile, explicit roles, content state, scope, canon, observed coverage, and complete VRS filenames for Operator review. SAGE never infers project authority from a folder name.

## Required practice

- Keep every source, reference, reviewed target, and original-language project read-only.
- Declare a generated target explicitly; do not create it by copying a source directory.
- Use USFM book filenames owned by the target project, not filenames inherited from a source project.
- Record project scope and canon in configuration; folder contents do not expand authority.
- Add a project-specific VRS only after an authoritative project decision.
- Treat `content_state: LOCKED` as a trust boundary, not as an error.
