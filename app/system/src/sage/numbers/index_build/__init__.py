"""Deterministic in-repo rebuild of the NCA original-language number index.

The 2026-09-09 reference package came from an external handover: its builder is not in
the repository, its source editions are unresolved, and 103 verse overrides carry no
token record. This package rebuilds the original-language side from MACULA Hebrew and
MACULA Greek (CC BY 4.0, Biblica, Inc.) word data:

- ``macula``   reads the pinned MACULA word tables into verse token lists;
- ``lexicon``  classifies one word as a numeral (value, kind, role) per language;
- ``compose``  joins numeral words into the values the shared counting convention
               (skills/nca-numbers/references/COUNTING-CONVENTION.md) defines;
- ``build``    produces typed per-value records, verse rollups, and the regression
               diff against the current package for human review.

Every output value is addressable by MACULA word IDs, so a finding can cite the exact
original-language words behind it.
"""
