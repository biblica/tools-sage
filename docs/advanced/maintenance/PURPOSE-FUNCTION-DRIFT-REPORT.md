# SAGE purpose and function drift report

## Decision baseline

- The SAGE system grammar uses U.S. English (`en-US`).
- The system/interface language is workstation-level and does not own Job report language.
- Every Scripture Project used by BIC or SAW is accessed through one Job binding and the
  role-specific grammar profile selected by that Job.
- Every Job-produced human output is governed by that Job's required primary reporting language
  and optional secondary reporting language.
- The Job primary language follows the target audience because one Operator may work across Jobs
  whose audiences require different languages or English variants.
- Any approved language of wider communication (`LWC`) with a governed reporting profile may
  replace the primary for a Job; `en-US` and `en-GB` are distinct English choices, not the only
  permitted primary languages.
- English reporting language must be explicit: use `en-US` or `en-GB`, never ambiguous `en`.
- Machine records, identifiers, commands, paths, hashes, status codes, and Scripture coordinates
  remain canonical and unchanged across human reporting languages.

## Cross-layer findings

| Surface | Current function | Assessment |
| --- | --- | --- |
| Menus | The Main Menu, BIC/SAW Job menus, Job settings, Reports, and recovery are deterministic controller surfaces. Menu strings are hard-coded in English. | Functionally coherent, but the documentation overstates the current interface-language coverage. |
| Project access | A Job binds every BIC `SOURCE`/`DONOR`/`TARGET` or SAW `WIP`/`REFERENCE` resource and selects role-compatible grammar profiles. | Aligned with the required Job authority. |
| Job reporting | `job.yml` stores only `reporting.secondary_language`; the primary language is inherited from global `human_output.operator_language`. | Major mismatch. The Job does not yet own its primary reporting language. |
| English identity | The global fallback and most tests use generic `en`. BCP 47 validation accepts regional forms, but policy and catalogs do not define distinct `en-US` and `en-GB` reporting profiles. | Major mismatch. U.S. and U.K. English cannot yet be selected and rendered as distinct governed reporting languages. |
| Skills | Six analytical Skills map one-to-one to BIC/SAW operations and are routed into sealed ACT tasks. Consolidation is deterministic Python and is not registered or routed as an AI Skill. | Aligned; the analytical/controller distinction is explicit. |
| Generated prompts | ACT prompts carry the owning Job, Run, role bindings, selected Skill, grammar evidence, scope, and exact output allowlist. Their reporting-language payload is derived from the Job runtime file. | Task governance is aligned; language authority drifts because the runtime primary still comes from the global setting. |
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

## Major adjustment required

1. Bump the Job manifest contract and require:

   ```yaml
   reporting:
     primary_language: en-US
     secondary_language: null
   ```

2. Treat the workstation setting as `system_interface_language`; do not use it as a Job report
   fallback after a Job is created.
3. Add separate vanilla reporting catalogs for `en-US` and `en-GB`, plus a governed approval path
   for other LWC reporting profiles. Map legacy reporting tag `en` to `en-US` only through an
   explicit pre-release migration or reject it at the new schema boundary.
4. Update Add Job and Job settings menus to require a primary reporting language and optionally
   choose a distinct secondary language.
5. Derive both human-output channels in `.sage/runtime.yml` exclusively from the Job manifest.
6. Pass the exact Job reporting tags through ACT manifests, model messages, consolidation,
   Operator notes, report headers, receipts, and validation.
7. Add tests proving that `en-US` and `en-GB` remain distinct, that a global interface change cannot
   alter an existing Job's reports, and that no Project can be accessed outside its Job bindings.
8. Externalize or otherwise fully route menu labels before describing the bundled human-output
   catalog as a complete main-interface profile.

Until this adjustment is implemented, current documentation must describe global-primary plus
Job-secondary behavior as the implementation state and this report as the approved target contract.
