# faTMNv4 analysed against usNIVv2

- Tool: `SAW`
- Job: `SAW_faTMNv4-usNIVv2`
- Status: `ACTIVE`

## Bound resources

- WIP — one bound resource: `faTMNv4`
- REFERENCE — one bound resource: `usNIVv2`
- Configured Greek resource: `NOT_CONFIGURED`
- Configured Hebrew resource: `NOT_CONFIGURED`
- Selected WIP grammar profile: `pes/wip`

## Directory use

- `runs/`: bounded operator Runs and immutable governed tasks.
- `reports/` and `exports/`: Job-level human outputs.
- `.sage/`: controller-owned state; do not edit manually.
- BIC `memory/` and `generations/` belong only to that BIC Job; SAW has no generation-handoff state.
