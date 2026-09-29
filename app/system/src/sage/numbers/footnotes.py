"""Noteworthy text-critical info: a local, deterministic, non-blocking advisory.

Per the 2026-09-28 simplified-check rewrite (Task 4): "noteworthy" means the
reference package has *registered* textual-critical guidance for this exact
coordinate -- a known, curated manuscript/scholarship concern about its
number(s) -- not a model judgment call. This never affects the numeric
PASS/FAIL/NEEDS_REVIEW comparison in numbers/compare.py; it is a separate,
always-computed, informational note surfaced alongside it.
"""
from __future__ import annotations

from typing import Mapping

from .models import ReferenceBundle
from sage.vrs import VerseRef


def noteworthy_note(ref: VerseRef, *, bundle: ReferenceBundle) -> Mapping[str, object] | None:
    """Return registered textual-critical guidance for one coordinate, or None.

    Purely a lookup against already-loaded, already-curated package data
    (bundle.footnote_guidance) -- no model call, no blocking of the numeric
    result this coordinate's group otherwise reports.
    """
    record = bundle.footnote_guidance.get(ref)
    if record is None:
        return None
    return {
        "western_reference": ref.label(),
        "classification": str(record.get("CLASS", "")),
        "scholarship_status": str(record.get("SCHOLARSHIP_STATUS", "")),
        "manuscript_evidence": str(record.get("MANUSCRIPT_EVIDENCE", "")),
        "scholarship_position": str(record.get("SCHOLARSHIP_POSITION", "")),
        "ol_values": str(record.get("OL_VALUES", "")),
        "alternate_values": str(record.get("ALT_NIV_VALUES", "")),
    }
