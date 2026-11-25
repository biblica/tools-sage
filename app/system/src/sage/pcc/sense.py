"""Sense evidence and grouping (plan §5 A3, decisions D2/D3; handover "Sense assignment").

Original-language (MACULA) lemmas are *evidence*, never authority, and only the CC BY 4.0 fields are used
(lemma, Strong's number, gloss). For one SOURCE expression the engine asks which original-language lemma is
present in the verses where the expression occurs, beyond chance:

- a lemma is a candidate when it is in at least ``min_support`` of the expression's verses, in at least
  ``min_cover`` of them, and the expression is in at least ``min_precision`` of the lemma's own verses
  (a function word present everywhere fails this);
- candidates are chosen greedily by coverage (a lemma that explains no verse the chosen ones leave open is redundant); each chosen lemma is one sense (``SENSE-OL-LEMMA``), so
  divergent lemmas split the expression into senses and never share an obligation (AT03, AT11, AT22);
- an occurrence is ``CONFIRMED`` for the one chosen lemma in its verse, and ``UNRESOLVED`` (``PC20``) when
  none or more than one chosen lemma is present, when the lemma is flagged polysemous, or when the verse
  has no original-language data. Unresolved is never collapsed into the majority sense.

With ``unit_lengths`` the lemma must also lie within ``window`` (relative verse position) of the
occurrence, else the occurrence is ``UNRESOLVED`` (``OUT_OF_POSITION``).

A curated expression keeps its curated senses: one curated sense confirms every occurrence, several leave
them unresolved for the team (P5). Verse-level evidence only; word-position alignment is a later step.
"""

from __future__ import annotations

import copy
from collections import Counter, defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .ids import IdRegistry, concept_key, group_id

RULE = "SENSE-OL-LEMMA"
# An occurrence is tied to a lemma only when that lemma sits within this share of the verse of it
# (relative position). Measured against the BSB tables: higher precision, lower coverage (see the plan).
DEFAULT_WINDOW = 0.25


@dataclass(frozen=True)
class OlItem:
    """One original-language word reduced to the evidence fields."""

    key: str       # Strong's number when present, else the lemma
    lemma: str
    strong: str
    gloss: str


@dataclass
class SenseResult:
    """Expressions with senses, occurrences with sense state, and the groups they form."""

    expressions: list[dict[str, Any]]
    occurrences: list[dict[str, Any]]
    groups: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)


def assign_senses(
    expressions: Sequence[Mapping[str, Any]],
    occurrences: Sequence[Mapping[str, Any]],
    ol_by_unit: Mapping[str, Sequence[OlItem]],
    *,
    min_support: int = 2,
    min_cover: float = 0.15,
    min_precision: float = 0.2,
    polysemous: Collection[str] = (),
    unit_lengths: Mapping[str, int] | None = None,
    window: float | None = DEFAULT_WINDOW,
) -> SenseResult:
    """Return copies of the records with sense evidence applied, plus groups and unresolved summaries."""
    exprs = [copy.deepcopy(dict(e)) for e in expressions]
    occs = [copy.deepcopy(dict(o)) for o in occurrences]
    by_expr: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for occ in occs:
        by_expr[occ["expression_id"]].append(occ)
    keys = {unit: {item.key for item in items} for unit, items in ol_by_unit.items()}
    info = {item.key: item for items in ol_by_unit.values() for item in items}
    lemma_units: Counter[str] = Counter()
    for unit_keys in keys.values():
        lemma_units.update(unit_keys)
    ids = IdRegistry()
    result = SenseResult(exprs, occs)
    flagged = frozenset(polysemous)

    for expr in exprs:
        eid = expr["expression_id"]
        mine = by_expr.get(eid, [])
        reasons: Counter[str] = Counter()
        curated = [s for s in expr["senses"] if s["review_state"] == "CURATED"]
        if curated:
            for occ in mine:
                if len(curated) == 1:
                    occ.update(sense_id=curated[0]["sense_id"], sense_state="CONFIRMED",
                               sense_evidence=["CURATED_SINGLE_SENSE"])
                else:
                    occ["sense_evidence"] = ["CURATED_SENSES_NEED_TEAM_DECISION"]
                    reasons["CURATED_SENSES_NEED_TEAM_DECISION"] += 1
            _groups(result, ids, expr, mine, min_support, reasons)
            continue
        units = {o["source_unit_id"] for o in mine if o["source_unit_id"] in keys}
        counts: Counter[str] = Counter()
        for unit in units:
            counts.update(keys[unit])
        chosen: list[str] = []
        remaining = set(units)
        candidates = sorted(
            (k for k, co in counts.items()
             if co >= min_support and co / len(units) >= min_cover and co / lemma_units[k] >= min_precision),
            key=lambda k: (-counts[k], -2 * counts[k] / (len(units) + lemma_units[k]), k),
        )
        for key in candidates:
            covered = {u for u in remaining if key in keys[u]}
            if covered:
                chosen.append(key)
                remaining -= covered
        sense_ids = {k: ids.mint("sense", {"expression": eid, "lemmas": [k]}) for k in chosen}
        if chosen:
            expr["senses"] = [{
                "sense_id": sense_ids[k],
                "label": f"{info[k].lemma}: {info[k].gloss}".strip(": ").strip() or info[k].lemma,
                "discriminator": f"original-language lemma {info[k].lemma}"
                                 + (f" (Strong's {info[k].strong})" if info[k].strong else ""),
                "review_state": "PROVISIONAL",
            } for k in chosen]
        for occ in mine:
            unit = occ["source_unit_id"]
            if unit not in keys:
                occ["sense_evidence"] = ["NO_OL_ALIGNMENT"]
                reasons["NO_OL_ALIGNMENT"] += 1
                continue
            present = [k for k in chosen if k in keys[unit]]
            if window is not None and unit_lengths and len(present) >= 1 and unit_lengths.get(unit):
                middle = (occ["body_start"] + occ["body_end"]) / 2 / unit_lengths[unit]
                size = len(ol_by_unit[unit])
                near = [k for k in present if any(abs((i + 0.5) / size - middle) <= window
                                                  for i, item in enumerate(ol_by_unit[unit]) if item.key == k)]
                if not near:
                    occ["sense_evidence"] = ["OUT_OF_POSITION"]
                    reasons["OUT_OF_POSITION"] += 1
                    continue
                present = near
            if len(present) == 1 and present[0] not in flagged:
                key = present[0]
                occ.update(sense_id=sense_ids[key], sense_state="CONFIRMED",
                           sense_evidence=[f"{RULE}:{info[key].lemma}|{info[key].strong}"])
            else:
                why = ("POLYSEMOUS_LEMMA:" + present[0]) if present and present[0] in flagged else (
                    "AMBIGUOUS_LEMMAS:" + ",".join(present) if present else
                    ("WEAK_ALIGNMENT" if not chosen else "NO_ASSOCIATED_LEMMA"))
                occ["sense_evidence"] = [why]
                reasons[why.split(":")[0]] += 1
        _groups(result, ids, expr, mine, min_support, reasons)
    result.groups.sort(key=lambda g: g["group_id"])
    result.unresolved.sort(key=lambda u: u["expression_id"])
    return result


def _groups(result: SenseResult, ids: IdRegistry, expr: Mapping[str, Any],
            mine: Sequence[Mapping[str, Any]], min_confirmed: int, reasons: Counter[str]) -> None:
    """One group per (expression, sense) with confirmed occurrences; summarize what stayed unresolved."""
    eid = expr["expression_id"]
    by_sense: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for occ in mine:
        if occ["sense_state"] == "CONFIRMED":
            by_sense[occ["sense_id"]].append(occ)
    for sense, items in sorted(by_sense.items()):
        verses = len({o["source_unit_id"] for o in items})
        result.groups.append({
            "group_id": group_id(concept_key("WORDING", f"und|{expr['normalized_source_form']}"), sense),
            "expression_id": eid,
            "sense_id": sense,
            "confirmed_occurrences": len(items),
            "confirmed_verses": verses,
            "status": "ELIGIBLE" if verses >= min_confirmed else "INFORMATIONAL",
        })
    unresolved = sum(1 for o in mine if o["sense_state"] != "CONFIRMED")
    if unresolved:
        result.unresolved.append({
            "expression_id": eid, "code": "PC20", "unresolved_occurrences": unresolved,
            "reasons": dict(sorted(reasons.items())),
        })
