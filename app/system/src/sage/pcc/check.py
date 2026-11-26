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
from dataclasses import dataclass, field, replace
from typing import Any

from ..references import parse_scope
from ..vrs import VerseRef, VersificationSchema
from .align import DirectModel, OlToken, _NULL, _prior, train_direct
from .contracts import SCHEMA_VERSION
from .discovery import SourceUnit
from .ids import make_id
from .resolver import Site, resolve, text_hash
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
KINDS = ("SUBSTITUTION", "REMOVAL")                 # forward kinds; INSERTION (PC12) is planted by the reverse scan
KIND_CODE = {"SUBSTITUTION": "PC10", "REMOVAL": "PC11", "INSERTION": "PC12"}
REVERSE_NEAR = 1              # pairs either side of a PC11 omission where a stray rendering may have moved
REVERSE_CONFIDENCE = 0.3      # PC12 is a lower-confidence review candidate, never an error verdict (REV03)
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
    status: str                  # ACCEPTED | REJECTED | CONFLICT | FORM | OMISSION | UNCERTAIN | NO_TARGET_VERSE
    form: str = ""               # TARGET wording as written
    form_key: str = ""           # comparison class
    variant: str = ""            # EXACT | SPELLING | INFLECTION | LEARNED
    rule_id: str = ""
    target_ref: str = ""
    confidence: float = 0.0
    negated: bool = False
    reason: str = ""
    nth: int = 0                 # occurrence of the group within its SOURCE verse (OCCURRENCE scope)
    verse_hash: str = ""         # SOURCE verse + paired WIP verse(s)
    level: str = ""              # scope of the deciding rule
    stale: tuple[str, ...] = ()  # approved rules that would apply but whose text changed (AT13)


def best_links(model: DirectModel, src: Sequence[Token], tgt: Sequence[Token], lam: float = CHECK_LAMBDA
               ) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Each WIP token's best SOURCE token and each SOURCE token's best WIP token, with posteriors."""
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
    return best_src, best_tgt


def learned_span(model: DirectModel, src: Sequence[Token], tgt: Sequence[Token], occ: set[int],
                 stops: frozenset[str], source_stops: frozenset[str], lam: float = CHECK_LAMBDA
                 ) -> tuple[list[int], bool, float, bool]:
    """Target tokens of the occurrence, whether reliable, their mean posterior, and whether the verse aligns."""
    if not src or not tgt:
        return [], False, 0.0, False
    nt = len(tgt)
    best_src, best_tgt = best_links(model, src, tgt, lam)
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
    details: list[dict[str, Any]] = field(default_factory=list)      # per finding: its occurrences and forms (P7-4)
    stale_rules: dict[str, list[str]] = field(default_factory=dict)  # rule -> sites where its text changed
    reverse: list[dict[str, Any]] = field(default_factory=list)      # P8: one row per rendering found outside its group


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
    verse_hashes: Mapping[str, str] = field(default_factory=dict)    # WIP canonical ref -> text hash (passages)
    decisions: Mapping[str, str] = field(default_factory=dict)       # finding id -> review status (P7-4)
    scope_units: frozenset[str] | None = None                        # SOURCE units of the scope (None: every pair)


def wip_verse_hashes(target_units: Mapping[str, SourceUnit]) -> dict[str, str]:
    """Canonical WIP verse -> hash of its unit text (a bridge shares its unit's hash)."""
    found: dict[str, str] = {}
    for unit in target_units.values():
        h = text_hash(unit.text)
        for ref in unit.native_refs:
            found.setdefault(ref, h)
    return found


def pair_hash(inp: "CheckInput", pair_id: str, source_unit: str) -> str:
    """Hash binding an occurrence: its SOURCE verse text and the paired WIP verse text(s)."""
    pair = next(p for p in inp.pairs if p.pair_id == pair_id) if not hasattr(inp, "_pair_index") else inp._pair_index[pair_id]
    return text_hash(inp.source_units[source_unit].text, *(inp.target_units[u].text for u in pair.target))


def _source_token_span(side: Side, pair_id: str, unit: str, start: int, end: int) -> set[int]:
    """Indices of the pair's SOURCE tokens inside an occurrence's code-point span."""
    return {i for i, (t, u) in enumerate(zip(side.tokens[pair_id], side.units[pair_id]))
            if u == unit and t.start < end and t.end > start}


def _group_rules(rules: Mapping[str, Mapping[str, Any]], group: str) -> list[Mapping[str, Any]]:
    """The group's rules plus WIP-language rules, longest form first (any state: all of them locate forms)."""
    found = [r for r in rules.values() if r["group_id"] == group
             or (r["scope"]["level"] == "LANGUAGE_PROFILE" and "=" not in r["normalized_target_form"])]
    return sorted(found, key=lambda r: (r["state"] != "APPROVED", -len(r["normalized_target_form"]), r["rule_id"]))


def locate(inp: CheckInput, occ: Mapping[str, Any], group: str, nth: int = 0) -> Evidence:
    """B2 + P7-2: find the rendering (glossary forms first, then the learned span), then resolve its rules."""
    ref = occ["canonical_ref"]
    pair_id = inp.unit_pair.get("S:" + occ["source_unit_id"])
    if pair_id is None:
        return Evidence(occ["occurrence_id"], group, ref, "NO_TARGET_VERSE", reason="NO_TARGET_VERSE", nth=nth)
    vhash = pair_hash(inp, pair_id, occ["source_unit_id"])
    tgt = inp.target_side.tokens[pair_id]
    owners = inp.target_side.units[pair_id]
    rules = _group_rules(inp.rules, group)
    found = None
    for rule in rules:
        hit = find_form([nfc_fold(t) for t in rule["normalized_target_form"].split()], tgt, inp.morph)
        if hit is not None:
            found = (hit, "glossary form")
            break
    if found is None:
        src = inp.source_side.tokens[pair_id]
        span_src = _source_token_span(inp.source_side, pair_id, occ["source_unit_id"], occ["body_start"], occ["body_end"])
        span, reliable, mean, aligned = learned_span(inp.model, src, tgt, span_src, inp.target_stops, inp.source_stops)
        target_ref = inp.target_units[owners[0]].canonical_ref if owners else ref
        if not (span and reliable):
            if not span and aligned:
                return Evidence(occ["occurrence_id"], group, ref, "OMISSION", target_ref=target_ref, nth=nth,
                                verse_hash=vhash, reason="the verse aligns but nothing in it renders this SOURCE wording")
            return Evidence(occ["occurrence_id"], group, ref, "UNCERTAIN", target_ref=target_ref, confidence=mean, nth=nth,
                            verse_hash=vhash, reason="alignment too weak to locate the rendering")
        found = ((span[0], span[-1], "LEARNED"), "learned alignment")
        confidence = mean
    else:
        confidence = 0.95
    (first, last, kind), how = found
    unit = inp.target_units[owners[first]]
    text = unit.text[tgt[first].start:tgt[last].end] if owners[first] == owners[last] else " ".join(t.text for t in tgt[first:last + 1])
    norm = " ".join(t.norm for t in tgt[first:last + 1])
    key = form_class(norm, inp.morph)
    site = Site(group, ref, nth, vhash)
    decision = resolve(rules, site, key, lambda form: form_class(nfc_fold(form), inp.morph), inp.verse_hashes)
    status = {"ACCEPT": "ACCEPTED", "CONTEXT_ONLY": "ACCEPTED", "REJECT": "REJECTED", "CONFLICT": "CONFLICT"}.get(decision.effect or "", "FORM")
    if status == "ACCEPTED" and kind == "LEARNED":
        approved = {nfc_fold(r["normalized_target_form"]) for r in rules if r["rule_id"] in decision.rule_ids}
        kind = "EXACT" if nfc_fold(norm) in approved else "INFLECTION"
    reason = how + (f"; {decision.effect.lower()} by {', '.join(decision.rule_ids)} ({decision.level})" if decision.effect
                    else "; no approved rule")
    return Evidence(occ["occurrence_id"], group, ref, status, text, key, kind, ",".join(decision.rule_ids),
                    unit.canonical_ref, confidence, _negated(tgt, first, last, inp.morph), reason, nth, vhash,
                    decision.level, decision.stale)


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


def classify(evs: Sequence[Evidence], *, confirmed: bool, morph: Morphology,
             conflict: bool = False) -> tuple[str, dict[str, str]]:
    """Group code and per-occurrence codes, in the handover's decision order (doc 02)."""
    per: dict[str, str] = {}
    if conflict or any(e.status == "CONFLICT" for e in evs):
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
    if not inp.verse_hashes:
        inp.verse_hashes = wip_verse_hashes(inp.target_units)
    inp._pair_index = {p.pair_id: p for p in inp.pairs}
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
        ordered = sorted(occs, key=lambda o: (o["canonical_ref"], o["source_unit_id"], o["body_start"]))
        seen: Counter[str] = Counter()
        evs = []
        for occ in ordered:
            evs.append(locate(inp, occ, gid, seen[occ["source_unit_id"]]))
            seen[occ["source_unit_id"]] += 1
        for ev in evs:
            for rule_id in ev.stale:
                result.stale_rules.setdefault(rule_id, []).append(ev.ref)
        result.evidence[gid] = evs
        confirmed = all(o["sense_state"] == "CONFIRMED" for o in occs) and group.get("state", "CONFIRMED") == "CONFIRMED"
        code, per = classify(evs, confirmed=confirmed, morph=inp.morph)
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
    ctx = reverse_scan(inp, result)
    result.reverse.sort(key=lambda r: (r["group_id"], r["pair_id"]))
    if qualify:
        result.qualification = self_qualify(inp, result, seed=seed)
        result.qualification["INSERTION"] = qualify_insertion(inp, result, ctx, seed=seed)
        result.best_effort = [k for k, q in result.qualification.items() if q["status"] == "BEST_EFFORT"]
        label = KIND_CODE
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
    status = {"CONFIRMED_ISSUE": "CONFIRMED_ISSUE", "DISMISS": "DISMISSED", "DEFER": "DEFERRED"}
    for finding in result.findings:
        decided = inp.decisions.get(finding["finding_id"])
        if decided in status:
            finding["review_status"] = status[decided]
            result.counts["decided_findings"] += 1
    result.findings.sort(key=lambda f: f["finding_id"])
    result.details.sort(key=lambda d: d["finding_id"])
    result.audit.sort(key=lambda r: r["occurrence_id"])
    return result


def _audit(result: CheckResult, inp: CheckInput, occ: Mapping[str, Any], gid: str, disposition: str, code: str,
           reason: str) -> None:
    """One audit row."""
    result.audit.append({"schema_version": SCHEMA_VERSION, "run_id": inp.run_id, "occurrence_id": occ["occurrence_id"],
                         "group_id": gid, "disposition": disposition, "result_code": code, "reason": reason})
    result.counts[f"audit_{disposition.lower()}"] += 1


def _finding(result: CheckResult, inp: CheckInput, code: str, gid: str | None, occs: Sequence[Mapping[str, Any]],
             evs: Sequence[Evidence], evidence: list[str], reason: str, severity: str, *, subkind: str = "",
             cluster: str = "", confidence: float | None = None) -> str:
    """One finding record; returns its id. Each finding is its own issue cluster unless ``cluster`` links it to
    another finding on the same problem (AT29)."""
    rules = sorted({r for e in evs for r in e.rule_id.split(",") if r})
    subjects = sorted(o["occurrence_id"] for o in occs)
    # Stable identity (P7-4): group, code, and each occurrence's place, form and verse text. A decision on a
    # finding holds in later Runs until one of these changes.
    if evs:
        items = sorted([e.ref, e.nth, e.form_key, e.verse_hash] for e in evs)
    else:
        items = sorted([o["canonical_ref"], o["source_text_span"], text_hash(inp.source_units[o["source_unit_id"]].text)]
                       for o in occs)
    finding_id = make_id("finding", {"group": gid, "code": code, "subkind": subkind, "items": items})
    result.details.append({"finding_id": finding_id, "group_id": gid, "code": code, "items": [
        {"occurrence_id": e.occurrence_id, "ref": e.ref, "nth": e.nth, "verse_hash": e.verse_hash, "form": e.form,
         "form_key": e.form_key, "status": e.status, "rule_ids": e.rule_id} for e in sorted(evs, key=lambda e: (e.ref, e.nth))]})
    result.findings.append({
        "schema_version": SCHEMA_VERSION,
        "finding_id": finding_id,
        "run_id": inp.run_id, "code": code, "review_status": "OPEN", "severity": severity,
        "is_blocking": code in ("PC23", "PC24", "PC25"),
        "detection_confidence": confidence if confidence is not None else round(min((e.confidence for e in evs), default=0.5) or 0.5, 4),
        "semantic_confidence": None, "group_id": gid,
        "issue_cluster_id": cluster or make_id("cluster", {"group": gid or subjects[0], "code": code, "subkind": subkind}),
        "source_occurrence_ids": subjects, "source_refs": sorted({o["canonical_ref"] for o in occs} or {e.ref for e in evs}),
        "target_refs": sorted({e.target_ref for e in evs if e.target_ref}),
        "evidence": evidence or [reason], "applied_rule_ids": rules,
        "reason": reason + (f" ({subkind})" if subkind else ""),
    })
    result.counts[f"finding_{code}"] += 1
    return finding_id


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
        _finding(result, inp, "PC23", gid, occs({"PC23"}), evs, distribution + [f"{e.ref}: {e.reason}" for e in evs
                                                                                 if e.status == "CONFLICT"],
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


# --- reverse scan (plan B5, P8) -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ScanForm:
    """A TARGET rendering of a compared group that the reverse scan looks for in the group's other verses."""

    group_id: str
    key: tuple[str, ...]          # comparison class, one entry per token
    tokens: tuple[str, ...]       # token norms of one written form (what self-qualification plants)
    origin: str                   # where the form comes from: an approved rule or the learned distribution
    learned: bool


@dataclass
class ReverseContext:
    """What the SOURCE side lists and the forward check located, per verse pair."""

    pairs: list[Pair]
    index: dict[str, int]                                  # pair -> position (for neighbouring verses)
    postings: dict[str, set[str]]                          # WIP comparison token -> pairs holding it
    group_pairs: dict[str, set[str]]                       # group -> pairs where SOURCE has it
    wording_pairs: dict[str, set[str]]                     # expression -> pairs where SOURCE has the wording
    rendered_at: dict[str, set[tuple[str, str]]]           # pair -> (group, form class) located there
    omission_pairs: dict[str, set[str]]                    # group -> pairs of its PC11 occurrences


def scan_forms(inp: CheckInput, result: CheckResult) -> list[ScanForm]:
    """Approved group renderings and renderings learned at two or more of the group's occurrences (REV01)."""
    occ_by_id = {o["occurrence_id"]: o for o in inp.occurrences}
    forms: dict[tuple[str, tuple[str, ...]], ScanForm] = {}
    for gid, evs in sorted(result.evidence.items()):
        if result.outcomes.get(gid) == "PC23":
            continue
        for rule in sorted(inp.rules.values(), key=lambda r: r["rule_id"]):
            if (rule["group_id"] == gid and rule["state"] == "APPROVED" and rule["effect"] in ("ACCEPT", "CONTEXT_ONLY")
                    and rule["scope"]["level"] == "SECG" and "=" not in rule["normalized_target_form"]):
                tokens = tuple(nfc_fold(rule["normalized_target_form"]).split())
                key = tuple(form_class(" ".join(tokens), inp.morph).split())
                forms.setdefault((gid, key), ScanForm(gid, key, tokens, f"approved rule {rule['rule_id']}", False))
        seen = Counter(e.form_key for e in evs if e.status in ("ACCEPTED", "FORM") and e.form_key)
        for key_text, n in sorted(seen.items()):
            if n < 2:
                continue
            key = tuple(key_text.split())
            if (gid, key) in forms:
                continue
            # the written tokens of the first occurrence carrying this form
            for ev in sorted(evs, key=lambda e: (e.ref, e.nth)):
                pair_id = inp.unit_pair.get("S:" + occ_by_id[ev.occurrence_id]["source_unit_id"]) if ev.form_key == key_text else None
                hit = find_form(list(key), inp.target_side.tokens[pair_id], inp.morph) if pair_id else None
                if hit:
                    tokens = tuple(t.norm for t in inp.target_side.tokens[pair_id][hit[0]:hit[1] + 1])
                    forms[(gid, key)] = ScanForm(gid, key, tokens, f"learned at {n} occurrences", True)
                    break
    return [f for _, f in sorted(forms.items()) if f.key]


def _scope_pairs(inp: CheckInput) -> list[Pair]:
    """Verse pairs of the Run's scope."""
    if inp.scope_units is None:
        return list(inp.pairs)
    return [p for p in inp.pairs if any(u in inp.scope_units for u in p.source)]


def reverse_context(inp: CheckInput, result: CheckResult) -> ReverseContext:
    """Index the scope's WIP tokens and what the forward check found per pair."""
    pairs = _scope_pairs(inp)
    postings: dict[str, set[str]] = defaultdict(set)
    for pair in pairs:
        for token in inp.target_side.tokens[pair.pair_id]:
            postings[inp.morph.stem(inp.morph.spell(token.norm))].add(pair.pair_id)
    occ_by_id = {o["occurrence_id"]: o for o in inp.occurrences}
    wording_pairs: dict[str, set[str]] = defaultdict(set)
    for occ in inp.occurrences:
        pair_id = inp.unit_pair.get("S:" + occ["source_unit_id"])
        if pair_id:
            wording_pairs[occ["expression_id"]].add(pair_id)
    group_pairs: dict[str, set[str]] = defaultdict(set)
    rendered_at: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for gid, evs in result.evidence.items():
        for ev in evs:
            pair_id = inp.unit_pair.get("S:" + occ_by_id[ev.occurrence_id]["source_unit_id"])
            if pair_id:
                group_pairs[gid].add(pair_id)
                if ev.status in ("ACCEPTED", "FORM", "REJECTED") and ev.form_key:
                    rendered_at[pair_id].add((gid, ev.form_key))
    omission_pairs: dict[str, set[str]] = defaultdict(set)
    for row in result.audit:
        if row["result_code"] == "PC11":
            pair_id = inp.unit_pair.get("S:" + occ_by_id[row["occurrence_id"]]["source_unit_id"])
            if pair_id:
                omission_pairs[row["group_id"]].add(pair_id)
    return ReverseContext(pairs, {p.pair_id: i for i, p in enumerate(inp.pairs)}, postings, group_pairs, wording_pairs,
                          rendered_at, omission_pairs)


def reverse_support(inp: CheckInput, ctx: ReverseContext, form: ScanForm, pair_id: str, tgt: Sequence[Token],
                    first: int, last: int, expression_id: str) -> tuple[str, str]:
    """REV01-REV03: is a rendering found outside its group supported by something else in the SOURCE verse?

    ``SUPPORTED_RENDERING`` (another listed SOURCE concept is rendered with this form here), ``SUPPORTED_WORDING``
    (the group's SOURCE wording is here, in another sense or not compared), ``SUPPORTED_ALIGNMENT`` (a SOURCE word
    of the verse links to it: an alternate construction or an explicit referent, AT09), ``UNCERTAIN`` (the verse
    does not align well enough to claim anything) or ``ADDED`` (a possible addition: ``PC12``, AT08).
    """
    key = " ".join(form.key)
    other = sorted(g for g, k in ctx.rendered_at.get(pair_id, ()) if k == key and g != form.group_id)
    if other:
        return "SUPPORTED_RENDERING", f"rendering of another listed concept here ({other[0]})"
    if pair_id in ctx.wording_pairs.get(expression_id, ()):
        return "SUPPORTED_WORDING", "the SOURCE wording is in this verse (another sense, or not compared)"
    src = inp.source_side.tokens[pair_id]
    if not src or not tgt:
        return "UNCERTAIN", "empty verse"
    # Support is word translation probability in either direction, without the position prior: the question is
    # whether any SOURCE word of the verse is rendered this way, wherever it stands (languages reorder).
    for i in range(first, last + 1):
        for j, f in enumerate(src):
            if (inp.model.e_given_f.get((tgt[i].norm, f.norm), 0.0) >= LINK_MIN_PROB
                    or inp.model.f_given_e.get((f.norm, tgt[i].norm), 0.0) >= LINK_MIN_PROB):
                return "SUPPORTED_ALIGNMENT", f"SOURCE word {j + 1} of the verse is rendered this way elsewhere"
    best_src, best_tgt = best_links(inp.model, src, tgt)
    content = [j for j, f in enumerate(src) if f.norm not in inp.source_stops]
    linked = {j for i, (j, _) in enumerate(best_src) if inp.model.e_given_f.get((tgt[i].norm, src[j].norm), 0.0) >= LINK_MIN_PROB}
    linked |= {j for j, (i, _) in enumerate(best_tgt) if inp.model.e_given_f.get((tgt[i].norm, src[j].norm), 0.0) >= LINK_MIN_PROB}
    if not content or sum(1 for j in content if j in linked) / len(content) < VERSE_ALIGNED_SHARE:
        return "UNCERTAIN", "the verse does not align well enough to judge"
    return "ADDED", "no SOURCE word of the verse links to it"


def reverse_scan(inp: CheckInput, result: CheckResult) -> ReverseContext | None:
    """B5: look for every group rendering in the scope's other verses; unsupported ones are ``PC12`` (AT08, AT09).

    A ``PC12`` next to a verse where the same group's rendering is missing (``PC11``) is a possibly moved
    rendering (subkind ``NEAR_OMISSION``) and shares that ``PC11``'s issue cluster (AT29). Each hit gets one row
    in ``result.reverse``; nothing here is an error verdict (REV03).
    """
    forms = scan_forms(inp, result)
    if not forms:
        return None
    ctx = reverse_context(inp, result)
    groups = {g["group_id"]: g for g in inp.groups}
    exprs = {e["expression_id"]: e for e in inp.expressions}
    pair_by_id = {p.pair_id: p for p in inp.pairs}
    added: dict[str, list[tuple[Evidence, bool]]] = defaultdict(list)
    done: set[tuple[str, str]] = set()
    for form in forms:
        candidates = set.intersection(*(ctx.postings.get(t, set()) for t in form.key))
        outside = candidates - ctx.group_pairs.get(form.group_id, set())
        others = len(ctx.pairs) - len(ctx.group_pairs.get(form.group_id, ()))
        if outside and len(outside) / max(others, 1) >= STOP_SHARE:
            # common in the verses without the concept too (a function word or a general word): not a rendering
            # that can be traced back to this concept
            result.counts["reverse_common_forms"] += 1
            continue
        expression_id = groups[form.group_id]["expression_id"]
        for pair_id in sorted(outside):
            if (form.group_id, pair_id) in done:
                continue
            tgt = inp.target_side.tokens[pair_id]
            hit = find_form(list(form.key), tgt, inp.morph)
            if hit is None:
                continue
            done.add((form.group_id, pair_id))
            first, last, _ = hit
            disposition, why = reverse_support(inp, ctx, form, pair_id, tgt, first, last, expression_id)
            pair = pair_by_id[pair_id]
            owners = inp.target_side.units[pair_id]
            unit = inp.target_units[owners[first]]
            text = unit.text[tgt[first].start:tgt[last].end] if owners[first] == owners[last] else " ".join(t.text for t in tgt[first:last + 1])
            source_ref = inp.source_units[pair.source[0]].canonical_ref
            result.reverse.append({"group_id": form.group_id, "pair_id": pair_id, "source_ref": source_ref,
                                   "target_ref": unit.canonical_ref, "form": text, "form_key": " ".join(form.key),
                                   "origin": form.origin, "disposition": disposition, "reason": why})
            result.counts[f"reverse_{disposition.lower()}"] += 1
            if disposition != "ADDED":
                continue
            near = any(abs(ctx.index[pair_id] - ctx.index[o]) <= REVERSE_NEAR
                       and inp.source_units[pair_by_id[o].source[0]].canonical_ref.split(" ")[0] == source_ref.split(" ")[0]
                       for o in ctx.omission_pairs.get(form.group_id, ()))
            ev = Evidence("", form.group_id, source_ref, "ADDED", text, " ".join(form.key), "", "", unit.canonical_ref,
                          REVERSE_CONFIDENCE, False, f"{why} ({form.origin})", 0, pair_hash(inp, pair_id, pair.source[0]))
            added[form.group_id].append((ev, near))
    for gid in sorted(added):
        label = exprs.get(groups[gid]["expression_id"], {}).get("source_surface", gid)
        where = _distribution(result.evidence.get(gid, ()))[:3]
        for near in (True, False):
            evs = sorted((e for e, n in added[gid] if n == near), key=lambda e: e.ref)
            if not evs:
                continue
            lines = [f"{e.ref}: '{e.form}' ({e.reason})" for e in evs] + [f"Where SOURCE has '{label}': " + "; ".join(where)]
            if near:
                pc11 = next((f for f in result.findings if f["group_id"] == gid and f["code"] == "PC11"), None)
                _finding(result, inp, "PC12", gid, [], evs, lines,
                         f"'{label}': its rendering appears next to a verse where it is missing; it may have moved "
                         "across the verse boundary (review, not an error verdict).", "LOW", subkind="NEAR_OMISSION",
                         cluster=pc11["issue_cluster_id"] if pc11 else "", confidence=REVERSE_CONFIDENCE)
            else:
                _finding(result, inp, "PC12", gid, [], evs, lines,
                         f"'{label}': its rendering appears where the SOURCE has no matching wording and no SOURCE word "
                         "links to it (possible addition; review, not an error verdict).", "LOW",
                         confidence=REVERSE_CONFIDENCE)
    return ctx


def qualify_insertion(inp: CheckInput, result: CheckResult, ctx: ReverseContext | None, *, seed: int = 0) -> dict[str, Any]:
    """L4 for the reverse scan: plant a learned group rendering into a verse without the group and count PC12."""
    rng = random.Random(seed + 1)
    forms = [f for f in scan_forms(inp, result) if f.learned] if ctx else []
    pair_ids = sorted(p.pair_id for p in ctx.pairs) if ctx else []
    groups = {g["group_id"]: g for g in inp.groups}
    trials = hits = attempts = 0
    while forms and pair_ids and trials < QUALIFY_SAMPLES and attempts < 20 * QUALIFY_SAMPLES:
        attempts += 1
        form, pair_id = rng.choice(forms), rng.choice(pair_ids)
        expression_id = groups[form.group_id]["expression_id"]
        tokens = inp.target_side.tokens[pair_id]
        if (pair_id in ctx.group_pairs.get(form.group_id, ()) or pair_id in ctx.wording_pairs.get(expression_id, ())
                or any(k == " ".join(form.key) for _, k in ctx.rendered_at.get(pair_id, ()))
                or not tokens or find_form(list(form.key), tokens, inp.morph)):
            continue
        at = rng.randrange(len(tokens) + 1)
        copy = list(tokens[:at]) + [Token(w, w, 0, 0) for w in form.tokens] + list(tokens[at:])
        disposition, _ = reverse_support(inp, ctx, form, pair_id, copy, at, at + len(form.tokens) - 1, expression_id)
        trials += 1
        hits += disposition == "ADDED"
    recall = round(hits / trials, 3) if trials else None
    status = "CHECKED" if trials >= QUALIFY_MIN_TRIALS and recall is not None and recall >= QUALIFY_BAR else "BEST_EFFORT"
    return {"trials": trials, "detected": hits, "recall": recall, "bar": QUALIFY_BAR, "status": status}


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
                                 confirmed=True, morph=inp.morph)
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
    sub = replace(inp, target_side=Side({**inp.target_side.tokens, pair_id: copy},
                                         {**inp.target_side.units, pair_id: _owners(inp, pair_id, first, last, len(replacement))}))
    sub._pair_index = inp._pair_index
    return locate(sub, occ, ev.group_id, ev.nth), bool(known)


def _owners(inp: CheckInput, pair_id: str, first: int, last: int, inserted: int) -> list[str]:
    """Unit owners of a modified token list."""
    owners = inp.target_side.units[pair_id]
    return owners[:first] + [owners[first]] * inserted + owners[last + 1:]
