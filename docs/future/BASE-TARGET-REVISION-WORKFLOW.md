# Existing-target revision workflow (future work)

Status: **PARKED / NOT IMPLEMENTED**.

A workflow that analyses and improves an already existing target translation must be developed separately from BIC.

BIC is fixed as:

```text
SOURCE + DONOR -> TARGET
```

Its TARGET is a generated destination, not input evidence. Therefore any future `BASE_TARGET`-style workflow must define its own authority model, review gates, write rules, and distinction between the existing target, external references, and original-language evidence. It must not be introduced by reusing BIC's DONOR role or by allowing BIC INSPECT/REWRITE to read existing TARGET Scripture.
