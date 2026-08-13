# BIC target generations

Target generations are **BIC-local immutable publication history**. They are not a SAW handoff mechanism and are not required for SAW configuration.

After a governed SELF-CHECK commit, an Operator may publish/verify a BIC generation for audit/history:

```sh
./sage generation list [--project PROJECT_ID]
./sage generation publish [--project PROJECT_ID]
./sage generation verify [--project PROJECT_ID] [--selector SELECTOR]
```

There is no automatic generation handoff or TARGET-to-WIP conversion command.

## TARGET storage modes

A BIC TARGET may be internal to SAGE or explicitly mapped to a Paratext/PTLite project folder. `READ_WRITE_TARGET` permits direct writes only to the designated TARGET `.SFM` files after deterministic SELF-CHECK validation. `.VRS` and all other external file types remain non-writable.
