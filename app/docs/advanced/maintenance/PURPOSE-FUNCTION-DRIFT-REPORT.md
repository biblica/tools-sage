# SAGE purpose and function drift report

## Decision baseline

- The SAGE system grammar uses U.S. English (`en-US`).
- The system/interface language is workstation-level and does not own Job report language.
- Every Scripture Project used by BIC or SAW is accessed through one Job binding and the
  role-specific grammar profile selected by that Job.
- Every Job-produced human output is governed by that Job's required primary reporting language
  and optional secondary reporting language.
- The Job primary language is selected for its reporting audience and is independent of Scripture
  Project language.
- Any approved language of wider communication (`LWC`) may be the Job primary. Report tags use the
  existing canonical BCP-47-style policy (`en`, `fr`, `pt-BR`, and so on); interface locales such
  as `en-US` and `en-GB` remain a separate workstation concern.
- Machine records, identifiers, commands, paths, hashes, status codes, and Scripture coordinates
  remain canonical and unchanged across human reporting languages.

## Cross-layer findings

| Surface | Current function | Assessment |
| --- | --- | --- |
| Menus | The Main Menu, BIC/SAW Job menus, Job settings, Reports, and recovery are deterministic controller surfaces. Menu strings are hard-coded in English. | Functionally coherent, but the documentation overstates the current interface-language coverage. |
| Project access | A Job binds every BIC `SOURCE`/`DONOR`/`TARGET` or SAW `WIP`/`REFERENCE` resource and selects role-compatible grammar profiles. | Aligned with the required Job authority. |
| Job reporting | `job.yml` stores required `reporting.primary_language` and optional `secondary_language`; the global Operator language is only the new-Job default. | Aligned with Job authority. |
| English identity | Reports use canonical `en`; workstation interface localization independently distinguishes `en-US` and `en-GB`. | Aligned with the separate report/interface contracts. |
| Skills | Six analytical Skills map one-to-one to BIC/SAW operations and are routed into sealed ACT tasks. Consolidation is deterministic Python and is not registered or routed as an AI Skill. | Aligned; the analytical/controller distinction is explicit. |
| Generated prompts | ACT prompts carry the owning Job, Run, role bindings, selected Skill, grammar evidence, scope, exact output allowlist, and explicit Job-owned narrative language. | Aligned; interface and optional secondary language are excluded from canonical narrative authority. |
| Reports | Canonical Job data and root-level polished reports are separated. Published reports remain after Job-directory removal. | Storage is aligned after correcting removal and path documentation. |

## Simple corrections completed

- Renamed the governing document to `SAGE-SYSTEM-GRAMMAR.md` and made U.S. English its canonical
  editorial standard without changing Scripture Project grammar identity.
- Corrected **Scan Paratext Projects**, the vocabulary-only BIC `DONOR` description, and the
  duplicated report path example.
- Clarified guided **Manage Jobs** versus the Main Menu's BIC/SAW Job surfaces.
- Clarified that **Remove Job** removes the Job directory but leaves separately published root
  reports in place.
- Corrected the generated Job README description of Job-local diagnostics, exports, and root-level
  polished reports.
- Kept the changelog compact, version-grouped, and bullet-only.

## Major adjustment implemented

1. Bump the Job manifest contract and require:

   ```yaml
   reporting:
     primary_language: en
     secondary_language: null
   ```

2. Treat the workstation setting as `system_interface_language`; do not use it as a Job report
   fallback after a Job is created.
3. Keep canonical report tags governed separately from regional interface locales.
4. Update Add Job and Job settings menus to require a primary reporting language and optionally
   choose a distinct secondary language.
5. Derive both human-output channels in `.sage/runtime.yml` exclusively from the Job manifest.
6. Pass the exact Job reporting tags through ACT manifests, model messages, consolidation,
   Operator notes, report headers, receipts, and validation.
7. Add tests proving that a global default or interface change cannot alter an existing Job's
   reports and that no Project can be accessed outside its Job bindings.
8. Externalize or otherwise fully route menu labels before describing the bundled human-output
   catalog as a complete main-interface profile.

Implementation now persists required Job-owned primary and optional secondary reporting tags,
binds the primary into narrative-generating ACT/provider contracts, and keeps interface and
secondary languages outside canonical narrative generation. The canonical report tag remains the
existing BCP-47-style value (`en`, `fr`, `pt-BR`, and so on); regional interface locale identity is
not reused as report-language authority.
