# SAGE Menu Localization

`menu-localization.json` is the canonical human-editable localization source for the SAGE terminal interface.

## Supported interface languages

- `en-US` — English (United States), canonical system English
- `en-GB` — English (United Kingdom)
- `id` — Bahasa Indonesia
- `fr` — Français
- `ru` — Русский
- `pt-BR` — Português (Brasil)

## Editing model

The file is UTF-8 JSON with deliberate whitespace for direct editing in a normal text editor.

Each semantic menu concept appears once under `strings`:

```json
{
  "strings": {
    "menu.main.menu": {
      "en-US": "Main menu",
      "en-GB": "Main menu",
      "id": "Menu utama",
      "fr": "Menu principal",
      "ru": "Главное меню",
      "pt-BR": "Menu principal"
    }
  }
}
```

Rules:

1. Keep semantic keys stable.
2. Every entry must contain all six locale values.
3. `en-US` is the canonical source wording used for runtime lookup.
4. Use sentence case for menu headings and items. Render mid-sentence governed entities as
   `PROJECT`, `JOB`, `RUN`, or `TASK`; reserve other uppercase forms for governed protocol tokens.
5. Preserve canonical SAGE identifiers such as `SAGE`, `BIC`, `RTC`, `STC`, `TARGET`, `SOURCE`,
   `DONOR`, `WIP`, `REFERENCE`, `ACT`, `RWC`, `SEMDOM`, `FLEx`, `Combine`, and `Codex` unless system grammar
   changes them. Keep sentence-initial `Project`, `Job`, `Run`, or `Task` natural; the renderer marks
   those governed entities in uppercase only when they occur later in a menu sentence.
6. Preserve meaning, not spacing. Shared UI formatting runs after localization, measures terminal
   display cells, and wraps menu/header/information text to the active viewport. Do not insert tabs
   or manual padding into localized values.

The reduced source contains one semantic entry per canonical phrase; capitalization-only display
variants are renderer style and must not be duplicated as localization entries.

## Menu-key grammar

Visible menu operations use numerals only. Persistent footer controls are language-neutral and fixed:

`A. Back   B. Main menu   C. Exit SAGE   D. Language`

The localized words are display text only. Navigation is never inferred from a localized label.

`D` opens Interface Language from any menu. Interface language is workstation/Setup state and does not determine Job reporting language.
