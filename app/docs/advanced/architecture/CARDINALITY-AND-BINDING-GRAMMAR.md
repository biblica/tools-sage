# Cardinality and binding grammar

Version: `0.02alpha1`

SAGE separates machine cardinality from Operator-facing binding language. It does not change BIC authority, protected linguistic policy, SAW independence, or bounded TARGET storage semantics.

## Machine cardinality

SAGE schemas use only these terms for cardinality:

- `exactly_one`
- `zero_or_one`
- `one_or_more`
- `zero_or_more`
- `exactly_one_of`

BIC declares `SOURCE=exactly_one`, `DONOR=exactly_one`, and `TARGET=exactly_one`. The TARGET has `exactly_one_of` internal SAGE storage or one mapped Paratext/PTLite project binding.

Greek and Hebrew project bindings are independently `zero_or_one`. They are configured authority bindings, not routine evidence. When a governed operation actually routes original-language evidence, SAGE requires exactly one applicable bound OL resource for the testament/scope and fails closed if it is absent or unusable.

The selected SOURCE/TARGET/WIP grammar contract is `exactly_one_active` for its governed role. Effective versification resolves to `exactly_one` effective VRS for each governed resource/Run context.

## Operator wording

Human-facing output does not expose schema syntax unless explaining the schema itself. Use:

- `one bound SOURCE resource`
- `one bound DONOR resource`
- `one bound TARGET resource`
- `configured Greek resource` / `configured Hebrew resource`
- `selected grammar profile`
- `resolved effective VRS`

Do not describe Greek/Hebrew resources or grammar profiles as `exact`. `Exact` remains valid where it genuinely means byte/hash/coordinate identity, such as exact evidence hashes or exact bounded coordinates.
