# Paratext Project Catalogue and Maintenance — RC7.04

## Operator model

SAGE keeps filesystem discovery separate from workflow role assignment:

```text
Paratext Projects root
  -> Scan
Paratext Project Catalogue
  -> Discovered Project
Add Project to SAGE
  -> SAGE Project Inventory
Assign Project Role in BIC/SAW
  -> Job Binding
Create Job
  -> Run
  -> Task
```

A **SAGE Project** is role-neutral. SOURCE, DONOR, TARGET, WIP, and REFERENCE exist only as Job bindings.

## Discovery gate

SAGE scans only immediate child folders of the configured Paratext/PTLite Projects root. A folder is a Project candidate only when it contains a parseable `settings.xml` with recognised Project metadata. Folders without `settings.xml` are ignored. Malformed or metadata-empty metadata is listed as invalid and cannot be added to SAGE until corrected.

Normal menu rendering uses the persisted catalogue at `state/paratext-project-catalog.json`; it does not repeatedly rescan the full root.

During a scan the terminal shows one rotating status line such as:

```text
Scanning Paratext Projects... | 34/87
```

## Metadata and language resolution

For each discovered Project SAGE reads, without modifying Paratext:

- `settings.xml` — `Language`, `FullName`, `LanguageIsoCode`;
- `canons.xml` — declared included books when detectable;
- top-level `.SFM` files — actual readable Scripture inventory;
- `custom.vrs` — descriptive versification comments;
- folder name — governed Project-code and language-prefix evidence.

Declared language codes are checked against SAGE's bundled ISO language data. A valid declared ISO identity is accepted even if no SAGE language-analysis profile exists yet. A folder prefix is secondary evidence only. Missing or invalid language metadata produces operator suggestions; SAGE never silently replaces an ambiguous identity.

A missing language-analysis profile does **not** prevent **Add Project to SAGE**. It may block later Job setup or a language-specific operation when that role actually requires such a profile.

When the declared ISO identity and the Project-code prefix are different but consistent (for example, `pes` Iranian Persian metadata with an `fa` Persian prefix), Job setup checks whether the prefix names an existing role-compatible profile. SAGE may then offer an explicit menu action to add a `profile_alias` namespace to `ecosystem.yml` and retry. The Operator must approve this update; SAGE keeps the Project language as `pes` and does not rewrite Paratext, Project Inventory, or existing Job data.

```yaml
language_profiles:
  pes:
    script: Arab
    profile_alias: fa
```

An alias inherits the referenced namespace's variants. Its script must match, and aliases with unknown targets, cycles, or their own variants are rejected.

## Scope and filters

The Add Projects to SAGE list supports:

- **Full Bible (FB)**;
- **New Testament (NT)**;
- **Portions**;
- **Language**, built dynamically from catalogued metadata.

No workflow-role filter belongs in Project discovery.

## Versification

`custom.vrs` comments may provide descriptive base information. If no base reference is present, SAGE displays `custom.vrs (base unknown)` rather than inventing one.

The **Base VRS root defaults to the configured Paratext Projects root**. An explicit operator Base VRS override remains in force when the Paratext root changes. Clearing the override returns to the Paratext-root default.

Standard USFM peripheral books (`FRT`, `INT`, `BAK`, `CNC`, `GLO`, `TDX`, `NDX`, `OTH`, and `XXA`–`XXG`) remain part of the Project resource fingerprint but are not treated as books in the declared biblical canon or compiled as verse-bearing Scripture.

When `custom.vrs` names a configured base VRS that differs from the stored Project selection, **Validate active Job** presents the detected change for Operator approval before validation. It never silently changes the Project's versification settings.

## Scripture Projects menu

```text
SCRIPTURE PROJECTS
------------------------------------------------------------------------
1. SAGE Projects
2. Add Projects to SAGE
3. Validate SAGE Projects
4. Scan / Rescan Paratext Projects
5. Original-language resources
6. Advanced resources
0. Back
```

The long Paratext catalogue appears only under **Add Projects to SAGE**, not inside BIC/SAW role selection.

A Project detail screen uses these sections:

```text
# Details ______________________________________________________________
# Project Settings _____________________________________________________
# Maintenance __________________________________________________________
# Advanced _____________________________________________________________
```

**Remove Project from SAGE** removes SAGE-owned inventory/mapping state only. It never deletes or modifies the Paratext Project or Scripture files. Removal is blocked while any Job, including an archived Job, still binds the Project.

## Job roles

BIC assigns SAGE Projects as SOURCE, DONOR, and TARGET. SAW assigns SAGE Projects as WIP and REFERENCE. One SAGE Project may be used by multiple Jobs in different permitted roles.

TARGET write authority is granted only by an explicitly authorised BIC TARGET Job binding. Project inventory membership itself does not grant write authority.

## Reporting languages

The terminal UI remains English. Reports can be bilingual. A Project-specific reporting pair overrides global reporting defaults; BIC uses the TARGET Project's reporting settings and SAW uses the WIP Project's settings. This override selects rendering languages only. Final workflow reports remain in the owning Job's `reports/<BOOK>/` catalogue; the Project does not own or redirect them.

## Original-language resources

`@GRK` and `@HEB` are governed Scripture resources and remain separate from the ordinary SAGE Project Inventory. They may use bundled authorised resources or explicit operator-selected sources. Discovery never automatically changes OL authority.
