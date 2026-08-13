# SAGE Jobs

Operational BIC and SAW work is stored as Jobs built from registered Scripture projects.

- `bic/`: `BIC_<SOURCE>-<DONOR>-<TARGET>` Jobs.
- `saw/`: `SAW_<WIP>-<REFERENCE>` Jobs.
- Each Job owns `job.yml`, `runs/`, reports, exports, archive state, and controller-owned `.sage/` state.

Registered Paratext/PTLite projects are not duplicated here; Job manifests bind their canonical project codes.
