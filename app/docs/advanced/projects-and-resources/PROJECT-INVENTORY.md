# SAGE Project Inventory and Paratext Catalog — v0.02alpha1

SAGE ships with **zero SAGE translation Projects**. Static product policy remains in `ecosystem.yml`. Operator-selected Projects are persisted in `localdata/.system/state/project-inventory.json`; derived Paratext discovery metadata is stored separately in `localdata/.system/state/paratext-project-catalog.json`.

## Canonical lifecycle

```text
Scan -> Discover -> Add to SAGE -> Configure -> Validate
     -> Assign role -> Create Job -> Choose scope -> Preview work -> Run -> Review results
```

The operator-facing nouns are:

- **Paratext Project Catalog** — cached filesystem discovery.
- **Discovered Project** — a candidate found by scanning.
- **Add Project to SAGE** — make a Project available to SAGE.
- **SAGE Project** — a Project in the persistent SAGE Project Inventory.
- **Assign Project Role** — choose SOURCE/DONOR/TARGET/WIP/REFERENCE during tool setup.
- **Job Binding** — the stored Project-to-role relationship inside a Job.

Do not use *register*, *registered*, or *unregister* for the SAGE Project lifecycle in operator-facing text; Paratext uses related terminology for other concepts.

## Role-neutral inventory

Adding a Project to SAGE records Scripture identity, language metadata, detected books/scope, location, VRS status, validation state, and short-code metadata. Report-language configuration belongs globally and to Jobs, never to Project inventory. Final workflow reports remain Job-owned. Adding a Project does not assign BIC/SAW roles and does not grant TARGET write authority.

BIC Job setup binds three SAGE Projects: SOURCE, DONOR, TARGET. SAW Job setup binds two: WIP, REFERENCE.

## Language identity

`settings.xml` `LanguageIsoCode` is normalized and checked against bundled ISO data. Valid ISO identity is accepted even if no SAGE language-analysis profile exists. Project folder prefix and human language name provide corroborating evidence. Missing/invalid values are presented for operator resolution; ambiguous suggestions are never applied silently.

Language-analysis profiles are checked later, when the selected Job role or operation requires one.

## External access

Ordinary SAGE Projects are read-only at inventory level. Effective access is derived from the Job. SOURCE, DONOR, WIP, and REFERENCE are read-only. Only an explicitly authorized BIC TARGET binding may receive governed `.SFM` writes. `.VRS` is always read-only.

## Safe removal

**Remove Project from SAGE** removes only SAGE state. It does not delete or modify the Paratext Project. SAGE blocks removal while a Job still uses the Project; remove or revise those Job bindings first.

`@GRK` and `@HEB` are governed original-language resources outside this ordinary Project Inventory.
