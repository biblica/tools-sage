# Implementation Checklist

## Discovery
- [ ] Locate Translation Brief model
- [ ] Locate existing shipped resource loader
- [ ] Locate OL package/version conventions
- [ ] Locate run/ACT dispatcher
- [ ] Locate report/finding schema
- [ ] Locate project `input/` handling

## Core contracts
- [ ] Add ATT reference mode config
- [ ] Add reference package manifest contract
- [ ] Add lexical record contract
- [ ] Add phrase record contract
- [ ] Add occurrence record contract
- [ ] Add finding contract

## Phase 1 runtime
- [ ] Load static reference package(s)
- [ ] Verify checksum/schema
- [ ] Read local terms.txt
- [ ] Read local phrases.txt
- [ ] Resolve local items against configured SOURCE
- [ ] Build effective monitored set
- [ ] Index TARGET
- [ ] Run lexical consistency analysis
- [ ] Run phrase consistency analysis
- [ ] Reconcile overlapping findings
- [ ] Implement reference-mode logic
- [ ] Write report + machine output

## Safety/scope guards
- [ ] No SQS call path
- [ ] No canonical mutation
- [ ] No OL fallback unless configured as SOURCE
- [ ] No semantic correctness verdict

## Tests
- [ ] Unit tests for config
- [ ] Unit tests for input parser
- [ ] Unit tests for resolver
- [ ] Unit tests for lexical analyzer
- [ ] Unit tests for phrase analyzer
- [ ] Integration tests for all three reference modes
- [ ] Regression test for package immutability
- [ ] Regression test for no-SQS operation
