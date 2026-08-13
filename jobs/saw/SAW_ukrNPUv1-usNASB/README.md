# ukrNPUv1 analysed against usNASB

- Tool: `SAW`
- Job: `SAW_ukrNPUv1-usNASB`
- Status: `ACTIVE`

## Bound resources

- WIP — one bound resource: `ukrNPUv1`
- REFERENCE — one bound resource: `usNASB`
- Configured Greek resource: `NOT_CONFIGURED`
- Configured Hebrew resource: `NOT_CONFIGURED`
- Selected WIP grammar profile: `uk/wip`

## Directory use

- `runs/`: bounded operator Runs and immutable governed tasks.
- `reports/` and `exports/`: Job-level human outputs.
- `.sage/`: controller-owned state; do not edit manually.
- BIC `memory/` and `generations/` belong only to that BIC Job; SAW has no generation-handoff state.
