# SAGE Menu Localization

SAGE terminal menus are localized independently from Scripture language profiles and Job reporting languages.

## Authority

- **Interface language** is workstation-level Setup state.
- **Job reporting language** is a reporting authority and must not inherit from the interface locale.
- **Scripture language/profile** controls linguistic analysis and must not inherit from either interface or reporting configuration.

The active interface language is stored in `ecosystem.yml`:

```yaml
interface:
  language: en-US
  menu_localization_source: system/config/localization/menu-localization.json
```

Supported interface languages in v0.01beta2 are `en-US`, `en-GB`, `id`, `fr`, `ru`, and `pt-BR`.

## Menu grammar

Functional choices are numbered vertically. Persistent controls are alphabetic and rendered as two footer rows:

```text
  1. ...
  2. ...
  3. ...

┌──────────────────────────────────────────────────────────────────────┐
│  A. Back   B. Main Menu   C. Exit SAGE                               │
│  D. Language   E. Help   F. Status                                   │
└──────────────────────────────────────────────────────────────────────┘
```

`A` is shown only when the current menu has a Back route. `B` through `F` are global semantic controls. `D. Language`, `E. Help`, and `F. Status` act non-destructively and return to the invoking menu. Alphabetic keys are semantic controls; they are not mnemonics derived from English or any localized label.
The footer keys retain two leading spaces inside the single-line box so their indentation matches
the three-column numeric choice field. Major menu headings use double-line boxes; minor headings use
a `> `-prefixed label and unindented, full-width single-line underline. Every presentation block has one blank line
before and after it.

The editable localization source is documented in `system/config/localization/README.md`.

## Release rebuild task

Before every Alpha, Beta, RC, or release source freeze, review the canonical menu text changed since the
previous version and rebuild `system/config/localization/menu-localization.json`:

1. Extract/review current static menu titles, instructions, and option labels plus the governed
   dynamic-menu list used by the localization contract tests.
2. Keep an existing semantic key only when the meaning is unchanged. Deliberately revise or replace
   the entry when meaning changes; do not preserve stale translations behind a familiar key.
3. Supply reviewed nonblank values for `en-US`, `en-GB`, `id`, `fr`, `ru`, and `pt-BR`.
4. Remove obsolete entries only after confirming no classic-menu or TUI lookup still consumes them.
5. Run `python -m pytest system/tests/test_menu_localization.py` against the frozen source. The
   release is blocked by missing, duplicate, blank, or stale changed-menu localization entries.

This rebuild is a release task even when English is the only menu text changed during development.
