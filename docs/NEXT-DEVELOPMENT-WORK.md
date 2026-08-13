# Next Development Work

1. Run native **Windows** acceptance with a real Paratext Projects root: catalogue scan/progress, Add Project to SAGE, Base VRS default/override, ISO-language review, BIC/SAW Job add/remove, safe Project removal, Codex ChatGPT login, and one governed BIC/SAW cycle.
2. Run native **macOS** acceptance with a Projects-root path containing spaces, `<Other location>`, custom VRS reporting, scan/progress, Job role selection, explicit OL configuration, Codex ChatGPT login, and one governed BIC/SAW cycle.
3. Exercise Normal SAW QA against representative real Project scopes to tune deterministic preflight thresholds and selective-OL request granularity without changing authority boundaries.
4. Exercise broad Book/section scopes on real translations to validate the RC7.04 pre-Run work/token preview, structural splitting, and Change-scope recovery path under realistic text sizes.
5. Continue menu-first convergence for any remaining low-frequency CLI-only maintenance actions; keep direct CLI syntax documented as a shortcut rather than the primary operator story.
6. Decide during beta whether to retire the narrow internal compatibility aliases whose Python names still contain legacy Project-registration terminology. They are not operator-facing and should not be renamed during RC7 without a migration reason.
7. Define beta-stage migration for existing `state/project-registry.json` installations to `state/project-inventory.json`; RC releases remain forward-only and do not ship RC-to-RC operator-state migration.
8. Evaluate later provider enablement only after RC7 interaction grammar stabilises. Ollama/LM Studio remain provisionable but execution-disabled; Grok/Gemini remain future adapters.
9. Continue regression testing of protected BIC rewrite-detail and verb-selection rules. Keep WDA and existing-target revision parked as separate future work.
