# File Naming and Serialization

SAGE uses file names to communicate ownership and data semantics. The format is part of the system contract, not a cosmetic preference.

## Canonical naming rules

| Surface | Naming rule | Examples |
|---|---|---|
| Current SAGE Markdown documents | uppercase kebab-case | `PROJECT-TREE.md`, `FILE-NAMING-AND-SERIALIZATION.md` |
| Conventional entry/readme files | preserve conventional name | `README.md`, `VERSION` |
| Python modules, tools, and tests | lowercase snake_case | `project_inventory.py`, `build_release.py` |
| CLI actions/options and Skill directories | lowercase kebab-case | `self-check`, `bic-self-check` |
| SAGE-owned config/policy/profile files | lowercase kebab-case + YAML | `model-policy.yml`, `structure-planning.yml`, `profile.yml` |
| SAGE-owned registries/manifests | lowercase kebab-case + JSON | `skills.json`, `sage-standard.json`, `sources.json`, `run.json` |
| SAGE schema specifications | lowercase kebab-case + `.schema.yml` | `job.schema.yml`, `skill-registry.schema.yml` |
| Runtime/generated machine state | lowercase kebab-case + JSON unless an external contract requires otherwise | `active-jobs.json`, `status.json`, `run.json` |
| Route qualification/override receipts | lowercase kebab-case + JSON in governed state roots | `llm-execution-receipt.json`, `model-routing-override.json` |
| Dynamic Project rights/config files | preserve governed Project ID + YAML | `idKKHv0.yml` |
| Skill reference Markdown | uppercase kebab-case | `REWRITE-CONTRACT.md` |

## Serialization rule

- **JSON** stores governed facts, registries, pins, manifests, indexes, findings, receipts, and generated state.
- **YAML** expresses editable configuration, policy, workflow, grammar/profile guidance, and current SAGE schema specifications.
- **Markdown** stores human operating/governance documentation.
- External/provider formats retain their required names and serialization.

## Windows path portability

All shipped SAGE path components are release-gated against Windows filesystem rules in addition to the naming grammar above. Current rules reject:

- reserved DOS/Windows device basenames such as `CON`, `PRN`, `AUX`, `NUL`, `COM1`-`COM9`, and `LPT1`-`LPT9`;
- `< > : " \ | ? *`, control characters, and trailing spaces/dots in path components;
- case-insensitive path collisions;
- path components longer than 255 characters; and
- SAGE-owned relative paths longer than the current 180-character portability budget.

Paratext Project IDs are checked against the same reserved-name/trailing-dot rules before SAGE uses them in Job, report, rights, or publication paths. External Project roots may contain spaces and are handled as native `Path` values rather than shell-concatenated strings.

## Governed exceptions

Do not rename files whose name is controlled by another system or by established packaging conventions. Current exceptions include:

- `SKILL.md` and `agents/openai.yaml`;
- Paratext `Settings.xml`, `BookNames.xml`, and bundled `.SFM` resource filenames;
- `README.md`, `VERSION`, `.gitattributes`, `.gitignore`, `pyproject.toml`, and dependency text files;
- Project IDs, language tags, USFM book codes, status values, historical source names, and external filenames recorded as provenance.

## Current convergence rules

The naming review migrated these current SAGE-owned files:

| Previous | Canonical |
|---|---|
| `system/config/sage.yml` + `system/config/terminology.yml` | `system/config/sage-standard.json` |
| `system/config/skills.yml` | `system/config/skills.json` |
| `system/config/qualification-baselines.yml` | `system/config/qualification-baselines.json` |
| `system/resources/rwc/authority/SOURCES.yml` | `system/resources/rwc/authority/sources.json` |
| `system/config/bic-protected-rewrite-contract.yml` | `system/config/bic-protected-rewrite-pin.json` |
| `system/config/bic-protected-verb-selection-contract.yml` | `system/config/bic-protected-verb-selection-pin.json` |
| `system/config/contracts/BIC-VERB-SELECTION-POLICY.yml` | `system/config/contracts/bic-verb-selection-policy.yml` |
| generated `run.yml` | generated `run.json` |
| `docs/PROJECT-CATALOGUE-AND-MAINTENANCE.md` | `docs/advanced/projects-and-resources/PROJECT-CATALOG-AND-MAINTENANCE.md` |
| `system/tools/CLONE_AND_INSTALL_README.md` | `system/tools/CLONE-AND-INSTALL.md` |

`run.json` is the canonical Run manifest for new current-development workspaces. Pre-release state is not promised compatible across package revisions, so the source package does not retain a dual-write `run.yml` path.

## Composite ITEM and finding identifiers

SAGE distinguishes a provider-local finding handle from the stable SAGE-owned ITEM code.
The LLM should return a short task-local `finding_id` such as `F001`. SAGE preserves that
value as `submitted_id` and assigns the globally stable ITEM/finding identifier after the
result has passed the task boundary.

Composite SAGE identifiers use the same hierarchy rule as the system grammar:

- `_` separates hierarchy levels;
- `-` separates words or compact fields inside one hierarchy level;
- a workflow prefix appears once only; and
- SAGE, not the LLM, owns the global identifier.

Example:

| Layer | Value |
|---|---|
| Workflow | `RTC` |
| Canonical Job/Run key | `RTC-faPCBv3_20260902-001` |
| Compact unit/stage key | `RTC-PH-99846F75` |
| Item sequence | `0001` |
| Canonical ITEM code | `RTC-faPCBv3_20260902-001_RTC-PH-99846F75_0001` |
| LLM-local handle retained as | `submitted_id: F001` |

Do not repeat `RTC` or `STC` in adjacent identifier segments. Run and unit identifiers may already contain the
workflow token for their own namespace; the ITEM assembler removes that redundant top-level
prefix before composing the final global code.

## RTC/STC report identity

Operator-facing RTC/STC filenames include the operation ID before the artifact type so RTC and STC
outputs are immediately distinguishable:

| Operation | Example |
|---|---|
| RTC | `JUD_001_RTC_ACTION-REPORT.md` |
| STC | `JUD_001_STC_ACTION-REPORT.md` |

The matching Operator Note uses the same operation segment. Report composition and naming are
deterministic Python operations; the model does not choose a report folder or filename.
