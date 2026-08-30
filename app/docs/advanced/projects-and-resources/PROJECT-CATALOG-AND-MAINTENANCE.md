# Paratext Project Catalog and Maintenance — v0.01beta2

## Operator model

SAGE keeps filesystem discovery separate from workflow role assignment:

```text
Paratext Projects root
  -> Scan
Paratext Project Catalog
  -> Discovered Project
Add Project to SAGE
  -> SAGE Project Inventory
Assign Project Role in BIC/SAW
  -> Job Binding
Create Job
  -> Run
  -> task
```

A **SAGE Project** is role-neutral. SOURCE, DONOR, TARGET, WIP, and REFERENCE exist only as Job bindings.

## Discovery and validation gates

SAGE deliberately separates **discovery** from **detailed validation**.

### Initial / Quick scan

Initial root setup and **Quick rescan** enumerate only immediate child directories of the configured Paratext/PTLite Projects root and test for the `settings.xml` marker path. They do **not** open or parse `settings.xml`, enumerate `.SFM`, read `canons.xml`, or read `custom.vrs`. A marker-bearing directory is therefore a **discovered candidate**, not yet a validated Project.

New candidates enter the catalog with `detail_status: PENDING`. Previously validated rows may retain their cached detailed metadata while they remain present. Removed folders disappear from discovery immediately.

### Lazy validation

When the Operator selects/uses a PENDING Project for an operation that requires detailed metadata, SAGE validates that Project only. This opens the required metadata and Scripture inventory for that one Project and updates its catalog row.

### Full rescan

**Full rescan** validates every marker-bearing Project, rebuilds detailed catalog metadata, and classifies readiness/warnings/invalid folders. Use Full rescan for deliberate whole-root validation or recovery, not normal startup.

The catalog at `localdata/.system/state/paratext-project-catalog.json` therefore records discovery and detailed-validation state separately. User-facing summaries show **discovered**, **validated**, and **pending** counts rather than presenting raw catalog JSON.

The shared lightweight resource-discovery snapshot uses the same principle for configured resource roots: compare immediate tree names to the prior snapshot, report additions/removals, and never open resource contents during the quick check.

## Metadata and language resolution

During lazy validation or Full rescan SAGE reads, without modifying Paratext:

- `settings.xml` — `Language`, `FullName`, `LanguageIsoCode`;
- `canons.xml` — declared included books when detectable;
- top-level `.SFM` files — actual readable Scripture inventory;
- `custom.vrs` — descriptive versification comments;
- folder name — governed Project-code and language-prefix evidence.

Declared language codes are checked against SAGE's bundled ISO language data. A valid declared ISO identity is accepted even if no SAGE language-analysis profile exists yet. A folder prefix is secondary evidence only. Missing or invalid language metadata produces Operator suggestions; SAGE never silently replaces an ambiguous identity.

A missing language-analysis profile does **not** prevent **Add Project to SAGE**. It may block later Job setup or a language-specific operation when that role actually requires such a profile.

Language identity relationships are explicit, not profile aliases. SAGE preserves the resolved ISO identity and regional Language Profile. For example, Persian `fa/fas` may have Iranian Persian `pes` as a member identity and `pes-IR` as a regional working profile. Project-name prefix evidence remains advisory and never rewrites Paratext metadata or collapses `pes` into `fa`. Legacy `profile_alias` values may be read for migration only and are not offered in current Operator setup.


## Scope and filters

The Add Projects to SAGE list supports:

- **Full Bible (FB)**;
- **New Testament (NT)**;
- **Portions**;
- **Language**, built dynamically from catalogd metadata.

No workflow-role filter belongs in Project discovery.

## Versification

`custom.vrs` comments may provide descriptive base information. If no base reference is present, SAGE displays `custom.vrs (base unknown)` rather than inventing one.

The **Base VRS root defaults to the configured Paratext Projects root**. An explicit Operator Base VRS override remains in force when the Paratext root changes. Clearing the override returns to the Paratext-root default.

Standard USFM peripheral books (`FRT`, `INT`, `BAK`, `CNC`, `GLO`, `TDX`, `NDX`, `OTH`, and `XXA`–`XXG`) remain part of the Project resource fingerprint but are not treated as books in the declared biblical canon or compiled as verse-bearing Scripture.

When `custom.vrs` names a configured base VRS that differs from the stored Project selection, **Validate active Job** presents the detected change for Operator approval before validation. It never silently changes the Project's versification settings.

## Scripture Projects menu

```text
╔══════════════════════════════════════════════════════════════════════╗
║ SCRIPTURE PROJECTS                                                   ║
╚══════════════════════════════════════════════════════════════════════╝

Paratext Projects root: <configured path> | NOT CONFIGURED

  1. List / manage SAGE Scripture Projects
  2. Add Projects to SAGE
  3. Remove Project from SAGE
  4. Language Profiles
  5. Validate SAGE Projects
  6. Paratext Projects root
  7. Scan Paratext Projects
  8. Original-language resources
  9. Advanced resources

┌──────────────────────────────────────────────────────────────────────┐
│  A. Back   B. Main Menu   C. Exit SAGE                               │
│  D. Language   E. Help   F. Status                                   │
└──────────────────────────────────────────────────────────────────────┘
```

The long Paratext catalog appears only under **Add Projects to SAGE**, not inside BIC/SAW role selection.

A Project detail screen uses these sections:

```text
# Details ______________________________________________________________
# Project Settings _____________________________________________________
# Maintenance __________________________________________________________
# Advanced _____________________________________________________________
```

**Remove Project from SAGE** is visible directly on this menu and remains available on each Project detail screen. It removes SAGE-owned inventory/mapping state only. It never deletes or modifies the Paratext Project or Scripture files. Removal is blocked while any Job, including an archived Job, still binds the Project.

## Job roles

BIC assigns SAGE Projects as SOURCE, DONOR, and TARGET. SAW assigns SAGE Projects as WIP and REFERENCE. One SAGE Project may be used by multiple Jobs in different permitted roles.

TARGET write authority is granted only by an explicitly authorized BIC TARGET Job binding. Project inventory membership itself does not grant write authority.

## Reporting languages

The global Operator language defaults to `en` and supplies the primary-language default captured when a Job is created. Normal menus expose only `approved` languages and configured `candidates`; a `pilot_only` tag must be added manually to `human_output.operator_language_policy.candidates` by an advanced Operator before evaluation. Each Job owns one required primary reporting language and may add one optional secondary language. Projects carry Scripture identity and capabilities only; they do not own language settings or report files. Canonical report data remains Job-owned; polished reports are published to root `localdata/reports/<job-id>/`.

## Original-language resources

`@GRK` and `@HEB` are governed Scripture resources and remain separate from the ordinary SAGE Project Inventory. They may use bundled authorized resources or explicit Operator-selected sources. Discovery never automatically changes OL authority.
