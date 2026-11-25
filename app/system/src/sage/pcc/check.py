"""PCC Function B, forward check (plan §6, P6-1..P6-7): is each SOURCE concept rendered consistently in the WIP?

Inputs are the terms analysis of the Run's scope (expressions, occurrences, groups: from the pinned reference
list or, without one, from discovery), the Job's glossary rules and language facts, and the SOURCE and WIP texts.

1. **Pair verses** (P6-1) through both versifications: units that share a canonical verse form one pair; a
   bridge or split joins several units into an ``EQUIVALENCE_GROUP``. A SOURCE occurrence whose verse has no
   WIP counterpart is ``PC21`` (``NO_TARGET_VERSE``).
2. **Groups** (P6-2): concept + sense groups with at least two confirmed verses are compared; fewer is
   ``INFORMATIONAL`` (AT16); unresolved senses are ``PC20`` (AT11). Concepts the list only proposes are not
   traced (D17).
3. **Locate the TARGET** (B2, P6-3/P6-4) per occurrence, in this order: a glossary form of the group (any
   state; only ``APPROVED`` ``ACCEPT`` rules accept) matched exactly, through a learned inflection or a
   team-declared spelling equivalence; else the span the SOURCE <-> WIP word alignment gives the occurrence
   (IBM Model 1 both ways, the P5b-0 engine). A span both directions agree on is reliable. No span in a
   verse that otherwise aligns well is a possible omission; anything else is uncertain (``PC21``, AT12).
4. **Classify** each group in the handover's order: ``PC23`` (equal-scope ACCEPT and REJECT of one form),
   ``PC21``, ``PC00`` / ``PC01`` (approved renderings, exact or variant), ``PC13`` (negation differs, only
   with declared negation markers), ``PC11``, ``PC10`` (differing unapproved forms; ``ORTHOGRAPHIC`` at
   low severity when they differ only in spelling), ``PC02`` (uniform but unapproved, or senses only
   provisional). Every ``PC10`` / ``PC11`` carries the rendering distribution.
5. **Self-qualify** (L4, P6-6): plant substitutions and removals into copies of the WIP's own verses and
   measure how many the matcher finds. A kind at or above ``QUALIFY_BAR`` (with enough cases) is
   ``CHECKED``; otherwise it is ``BEST_EFFORT`` (PO 2026-11-25): its findings are still reported, each labelled
   with the measured recall (or "not measured"), and the Operator tunes the result through the reference
   list and glossary import/export. Nothing below the bar is ever counted as a pass.

Every eligible occurrence gets exactly one audit row. Nothing is normalized away unless the team declared
it; no language code is consulted (D11). Deterministic for the same inputs.
"""

from __future__ import annotations

import random
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..references import parse_scope
from ..vrs import VerseRef, VersificationSchema
from .align import DirectModel, OlToken, _NULL, _prior, train_direct
from .contracts import SCHEMA_VERSION
from .discovery import SourceUnit
from .ids import full_digest, make_id
from .segment import Token, tokenize
from .traits import MIN_STEM, WipTraits

MIN_GROUP_VERSES = 2
SPAN_MIN_POSTERIOR = 0.3      # a target token belongs to the occurrence from this posterior
RELIABLE_POSTERIOR = 0.5      # an agreed link at least this strong makes the span reliable
LINK_MIN_PROB = 0.05          # an agreed link counts only when t(WIP token | SOURCE token) reaches this
CONTEXT_WINDOW = 5            # SOURCE tokens either side of an occurrence that form its context
CONTEXT_MIN = 3               # fewer context words: judge the whole verse
VERSE_ALIGNED_SHARE = 0.4     # share of SOURCE content tokens with agreed links for a verse to count as aligned
STOP_SHARE = 0.15             # WIP tokens in this share of verses are function-like (never a span edge)
CHECK_LAMBDA = 4.0           # relative-position prior for SOURCE <-> WIP spans (softer than OL: languages reorder)
QUALIFY_BAR = 0.8             # minimum measured recall per kind (plan L4)
QUALIFY_MIN_TRIALS = 20       # fewer planted cases than this: too little text to measure -> BEST_EFFORT
QUALIFY_SAMPLES = 60          # planted errors per kind
KINDS = ("SUBSTITUTION", "REMOVAL")
SEVERITY = {"PC10": "MEDIUM", "PC11": "MEDIUM", "PC12": "LOW", "PC13": "HIGH", "PC20": "LOW", "PC21": "LOW",
            "PC23": "HIGH"}
KEY_CATEGORIES = frozenset({"BE", "AT", "RI", "KEY_TERM", "DECLARED"})


# --- texts and verse pairing ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pair:
    """SOURCE and WIP units that cover the same canonical verses."""

    pair_id: str
    source: tuple[str, ...]
    target: tuple[str, ...]
    kind: str                     # ONE_TO_ONE | EQUIVALENCE_GROUP


def _canonical(unit: SourceUnit, schema: VersificationSchema) -> set[tuple[str, int, int]]:
    """Canonical verses of one unit."""
    found = set()
    for label in unit.native_refs:
        book, _, cv = label.partition(" ")
        chapter, _, verse = cv.partition(":")
        for ref in schema.local_to_canonical(VerseRef(book, int(chapter), int(verse))):
            found.add((ref.book, ref.chapter, ref.verse))
    return found


def pair_verses(source: Sequence[SourceUnit], target: Sequence[SourceUnit], source_schema: VersificationSchema,
                target_schema: VersificationSchema) -> tuple[list[Pair], dict[str, str]]:
    """Pairs (units joined through shared canonical verses) and a unit -> pair map for both sides."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        """Union-find root."""
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner: dict[tuple[str, int, int], str] = {}
    for prefix, units, schema in (("S:", source, source_schema), ("T:", target, target_schema)):
        for unit in units:
            node = prefix + unit.unit_id
            find(node)
            for verse in _canonical(unit, schema):
                if verse in owner:
                    parent[find(node)] = find(owner[verse])
                else:
                    owner[verse] = node
    members: dict[str, list[str]] = defaultdict(list)
    for node in parent:
        members[find(node)].append(node)
    order = {("S:" + u.unit_id): i for i, u in enumerate(source)} | {("T:" + u.unit_id): i for i, u in enumerate(target)}
    pairs, unit_pair = [], {}
    for nodes in sorted(members.values(), key=lambda ns: min(order[n] for n in ns)):
        s = tuple(n[2:] for n in sorted(nodes, key=order.get) if n.startswith("S:"))
        t = tuple(n[2:] for n in sorted(nodes, key=order.get) if n.startswith("T:"))
        if not s or not t:
            continue
        pair = Pair(f"P{len(pairs):06d}", s, t, "ONE_TO_ONE" if len(s) == len(t) == 1 else "EQUIVALENCE_GROUP")
        pairs.append(pair)
        for unit in s:
            unit_pair["S:" + unit] = pair.pair_id
        for unit in t:
            unit_pair["T:" + unit] = pair.pair_id
    return pairs, unit_pair


@dataclass
class Side:
    """Tokens of one side of every pair, with each token's unit and offsets."""

    tokens: dict[str, list[Token]] = field(default_factory=dict)      # pair -> tokens (offsets index their unit)
    units: dict[str, list[str]] = field(default_factory=dict)         # pair -> unit id per token


def side_tokens(pairs: Sequence[Pair], units: Mapping[str, SourceUnit], which: str, *, cased: bool,
                letter_marks: Iterable[str] = (), unspaced: bool = False) -> Side:
    """Tokenize one side of every pair (units in order)."""
    side = Side()
    marks = tuple(letter_marks)
    for pair in pairs:
        tokens, owners = [], []
        for unit_id in (pair.source if which == "source" else pair.target):
            items = tokenize(units[unit_id].text, cased=cased, letter_marks=marks, unspaced=unspaced)
            tokens += items
            owners += [unit_id] * len(items)
        side.tokens[pair.pair_id], side.units[pair.pair_id] = tokens, owners
    return side


def train_pair_model(pairs: Sequence[Pair], source: Side, target: Side) -> DirectModel:
    """Model 1 both ways over every pair: t(WIP token | SOURCE token) and back (the P5b-0 engine)."""
    e = {p.pair_id: target.tokens[p.pair_id] for p in pairs}
    f = {p.pair_id: [OlToken(str(i), t.norm) for i, t in enumerate(source.tokens[p.pair_id])] for p in pairs}
    return train_direct(e, f)


def stop_forms(side: Side) -> frozenset[str]:
    """Token forms present in a large share of pairs (function-like), measured from the text."""
    counts: Counter[str] = Counter()
    for tokens in side.tokens.values():
        counts.update({t.norm for t in tokens})
    total = max(len(side.tokens), 1)
    return frozenset(form for form, n in counts.items() if n / total >= STOP_SHARE and n >= 20)


# --- TARGET forms -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Morphology:
    """What the WIP's own text and the team say about word forms (plan §7 L1-L3)."""

    suffixes: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    equivalences: Mapping[str, str] = field(default_factory=dict)   # declared spelling variant -> preferred
    negation: tuple[str, ...] = ()

    @classmethod
    def from_traits(cls, traits: WipTraits, facts: Mapping[str, Any] | None = None) -> "Morphology":
        """Learned affixes plus the team's declared facts (``glossary`` language facts)."""
        facts = facts or {}
        pairs = {}
        for item in str(facts.get("spelling_equivalences") or "").split(";"):
            a, sep, b = item.partition("=")
            if sep and a.strip() and b.strip():
                pairs[nfc_fold(a)] = nfc_fold(b)
        negation = tuple(sorted({nfc_fold(x) for x in str(facts.get("negation_markers") or "").split(";") if x.strip()}))
        return cls(tuple(a.form for a in traits.suffixes), tuple(a.form for a in traits.prefixes), pairs, negation)

    def spell(self, form: str) -> str:
        """A token with declared spelling equivalences applied."""
        return self.equivalences.get(form, form)

    def stem(self, form: str) -> str:
        """Strip learned prefixes and suffixes (longest first, to a fixpoint, never below MIN_STEM)."""
        changed = True
        while changed:
            changed = False
            for suffix in sorted(self.suffixes, key=lambda x: (-len(x), x)):
                if form.endswith(suffix) and len(form) - len(suffix) >= MIN_STEM:
                    form, changed = form[:-len(suffix)], True
                    break
            for prefix in sorted(self.prefixes, key=lambda x: (-len(x), x)):
                if form.startswith(prefix) and len(form) - len(prefix) >= MIN_STEM:
                    form, changed = form[len(prefix):], True
                    break
        return form


def nfc_fold(text: str) -> str:
    """NFC + casefold, whitespace folded (comparison only; diacritics are kept)."""
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def _edit1(a: str, b: str) -> bool:
    """True when two strings differ by exactly one edit."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def find_form(form: Sequence[str], tokens: Sequence[Token], morph: Morphology) -> tuple[int, int, str] | None:
    """First place ``form`` (comparison tokens) occurs in ``tokens``: (first, last, EXACT|SPELLING|INFLECTION)."""
    n = len(form)
    norms = [t.norm for t in tokens]
    for kind, view in (("EXACT", lambda x: x), ("SPELLING", morph.spell),
                       ("INFLECTION", lambda x: morph.stem(morph.spell(x)))):
        wanted = [view(x) for x in form]
        for i in range(len(norms) - n + 1):
            if [view(x) for x in norms[i:i + n]] == wanted:
                return i, i + n - 1, kind
    return None


def form_class(form: str, morph: Morphology) -> str:
    """Comparison class of a rendering: declared spellings applied, learned inflection removed."""
    return " ".join(morph.stem(morph.spell(t)) for t in form.split())


# --- per-occurrence evidence --------------------------------------------------------------------------------


@dataclass
class Evidence:
    """What was found in the WIP for one SOURCE occurrence."""

    occurrence_id: str
    group_id: str
    ref: str
    status: str                  # ACCEPTED | REJECTED | FORM | OMISSION | UNCERTAIN | NO_TARGET_VERSE
    form: str = ""               # TARGET wording as written
    form_key: str = ""           # comparison class
    variant: str = ""            # EXACT | SPELLING | INFLECTION | LEARNED
    rule_id: str = ""
    target_ref: str = ""
    confidence: float = 0.0
    negated: bool = False
    reason: str = ""


def learned_span(model: DirectModel, src: Sequence[Token], tgt: Sequence[Token], occ: set[int],
                 stops: frozenset[str], source_stops: frozenset[str], lam: float = CHECK_LAMBDA
                 ) -> tuple[list[int], bool, float, bool]:
    """Target tokens of the occurrence, whether reliable, their mean posterior, and whether the verse aligns."""
    if not src or not tgt:
        return [], False, 0.0, False
    ns, nt = len(src), len(tgt)
    best_src: list[tuple[int, float]] = []
    for i, e in enumerate(tgt):
        scores = [model.e_given_f.get((e.norm, f.norm), 0.0) * _prior(i, nt, j, ns, lam) for j, f in enumerate(src)]
        z = sum(scores) + model.e_given_f.get((e.norm, _NULL), 0.0) * 0.5
        j = max(range(ns), key=scores.__getitem__)
        best_src.append((j, scores[j] / z if z else 0.0))
    best_tgt: list[tuple[int, float]] = []
    for j, f in enumerate(src):
        scores = [model.f_given_e.get((f.norm, e.norm), 0.0) * _prior(i, nt, j, ns, lam) for i, e in enumerate(tgt)]
        z = sum(scores) + model.f_given_e.get((f.norm, _NULL), 0.0) * 0.5
        i = max(range(nt), key=scores.__getitem__)
        best_tgt.append((i, scores[i] / z if z else 0.0))
    agreed = {(j, i) for i, (j, p) in enumerate(best_src) if best_tgt[j][0] == i
              and model.e_given_f.get((tgt[i].norm, src[j].norm), 0.0) >= LINK_MIN_PROB}
    # Context: the SOURCE content words around the occurrence (the whole verse when it has too few). An
    # omission is only claimed where the words around it are rendered and linked both ways.
    content = [j for j, f in enumerate(src) if f.norm not in source_stops and j not in occ]
    if occ:
        near = [j for j in content if min(abs(j - k) for k in occ) <= CONTEXT_WINDOW]
        content = near if len(near) >= CONTEXT_MIN else content
    # a context word counts as rendered when either direction links it with real probability
    linked = {j for i, (j, _) in enumerate(best_src) if model.e_given_f.get((tgt[i].norm, src[j].norm), 0.0) >= LINK_MIN_PROB}
    linked |= {j for j, (i, _) in enumerate(best_tgt) if model.e_given_f.get((tgt[i].norm, src[j].norm), 0.0) >= LINK_MIN_PROB}
    aligned = bool(content) and sum(1 for j in content if j in linked) / len(content) >= VERSE_ALIGNED_SHARE
    def forward(i: int) -> bool:
        """The token's best SOURCE word is in the occurrence and t(token | word) is a real probability."""
        j, p = best_src[i]
        return j in occ and p >= SPAN_MIN_POSTERIOR and model.e_given_f.get((tgt[i].norm, src[j].norm), 0.0) >= LINK_MIN_PROB

    def backward(i: int) -> bool:
        """An occurrence word's best TARGET token is this one and t(word | token) is a real probability."""
        return any(best_tgt[j][0] == i and best_tgt[j][1] >= SPAN_MIN_POSTERIOR
                   and model.f_given_e.get((src[j].norm, tgt[i].norm), 0.0) >= LINK_MIN_PROB for j in occ)

    def supported(i: int) -> bool:
        """Linked to the occurrence in either direction with real (not only relative) probability."""
        return forward(i) or backward(i)

    # a span needs at least one token whose own best SOURCE word is the occurrence; backward links only extend it
    picked = {i for i in range(nt) if supported(i)} if any(forward(i) for i in range(nt)) else set()
    picked = {i for i in picked if tgt[i].norm not in stops} or picked
    if not picked:
        return [], False, 0.0, aligned
    # keep the contiguous run (gaps of one token bridged) holding the strongest token
    strongest = max(picked, key=lambda i: (best_src[i][1] if best_src[i][0] in occ else 0.0, -i))
    run = {strongest}
    for step in (-1, 1):
        i = strongest
        while True:
            nxt = next((k for k in (i + step, i + 2 * step) if k in picked), None)
            if nxt is None:
                break
            run.update(range(min(i, nxt), max(i, nxt) + 1))
            i = nxt
    span = sorted(run)
    while len(span) > 1 and (tgt[span[0]].norm in stops or not supported(span[0])):
        span.pop(0)
    while len(span) > 1 and (tgt[span[-1]].norm in stops or not supported(span[-1])):
        span.pop()
    reliable = any((j, i) in agreed and best_src[i][1] >= RELIABLE_POSTERIOR for i in span for j in occ)
    mean = sum(best_src[i][1] for i in span) / len(span)
    return span, reliable, round(mean, 4), aligned


# --- the check ---------------------------------------------------------------------------------------------


@dataclass
class CheckResult:
    """Findings, audit rows, per-group outcomes, qualification and summary counts."""

    findings: list[dict[str, Any]] = field(default_factory=list)
    audit: list[dict[str, Any]] = field(default_factory=list)
    outcomes: dict[str, str] = field(default_factory=dict)          # group -> code
    evidence: dict[str, list[Evidence]] = field(default_factory=dict)
    qualification: dict[str, dict[str, Any]] = field(default_factory=dict)
    best_effort: list[str] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)


@dataclass
class CheckInput:
    """Everything one check needs, prepared by the Run (or a test)."""

    run_id: str
    run_input_sha256: str
    source_units: Mapping[str, SourceUnit]
    target_units: Mapping[str, SourceUnit]
    pairs: Sequence[Pair]
    unit_pair: Mapping[str, str]
    source_side: Side
    target_side: Side
    model: DirectModel
    morph: Morphology
    expressions: Sequence[Mapping[str, Any]]
    occurrences: Sequence[Mapping[str, Any]]
    groups: Sequence[Mapping[str, Any]]
    rules: Mapping[str, Mapping[str, Any]]
    target_stops: frozenset[str] = frozenset()
    source_stops: frozenset[str] = frozenset()


def _source_token_span(side: Side, pair_id: str, unit: str, start: int, end: int) -> set[int]:
    """Indices of the pair's SOURCE tokens inside an occurrence's code-point span."""
    return {i for i, (t, u) in enumerate(zip(side.tokens[pair_id], side.units[pair_id]))
            if u == unit and t.start < end and t.end > start}


def _rules_for(rules: Mapping[str, Mapping[str, Any]], group: str, ref: str) -> list[Mapping[str, Any]]:
    """Rules of one group that apply at ``ref`` (group scope, or a passage holding ``ref``)."""
    book, _, cv = ref.partition(" ")
    chapter, _, verse = cv.partition(":")
    found = []
    for rule in rules.values():
        if rule["group_id"] != group:
            continue
        scope = rule["scope"]
        if scope["level"] == "PASSAGE":
            try:
                if not parse_scope(scope["identifier"]).contains(VerseRef(book, int(chapter), int(verse))):
                    continue
            except Exception:  # noqa: BLE001 - an unreadable passage never applies
                continue
        found.append(rule)
    return found


def locate(inp: CheckInput, occ: Mapping[str, Any], group: str) -> Evidence:
    """B2: glossary forms first, then the learned span; never a guess."""
    ref = occ["canonical_ref"]
    pair_id = inp.unit_pair.get("S:" + occ["source_unit_id"])
    if pair_id is None:
        return Evidence(occ["occurrence_id"], group, ref, "NO_TARGET_VERSE", reason="NO_TARGET_VERSE")
    tgt = inp.target_side.tokens[pair_id]
    owners = inp.target_side.units[pair_id]
    rules = sorted(_rules_for(inp.rules, group, ref), key=lambda r: (r["state"] != "APPROVED", -len(r["normalized_target_form"]), r["rule_id"]))
    for rule in rules:
        form = [nfc_fold(t) for t in rule["normalized_target_form"].split()]
        hit = find_form(form, tgt, inp.morph)
        if hit is None:
            continue
        first, last, kind = hit
        unit = inp.target_units[owners[first]]
        text = unit.text[tgt[first].start:tgt[last].end] if owners[first] == owners[last] else " ".join(t.text for t in tgt[first:last + 1])
        approved = rule["state"] == "APPROVED"
        status = ("ACCEPTED" if rule["effect"] == "ACCEPT" else "REJECTED") if approved else "FORM"
        return Evidence(occ["occurrence_id"], group, ref, status, text, form_class(" ".join(t.norm for t in tgt[first:last + 1]), inp.morph),
                        kind, rule["rule_id"], unit.canonical_ref, 0.95, _negated(tgt, first, last, inp.morph),
                        f"glossary form ({rule['state'].lower()})")
    src = inp.source_side.tokens[pair_id]
    span_src = _source_token_span(inp.source_side, pair_id, occ["source_unit_id"], occ["body_start"], occ["body_end"])
    span, reliable, mean, aligned = learned_span(inp.model, src, tgt, span_src, inp.target_stops, inp.source_stops)
    target_ref = inp.target_units[owners[0]].canonical_ref if owners else ref
    if span and reliable:
        first, last = span[0], span[-1]
        unit = inp.target_units[owners[first]]
        text = unit.text[tgt[first].start:tgt[last].end] if owners[first] == owners[last] else " ".join(t.text for t in tgt[first:last + 1])
        norm = " ".join(t.norm for t in tgt[first:last + 1])
        return Evidence(occ["occurrence_id"], group, ref, "FORM", text, form_class(norm, inp.morph), "LEARNED", "",
                        unit.canonical_ref, mean, _negated(tgt, first, last, inp.morph), "learned alignment")
    if not span and aligned:
        return Evidence(occ["occurrence_id"], group, ref, "OMISSION", target_ref=target_ref,
                        reason="the verse aligns but nothing in it renders this SOURCE wording")
    return Evidence(occ["occurrence_id"], group, ref, "UNCERTAIN", target_ref=target_ref, confidence=mean,
                    reason="alignment too weak to locate the rendering")


def _negated(tokens: Sequence[Token], first: int, last: int, morph: Morphology) -> bool:
    """A declared negation marker inside the span or right next to it."""
    if not morph.negation:
        return False
    window = tokens[max(0, first - 1):last + 2]
    return any(t.norm in morph.negation or any(t.norm.startswith(m) and len(t.norm) > len(m) + 1 for m in morph.negation)
               for t in window)


def _distribution(items: Sequence[Evidence]) -> list[str]:
    """'form (n): refs' lines, most frequent first."""
    forms: dict[str, list[Evidence]] = defaultdict(list)
    for ev in items:
        forms[ev.form or f"[{ev.status.lower()}]"].append(ev)
    return [f"{form} ({len(evs)}): {', '.join(sorted({e.ref for e in evs}))}"
            for form, evs in sorted(forms.items(), key=lambda kv: (-len(kv[1]), kv[0]))]


def classify(evs: Sequence[Evidence], *, confirmed: bool, conflict: bool, morph: Morphology) -> tuple[str, dict[str, str]]:
    """Group code and per-occurrence codes, in the handover's decision order (doc 02)."""
    per: dict[str, str] = {}
    if conflict:
        return "PC23", {e.occurrence_id: "PC23" for e in evs}
    uncertain = [e for e in evs if e.status in ("UNCERTAIN", "NO_TARGET_VERSE")]
    rest = [e for e in evs if e not in uncertain]
    for e in uncertain:
        per[e.occurrence_id] = "PC21"
    # A declared negation marker present in some renderings only is a feature shift even when every form is
    # approved (protected feature, doc 14): it is checked before an all-approved group can pass.
    if morph.negation:
        neg = [e for e in rest if e.status in ("ACCEPTED", "FORM") and e.negated]
        pos = [e for e in rest if e.status in ("ACCEPTED", "FORM") and not e.negated]
        if neg and pos:
            minority = neg if len(neg) <= len(pos) else pos
            per.update({e.occurrence_id: "PC13" for e in minority})
            rest = [e for e in rest if e not in minority]
    accepted = [e for e in rest if e.status == "ACCEPTED"]
    if rest and len(accepted) == len(rest) and not any(c == "PC13" for c in per.values()):
        code = "PC00" if confirmed and all(e.variant == "EXACT" for e in accepted) and len({e.form_key for e in accepted}) == 1 else "PC01"
        if not confirmed:
            code = "PC02"
        per.update({e.occurrence_id: code for e in accepted})
        return ("PC21" if uncertain else code), per
    omissions = [e for e in rest if e.status == "OMISSION"]
    per.update({e.occurrence_id: "PC11" for e in omissions})
    rendered = [e for e in rest if e.status in ("ACCEPTED", "FORM", "REJECTED")]
    classes = {e.form_key for e in rendered if e.status != "REJECTED"}
    rejected = [e for e in rendered if e.status == "REJECTED"]
    if rejected or len(classes) > 1 or (accepted and any(e.status == "FORM" for e in rendered)):
        for e in rendered:
            per[e.occurrence_id] = "PC10" if e.status != "ACCEPTED" else "PC01"
        group = "PC10"
    elif rendered:
        for e in rendered:
            per[e.occurrence_id] = "PC02" if e.status != "ACCEPTED" else ("PC00" if confirmed else "PC02")
        group = "PC02"
    else:
        group = "PC11" if omissions else "PC21"
    if any(c == "PC13" for c in per.values()):
        group = "PC13"
    elif omissions and group in ("PC02",):
        group = "PC11"
    return group, per


def orthographic_only(evs: Sequence[Evidence]) -> bool:
    """All differing forms are one edit apart (or declared equivalents) from the most frequent one."""
    keys = Counter(e.form_key for e in evs if e.form_key)
    if len(keys) < 2:
        return False
    main = keys.most_common(1)[0][0]
    return all(k == main or _edit1(k, main) for k in keys)


def run_check(inp: CheckInput, *, qualify: bool = True, seed: int = 0) -> CheckResult:
    """Classify every eligible group of the scope; findings, audit and qualification."""
    result = CheckResult()
    by_group: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    occ_by_id = {o["occurrence_id"]: o for o in inp.occurrences}
    group_of = {(g["expression_id"], g["sense_id"]): g for g in inp.groups}
    exprs = {e["expression_id"]: e for e in inp.expressions}
    unresolved = []
    for occ in inp.occurrences:
        group = group_of.get((occ["expression_id"], occ["sense_id"]))
        if group is None:
            if occ["sense_state"] == "UNRESOLVED" or not occ["sense_id"]:
                unresolved.append(occ)
            continue
        if group.get("entry_status") == "PROPOSED":
            result.counts["not_traced_proposed"] += 1
            continue
        by_group[group["group_id"]].append(occ)
    groups = {g["group_id"]: g for g in inp.groups}
    for gid in sorted(by_group):
        occs = by_group[gid]
        group = groups[gid]
        verses = len({o["source_unit_id"] for o in occs})
        if verses < MIN_GROUP_VERSES:
            for occ in occs:
                _audit(result, inp, occ, gid, "INFORMATIONAL", "PC02",
                       "Group has fewer than two confirmed verses in this scope: listed, not compared (AT16).")
            result.counts["informational_groups"] += 1
            continue
        evs = [locate(inp, occ, gid) for occ in sorted(occs, key=lambda o: (o["canonical_ref"], o["body_start"]))]
        result.evidence[gid] = evs
        confirmed = all(o["sense_state"] == "CONFIRMED" for o in occs) and group.get("state", "CONFIRMED") == "CONFIRMED"
        conflict = _conflict(inp.rules, gid)
        code, per = classify(evs, confirmed=confirmed, conflict=conflict, morph=inp.morph)
        result.outcomes[gid] = code
        expr = exprs.get(group["expression_id"], {})
        _emit_group(result, inp, gid, group, expr, evs, code, per, occ_by_id)
    for occ in sorted(unresolved, key=lambda o: o["occurrence_id"]):
        _audit(result, inp, occ, "", "REVIEW", "PC20", "SOURCE sense not resolved; never counted consistent (AT11).")
    by_expr: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for occ in unresolved:
        by_expr[occ["expression_id"]].append(occ)
    for eid, occs in sorted(by_expr.items()):
        _finding(result, inp, "PC20", None, occs, [], [f"{len(occs)} occurrence(s) whose SOURCE sense is not one "
                 f"of the list's senses: {', '.join(sorted({o['source_text_span'] for o in occs}))}"],
                 "SOURCE sense unresolved; decide the sense before this wording is compared.", "LOW")
    if qualify:
        result.qualification = self_qualify(inp, result, seed=seed)
        result.best_effort = [k for k, q in result.qualification.items() if q["status"] == "BEST_EFFORT"]
        label = {"SUBSTITUTION": "PC10", "REMOVAL": "PC11"}
        for kind in result.best_effort:
            q = result.qualification[kind]
            measured = (f"measured {round(100 * q['recall'])}% on {q['trials']} planted case(s)" if q["recall"] is not None
                        and q["trials"] >= QUALIFY_MIN_TRIALS else "not measured: too little text")
            for finding in result.findings:
                if finding["code"] == label[kind]:
                    finding["evidence"].append(f"Best effort for this WIP: {kind.lower()} detection {measured} "
                                               f"(bar {round(100 * QUALIFY_BAR)}%).")
                    if q["recall"] is not None:
                        finding["detection_confidence"] = round(min(finding["detection_confidence"], q["recall"]), 4)
                    result.counts["best_effort_findings"] += 1
    result.findings.sort(key=lambda f: f["finding_id"])
    result.audit.sort(key=lambda r: r["occurrence_id"])
    return result


def _conflict(rules: Mapping[str, Mapping[str, Any]], gid: str) -> bool:
    """Equal-scope APPROVED ACCEPT and REJECT of the same form in one group (PC23)."""
    seen: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for rule in rules.values():
        if rule["group_id"] == gid and rule["state"] == "APPROVED":
            seen[(rule["normalized_target_form"], rule["scope"]["level"], rule["scope"]["identifier"])].add(rule["effect"])
    return any({"ACCEPT", "REJECT"} <= effects for effects in seen.values())


def _audit(result: CheckResult, inp: CheckInput, occ: Mapping[str, Any], gid: str, disposition: str, code: str,
           reason: str) -> None:
    """One audit row."""
    result.audit.append({"schema_version": SCHEMA_VERSION, "run_id": inp.run_id, "occurrence_id": occ["occurrence_id"],
                         "group_id": gid, "disposition": disposition, "result_code": code, "reason": reason})
    result.counts[f"audit_{disposition.lower()}"] += 1


def _finding(result: CheckResult, inp: CheckInput, code: str, gid: str | None, occs: Sequence[Mapping[str, Any]],
             evs: Sequence[Evidence], evidence: list[str], reason: str, severity: str, *, subkind: str = "") -> None:
    """One finding record."""
    rules = sorted({e.rule_id for e in evs if e.rule_id})
    candidate = full_digest([code, subkind, sorted(e.form_key for e in evs)])
    subjects = sorted(o["occurrence_id"] for o in occs)
    result.findings.append({
        "schema_version": SCHEMA_VERSION,
        "finding_id": make_id("finding", {"input": inp.run_input_sha256, "code": code, "subjects": subjects, "candidate": candidate}),
        "run_id": inp.run_id, "code": code, "review_status": "OPEN", "severity": severity,
        "is_blocking": code in ("PC23", "PC24", "PC25"),
        "detection_confidence": round(min((e.confidence for e in evs), default=0.5) or 0.5, 4),
        "semantic_confidence": None, "group_id": gid,
        "issue_cluster_id": make_id("cluster", {"group": gid or subjects[0], "code_family": code[:3]}),
        "source_occurrence_ids": subjects, "source_refs": sorted({o["canonical_ref"] for o in occs}),
        "target_refs": sorted({e.target_ref for e in evs if e.target_ref}),
        "evidence": evidence or [reason], "applied_rule_ids": rules,
        "reason": reason + (f" ({subkind})" if subkind else ""),
    })
    result.counts[f"finding_{code}"] += 1


def _emit_group(result: CheckResult, inp: CheckInput, gid: str, group: Mapping[str, Any], expr: Mapping[str, Any],
                evs: Sequence[Evidence], code: str, per: Mapping[str, str], occ_by_id: Mapping[str, Mapping[str, Any]]) -> None:
    """Audit rows and findings of one compared group."""
    key = any(s.get("discriminator", "").split("(")[-1].split(";")[0].strip() in KEY_CATEGORIES for s in expr.get("senses", ()))
    for ev in evs:
        c = per.get(ev.occurrence_id, code)
        disposition = "BLOCKED" if c == "PC23" else "EVALUATED" if c in ("PC00", "PC01", "PC02") else "REVIEW"
        _audit(result, inp, occ_by_id[ev.occurrence_id], gid, disposition, c, ev.reason or c)
    distribution = _distribution(evs)
    def occs(codes):
        """Occurrences with one of ``codes``."""
        return [occ_by_id[e.occurrence_id] for e in evs if per.get(e.occurrence_id) in codes]
    def bump(severity):
        """Key terms one level higher."""
        order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        return order[min(order.index(severity) + 1, 3)] if key else severity
    label = expr.get("source_surface", gid)
    if code == "PC23":
        _finding(result, inp, "PC23", gid, occs({"PC23"}), evs, distribution,
                 f"'{label}': approved rules accept and reject the same form at the same scope.", "HIGH")
        return
    if any(c == "PC21" for c in per.values()):
        bad = [e for e in evs if per.get(e.occurrence_id) == "PC21"]
        _finding(result, inp, "PC21", gid, occs({"PC21"}), bad, [f"{e.ref}: {e.reason}" for e in bad],
                 f"'{label}': the rendering could not be located reliably; not counted as omission (AT12).", "LOW")
    if any(c == "PC13" for c in per.values()):
        _finding(result, inp, "PC13", gid, occs({"PC13"}), [e for e in evs if per.get(e.occurrence_id) == "PC13"],
                 distribution, f"'{label}': a declared negation marker is present in some renderings and not others.", "HIGH")
    if any(c == "PC11" for c in per.values()):
        _finding(result, inp, "PC11", gid, occs({"PC11"}), [e for e in evs if per.get(e.occurrence_id) == "PC11"],
                 distribution, f"'{label}': no TARGET rendering where the verse otherwise aligns (possible omission).",
                 bump("MEDIUM"))
    if code == "PC10" or any(c == "PC10" for c in per.values()):
        rendered = [e for e in evs if e.status in ("ACCEPTED", "FORM", "REJECTED")]
        ortho = orthographic_only(rendered) and not any(e.status == "REJECTED" for e in rendered)
        rejected = [e for e in rendered if e.status == "REJECTED"]
        reason = (f"'{label}': a rejected rendering is used." if rejected else
                  f"'{label}': the same SOURCE concept and sense is rendered in {len({e.form_key for e in rendered})} "
                  "different ways, not all approved.")
        _finding(result, inp, "PC10", gid, occs({"PC10", "PC01"}), rendered, distribution, reason,
                 "LOW" if ortho else bump("MEDIUM"), subkind="ORTHOGRAPHIC" if ortho else "")


# --- self-qualification (plan L4) --------------------------------------------------------------------------


def self_qualify(inp: CheckInput, result: CheckResult, *, seed: int = 0) -> dict[str, dict[str, Any]]:
    """Plant substitutions and removals into copies of verses whose group looked uniform; measure recall."""
    rng = random.Random(seed)
    # Each candidate is the group's majority rendering (at least two occurrences); the planted case is judged
    # against that rendering only, so other review in the group does not hide or fake a detection.
    candidates = []
    for gid, evs in sorted(result.evidence.items()):
        if result.outcomes.get(gid) == "PC23":
            continue
        rendered = [e for e in evs if e.status in ("ACCEPTED", "FORM")]
        top = Counter(e.form_key for e in rendered).most_common(1)
        if top and top[0][1] >= 2:
            majority = [e for e in rendered if e.form_key == top[0][0]]
            candidates += [(gid, majority, victim) for victim in majority]
    all_forms = sorted({t.norm for tokens in inp.target_side.tokens.values() for t in tokens
                        if t.norm not in inp.target_stops and len(t.norm) >= MIN_STEM})
    # Substitutes are other renderings the model knows for the same SOURCE word (a synonym, the realistic
    # variation PC10 exists for); a random word only when the model knows none.
    renderings: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for (e, f), prob in inp.model.e_given_f.items():
        if prob >= LINK_MIN_PROB and e not in inp.target_stops and len(e) >= MIN_STEM:
            renderings[f].append((prob, e))
    for items in renderings.values():
        items.sort(key=lambda x: (-x[0], x[1]))
    inp_renderings = dict(renderings)
    out = {}
    for kind in KINDS:
        trials = hits = synonyms = 0
        for gid, evs, victim in rng.sample(candidates, min(len(candidates), QUALIFY_SAMPLES)) if candidates else []:
            occ = next(o for o in inp.occurrences if o["occurrence_id"] == victim.occurrence_id)
            planted = _plant(inp, occ, victim, kind, rng, all_forms, evs, inp_renderings)
            if planted is None:
                continue
            planted, synonym = planted
            trials += 1
            code, per = classify([planted if e.occurrence_id == victim.occurrence_id else e for e in evs],
                                 confirmed=True, conflict=False, morph=inp.morph)
            got = per.get(victim.occurrence_id)
            # a known synonym must be caught as variation (PC10); a random word may also read as a gap (PC11)
            wanted = ("PC10",) if kind == "SUBSTITUTION" and synonym else ("PC10", "PC11") if kind == "SUBSTITUTION" else ("PC11",)
            hits += got in wanted
            synonyms += kind == "SUBSTITUTION" and synonym
        recall = round(hits / trials, 3) if trials else None
        status = "CHECKED" if trials >= QUALIFY_MIN_TRIALS and recall is not None and recall >= QUALIFY_BAR else "BEST_EFFORT"
        out[kind] = {"trials": trials, "detected": hits, "recall": recall, "bar": QUALIFY_BAR, "status": status}
        if kind == "SUBSTITUTION":
            out[kind]["known_synonyms"] = synonyms
    return out


def _plant(inp: CheckInput, occ: Mapping[str, Any], ev: Evidence, kind: str, rng: random.Random,
           forms: Sequence[str], group: Sequence[Evidence],
           renderings: Mapping[str, Sequence[tuple[float, str]]] | None = None) -> tuple[Evidence, bool] | None:
    """Locate the occurrence again in a copy of its WIP verse with the rendering replaced or removed."""
    pair_id = inp.unit_pair.get("S:" + occ["source_unit_id"])
    if pair_id is None or not ev.form:
        return None
    tokens = inp.target_side.tokens[pair_id]
    hit = find_form(ev.form_key.split(), tokens, inp.morph) or find_form([nfc_fold(t) for t in ev.form.split()], tokens, inp.morph)
    if hit is None:
        return None
    first, last, _ = hit
    rest = list(tokens[:first]) + list(tokens[last + 1:])
    if find_form([t.norm for t in tokens[first:last + 1]], rest, inp.morph):
        return None  # the rendering occurs twice in the verse: removing one cannot be told from keeping it
    taken = {e.form_key for e in group}
    if kind == "SUBSTITUTION":
        src = inp.source_side.tokens[pair_id]
        occ_tokens = _source_token_span(inp.source_side, pair_id, occ["source_unit_id"], occ["body_start"], occ["body_end"])
        known = [e for j in sorted(occ_tokens) for _, e in (renderings or {}).get(src[j].norm, ())
                 if form_class(e, inp.morph) not in taken]
        choices = known[:1] or [f for f in forms if form_class(f, inp.morph) not in taken]
        if not choices:
            return None
        replacement = [Token(w, w, 0, 0) for w in [choices[0] if known else rng.choice(choices)]]
    else:
        replacement, known = [], []
    copy = list(tokens[:first]) + replacement + list(tokens[last + 1:])
    sub = CheckInput(**{**inp.__dict__, "target_side": Side({**inp.target_side.tokens, pair_id: copy},
                                                           {**inp.target_side.units, pair_id: _owners(inp, pair_id, first, last, len(replacement))})})
    return locate(sub, occ, ev.group_id), bool(known)


def _owners(inp: CheckInput, pair_id: str, first: int, last: int, inserted: int) -> list[str]:
    """Unit owners of a modified token list."""
    owners = inp.target_side.units[pair_id]
    return owners[:first] + [owners[first]] * inserted + owners[last + 1:]
