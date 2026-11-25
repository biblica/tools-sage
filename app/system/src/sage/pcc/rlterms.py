"""Terms Run from a pinned reference list (plan P5b-3, D16): the list's concepts located in the Job's SOURCE.

A terms Run no longer discovers wordings. It takes the pinned list's concepts and locates them in the Run's
scope through the same path that built the list (``rlbuild.BuildContext``): original-language occurrences
realized through the SOURCE alignment, or, for a concept without lemma keys, the list's own wordings. The
candidates are fixed: an occurrence belongs to one of the list's senses for its concept (matched by the
sense key the list was built with, whole wording first, then first word) or to none (``UNRESOLVED``, a
wording the list does not have). Senses are never re-chosen.

When the Job's SOURCE is the text the list was built on (same content hash), matched occurrences are
``CONFIRMED``. Otherwise they are ``PROVISIONAL``: the list was re-located in another edition or a changed
text, and the Run says so. Phrases in the Job's ``phrases.txt`` that are not on the list are located too
and listed as the team's own entries (``LOCAL_INPUT``), with senses from their wording.

Output records keep the P4 contracts, so the terms list, glossary import and bundles work unchanged; a
group id is concept + sense (D13), so glossary rules survive scope changes and re-pins.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .contracts import SCHEMA_VERSION
from .ids import expression_id, group_id, occurrence_id
from .rlbuild import BuildContext, Concept, _Rendered, declared_concepts, partition, sense_candidates
from .segment import tokenize

MIN_GROUP_VERSES = 2  # fewer confirmed verses -> INFORMATIONAL (AT16)


@dataclass
class TermsResult:
    """Machine records and the notes a Run reports."""

    expressions: list[dict[str, Any]] = field(default_factory=list)
    occurrences: list[dict[str, Any]] = field(default_factory=list)
    groups: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    notes: list[tuple[str, str, str]] = field(default_factory=list)
    stats: Counter[str] = field(default_factory=Counter)


def _pick(concept_key: str, r: _Rendered, senses: Mapping[str, Mapping[str, Any]]) -> str | None:
    """The list's sense for one occurrence: whole-wording key first, then first-word key; most verses wins."""
    candidates = sense_candidates(concept_key, r)
    half = len(candidates) // 2
    for level in (candidates[:half], candidates[half:]):
        found = [c for c in level if c in senses]
        if found:
            return max(found, key=lambda c: (senses[c]["verses"], c))
    return None


def _relocation_spans(ctx: BuildContext, entry: Mapping[str, Any], scope: set[str]) -> list[tuple[str, int, int]]:
    """Spans of a concept without lemma keys: its listed wordings, located by tokens."""
    from .rlbuild import locate_wording
    wordings = {w["wording"] for s in entry["senses"] for w in s["wordings"]}
    if entry["anchor"]["kind"] == "WORDING":
        wordings.add(entry["anchor"]["value"][0].split("|", 1)[1])
    spans: set[tuple[str, int, int]] = set()
    tokens_in_scope = {u: t for u, t in ctx.alignment.tokens.items() if u in scope}
    for wording in sorted(wordings):
        tokens = tuple(t.norm for t in tokenize(wording, cased=ctx.cased))
        if tokens:
            spans.update(locate_wording(tokens_in_scope, tokens))
    # a span inside a longer span of the same concept is the same occurrence
    kept = [s for s in spans if not any(o != s and o[0] == s[0] and o[1] <= s[1] and s[2] <= o[2] for o in spans)]
    return sorted(kept)


def terms_from_reference_list(
    ctx: BuildContext,
    *,
    scope_units: Iterable[str],
    manifest: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    source_corpus_id: str,
    source_sha256: str,
    phrases: Iterable[tuple[str, Sequence[str], int]] = (),
    language_tag: str = "und",
    scope_label: str = "",
) -> TermsResult:
    """Locate the pinned list's concepts (and the Job's own phrases) in ``scope_units``."""
    scope = set(scope_units)
    same_text = manifest["reference"]["content_sha256"] == source_sha256
    state = "CONFIRMED" if same_text else "PROVISIONAL"
    out = TermsResult()
    rl_label = f"{manifest['rl_id']}@v{manifest['version']}"
    if not same_text:
        out.notes.append(("PCC_RL_OTHER_EDITION",
                          f"Reference list {rl_label} was built on another text than this SOURCE: its concepts were "
                          "located again and every matched occurrence is PROVISIONAL until reviewed.", scope_label))
    listed = set()
    for entry in sorted(entries, key=lambda e: e["concept_key"]):
        if entry["status"] == "DROPPED":
            continue
        listed.add(entry["concept_key"])
        senses = {s["sense_key"]: s for s in entry["senses"] if s["kind"] == "SENSE"}
        if not senses:
            out.stats["entries_without_senses"] += 1
            continue
        kind = entry["anchor"]["kind"]
        if kind == "OL":
            counts, rendered = ctx.realize_concept(Concept("OL", tuple(entry["anchor"]["value"]), entry["label"],
                                                           entry["category"], entry["status"], ()), units=scope)
        else:
            spans = _relocation_spans(ctx, entry, scope)
            counts, rendered = ctx.realize_concept(Concept("WORDING", (f"{language_tag}|{entry['label']}",),
                                                           entry["label"], entry["category"], entry["status"], ()),
                                                   spans, units=scope)
        if not counts["occurrences"]:
            out.stats["concepts_not_in_scope"] += 1
            continue
        out.stats["concepts"] += 1
        out.stats["occurrences"] += counts["occurrences"]
        out.stats["unrealized"] += counts["no_realization"] + counts["function_only"]
        review = "CURATED" if entry["status"] == "ACTIVE" and same_text else "PROVISIONAL"
        rare = {w["wording"].casefold() for s in entry["senses"] if s["kind"] == "OTHER" for w in s["wordings"]}
        _emit(out, entry["concept_key"], entry, senses, rendered, ctx, source_corpus_id, source_sha256,
              state, review, "AUTHORIZED_REFERENCE", [f"RL:{rl_label}"], rare)
    for concept in _local_concepts(ctx, phrases, language_tag, listed, out):
        spans = None
        if concept.kind == "WORDING":
            spans = _relocation_spans(ctx, {"anchor": {"kind": "WORDING", "value": list(concept.anchor)},
                                            "senses": []}, scope)
        _, rendered = ctx.realize_concept(concept, spans, units=scope)
        senses = {s["sense_key"]: s for s in partition(concept.key, rendered, min_verses=1)}
        if not rendered:
            line = concept.sources[0].split(":")[1]
            out.notes.append(("PCC_PHRASE_NOT_IN_SOURCE", f"phrases.txt line {line}: '{concept.label}' does not occur "
                              "in the SOURCE scope; kept on the list with zero occurrences.", f"phrases.txt:{line}"))
            senses = {"": {"sense_key": f"{concept.key}-LOCAL", "label": concept.label, "verses": 0}}
        entry = {"label": concept.label, "anchor": {"kind": concept.kind, "value": list(concept.anchor)},
                 "category": "DECLARED"}
        _emit(out, concept.key, entry, senses, rendered, ctx, source_corpus_id, source_sha256, "PROVISIONAL",
              "PROVISIONAL", "LOCAL_INPUT", [concept.sources[0]])
    out.expressions.sort(key=lambda e: e["expression_id"])
    out.occurrences.sort(key=lambda o: o["occurrence_id"])
    out.groups.sort(key=lambda g: g["group_id"])
    out.unresolved.sort(key=lambda u: u["expression_id"])
    return out


def _local_concepts(ctx: BuildContext, phrases: Iterable[tuple[str, Sequence[str], int]], language_tag: str,
                    listed: set[str], out: TermsResult) -> list[Concept]:
    """The Job's phrases.txt lines that are not already concepts on the list."""
    concepts, _, _ = declared_concepts(ctx, phrases, language_tag)
    found = []
    for concept in concepts:
        if concept.key in listed:
            out.stats["phrases_on_list"] += 1
        else:
            found.append(concept)
    return found


def _emit(out: TermsResult, concept_key: str, entry: Mapping[str, Any], senses: Mapping[str, Mapping[str, Any]],
          rendered: Sequence[_Rendered], ctx: BuildContext, source_id: str, source_sha: str, state: str,
          review: str, origin: str, evidence: list[str], rare: set[str] = frozenset()) -> None:
    """One expression with its senses, occurrences, groups and unresolved summary."""
    eid = expression_id(source_sha, concept_key)
    lemma = entry["label"].split(" ")[0]
    surface = max(senses.values(), key=lambda s: (s["verses"], s["label"]))["label"]
    single = entry["anchor"]["kind"] == "OL" and len(entry["anchor"]["value"]) == 1
    out.expressions.append({
        "schema_version": SCHEMA_VERSION, "expression_id": eid, "source_corpus_id": source_id,
        "source_surface": surface, "normalized_source_form": " ".join(t.norm for t in tokenize(surface, cased=ctx.cased))
        or surface, "origin": origin, "category": "TERM" if single else "FIXED_PHRASE",
        "senses": [{"sense_id": key, "label": sense["label"],
                    "discriminator": f"original-language lemma {lemma} ({entry['category']}; {concept_key})",
                    "review_state": review} for key, sense in sorted(senses.items())],
    })
    by_sense: dict[str, list[dict[str, Any]]] = defaultdict(list)
    reasons: Counter[str] = Counter()
    for r in rendered:
        unit = ctx.by_unit[r.unit]
        sense = _pick(concept_key, r, senses)
        # A wording the list pooled as too rare to be a sense, or one the list never saw.
        why = None if sense else ("RARE_RENDERING" if r.display.casefold() in rare else "NEW_WORDING")
        occ = {
            "schema_version": SCHEMA_VERSION,
            "occurrence_id": occurrence_id(source_sha, unit.canonical_ref, r.start, r.end, eid),
            "expression_id": eid, "source_corpus_id": source_id, "source_corpus_sha256": source_sha,
            "source_unit_id": r.unit, "canonical_ref": unit.canonical_ref, "native_refs": list(unit.native_refs),
            "body_start": r.start, "body_end": r.end, "offset_units": "UNICODE_CODE_POINT",
            "source_text_span": unit.text[r.start:r.end], "sense_id": sense,
            "sense_state": state if sense else "UNRESOLVED",
            "sense_evidence": evidence + [f"ALIGN:{r.method}"] + ([why] if why else []),
        }
        out.occurrences.append(occ)
        if sense:
            by_sense[sense].append(occ)
        else:
            reasons[why] += 1
    for sense, items in sorted(by_sense.items()):
        verses = len({o["source_unit_id"] for o in items})
        out.groups.append({"group_id": group_id(concept_key, sense), "concept_key": concept_key, "expression_id": eid,
                           "sense_id": sense, "confirmed_occurrences": len(items), "confirmed_verses": verses,
                           "state": state if origin == "AUTHORIZED_REFERENCE" else "PROVISIONAL",
                           "status": "ELIGIBLE" if verses >= MIN_GROUP_VERSES else "INFORMATIONAL"})
    if reasons:
        out.unresolved.append({"expression_id": eid, "code": "PC20", "unresolved_occurrences": sum(reasons.values()),
                               "reasons": dict(sorted(reasons.items()))})

