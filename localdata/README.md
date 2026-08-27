# SAGE localdata

This directory is the persistent, writable half of the portable SAGE bundle.

The visible layout separates ownership and purpose:

- `inputs/` — Operator-supplied resources, style guides, and semantic-domain data
- `work/` — active SAGE Projects, Jobs, and Runs, plus intermediate working material
- `reports/` — finalized human-facing reports
- `exports/` — portable export packages
- `plugins/` — locally installed extensions
- `.system/` — SAGE-managed settings, state, caches, logs, and Python runtime

Every item in this directory is ignored by Git except this README.

Do not commit local Scripture content, credentials, machine state, generated reports,
or `.system/`. Back up this directory separately before replacing a device or storage
volume. Application updates replace `../app/` and preserve this directory.
