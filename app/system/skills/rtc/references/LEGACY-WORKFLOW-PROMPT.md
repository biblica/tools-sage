<!-- saw-root-sha256: 9dd127a14adc38dc11c47ca339670e2168619016892011e265f535741f75b680 -->
<!-- schema-pack-sha256: a4a6662a1f1530636734edfdf232bfe82a4b81d018aad4004351f5022a0dba08 -->
# RUN RTC

Resolve the operator scope exactly, then run `./saw run RTC --scope "<scope>"` on macOS/Linux or `.\saw.cmd run RTC --scope "<scope>"` on Windows.
SAW performs deterministic full-scope checks, maps TARGET-local coordinates through resource-specific VRS schemas, and creates section-led internal work units.
Use `\ms1`, `\ms2`, `\s1`, and `\s2`; ignore `\s3`; a `\c` marker alone never forces a split; allow chapter-crossing units.
Execute the generated Act, write its governed JSON output, and submit with the exact runtime command.
Continue automatically until deterministic finalization reports completion.
