# INIT and auto resolution

`./system/bin/sage project init`, `./system/bin/sage workspace validate`, and `./system/bin/sage workspace initialize` use guided remediation for recoverable settings.

## Source and effective configuration

SAGE never rewrites the selected source settings file during INIT. Confirmed changes are stored in:

```text
localdata/.system/config/operator-overrides.yml
```

The sidecar records:

- the selected source-settings path and SHA-256;
- explicit Operator-confirmed overrides;
- the original and resolved value;
- the resolution method and history.

SAGE merges the fresh sidecar over the source settings in memory and validates the complete effective configuration. If the source file changes, the sidecar is stale and cannot be used until the Operator clears or regenerates it.

## Guided settings

INIT may prompt for:

- `ecosystem.configured`;
- enablement of SAGE Projects required by the selected workflow;
- language code/profile and profile variant;
- project scope, canon, expected books, and roles;
- `content_state`;
- base and custom VRS files;
- each non-trivial `auto` resolution.

For each `auto` result SAGE displays the proposed value, evidence source, confidence, and setting path. The Operator may:

1. accept the detected value as an explicit effective override;
2. retain the source value as `auto`;
3. enter another compatible value;
4. cancel INIT.

Every confirmed value is revalidated before INIT continues. An invalid combination restores the previous sidecar. Task-triggered INIT limits required prompts to the projects selected by the exact task; unrelated automatic settings remain reportable but do not interrupt that task.

## Interactive and non-interactive behavior

Interactive terminal use prompts for required input. `--json`, `--no-prompt`, and `project init --non-interactive` do not prompt; they return or record `INPUT_REQUIRED`/`READY_WITH_ACTIONS` details.

A missing or mistyped value is not `BLOCKED`. `BLOCKED` applies only after corrected input is valid and a genuine in-scope configuration, authority, integrity, or resource defect remains.

## Reset and clearing

The sidecar is governed effective configuration, not transient runtime state. Therefore:

```bash
./system/bin/sage workspace reset-state
```

preserves it. Clear it explicitly with:

```bash
./system/bin/sage project init --clear-overrides
```

## Generated records

```text
localdata/.system/config/operator-overrides.yml
localdata/reports/setup/operator-review.json
localdata/reports/setup/PROJECT-INIT-REPORT.md
localdata/reports/initialization/auto-resolution-report.json
localdata/reports/initialization/auto-resolution-report.md
```

See [Guided Input and INIT Remediation](GUIDED-INPUT-AND-INIT-REMEDIATION.md).
