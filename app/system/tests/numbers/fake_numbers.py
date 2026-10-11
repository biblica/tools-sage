"""Build extraction-contract 3.0 ``numbers`` lists for test fakes."""
from __future__ import annotations


def nums(values, text, kinds=None):
    """One number object per value; each cites the whole work-unit text as its exact text."""
    kinds = list(kinds) if kinds is not None else ["CARDINAL"] * len(values)
    return [{"text": text or "x", "value": value, "kind": kind, "counts": "", "counts_en": ""}
            for value, kind in zip(values, kinds)]
