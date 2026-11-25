"""PCC P5b-3: a Job pins a reference list; the terms Run locates it; re-pin carries rules; WIP attach once.

Fabricated workspace and text only. The original-language analysis and the alignment are fabricated and
patched into the Run (the test workspace has no MACULA package).
"""

from __future__ import annotations

import pytest

import sage.pcc.run as pcc_run
from sage.errors import SageError, ValidationError
from sage.jobs import JobStore, pcc_default_settings
from sage.pcc import glossary
from sage.pcc.align import Alignment, Link
from sage.pcc.contracts import validate_record
from sage.pcc.ids import concept_key, group_id, sense_key
from sage.pcc.jsonl import read_json, read_jsonl
from sage.pcc.pin import pin_for, repin
from sage.pcc.reflist import ENTRIES, ReferenceListStore
from sage.pcc.run import execute_pcc_run, load_run_snapshot, run_initializer
from sage.pcc.segment import tokenize
from sage.pcc.source_text import source_content_sha256
from sage.registry import load_ecosystem
from sage.vrs import VerseRef

TEXT = ["The lamp shone in the house.", "A lamp was lit.", "Then the Lamp went out.", "The house was dark."]
LAMP, HOUSE, BREAD = concept_key("OL", ["GRK:50"]), concept_key("OL", ["GRK:10"]), concept_key("OL", ["GRK:11"])
WORDS = {1: [("λύχνος", "50"), ("οἶκος", "10")], 2: [("λύχνος", "50")], 3: [("λύχνος", "50")], 4: [("οἶκος", "10")]}
LINKS = {"lamp": "50", "house": "10"}


class _W:
    """Stand-in for an ``OlWord``."""

    def __init__(self, word_id, lemma, strong):
        """One noun segment."""
        self.word_id, self.text = word_id, lemma
        self.segments = ({"strong": strong, "lemma": lemma, "pos": "noun", "gloss": lemma},)


class _Analysis:
    """Fabricated Greek words for MAT 1:1-4."""

    package_id = "SYNTHETIC_OL"

    def verses(self, family):
        """Fabricated verses (Greek only)."""
        if family != "GRK":
            return {}
        return {VerseRef("MAT", 1, v): [_W(f"MAT 1:{v}!{i}", lemma, strong) for i, (lemma, strong) in enumerate(words, 1)]
                for v, words in WORDS.items()}


def _alignment(units, *args, **kwargs):
    """Link 'lamp' and 'house' tokens to their fabricated words (stands in for the cached aligner)."""
    tokens, links = {}, {}
    for unit in units:
        verse = int(unit.canonical_ref.split(":")[1])
        tokens[unit.unit_id] = tokenize(unit.text)
        refs = {strong: f"MAT 1:{verse}!{i}" for i, (_, strong) in enumerate(WORDS.get(verse, ()), 1)}
        links[unit.unit_id] = [Link(i, refs[LINKS[t.norm]], "gold", 1.0, f"GRK:{LINKS[t.norm]}")
                               for i, t in enumerate(tokens[unit.unit_id]) if t.norm in LINKS and LINKS[t.norm] in refs]
    return Alignment(tokens, links, {"tokens": 0}, {}), False


@pytest.fixture
def workspace(make_workspace, monkeypatch):
    """A workspace whose SOURCE holds the fabricated text, with the OL analysis and aligner patched."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=4)
    config = load_ecosystem(root / "ecosystem.yml")
    source = config.project("usNIVv2").path
    usfm = next(source.glob("*.SFM"))
    usfm.write_text("\\id MAT\n\\c 1\n\\p\n" + "".join(f"\\v {i} {t}\n" for i, t in enumerate(TEXT, 1)), encoding="utf-8")
    monkeypatch.setattr(pcc_run, "load_ol_analysis", lambda root: _Analysis())
    monkeypatch.setattr(pcc_run, "load_pcc_ol", lambda root: None)
    monkeypatch.setattr(pcc_run, "cached_alignment", _alignment)
    store = JobStore(config.root, config.settings_path)
    return store, config, source


def _entry(concept, label, senses, status="ACTIVE"):
    """One reference-list entry with recurring senses given as (signature, label, verses)."""
    return {"concept_key": concept, "anchor": {"kind": "OL", "value": [{LAMP: "GRK:50", HOUSE: "GRK:10",
                                                                         BREAD: "GRK:11"}[concept]]},
            "label": label, "category": "RE", "status": status, "origin": "BIBLICAL_TERMS", "sources": ["BT:x"],
            "senses": [{"sense_key": sense_key(concept, sig), "kind": "SENSE", "label": sl, "wordings":
                        [{"wording": sl, "verses": n}], "verses": n, "examples": [], "ol_senses": [], "state": "PROPOSED"}
                       for sig, sl, n in senses],
            "realization": {k: 0 for k in ("occurrences", "realized", "function_only", "no_realization", "gold",
                                           "transitive", "direct", "located")},
            "verses": 2, "examples": [], "notes": ""}


V1 = [_entry(LAMP, "λύχνος", [("lamp|LOWER", "lamp", 2)]), _entry(HOUSE, "οἶκος", [("house|LOWER", "house", 2)]),
      _entry(BREAD, "ἄρτος", [("bread|LOWER", "bread", 3)])]
V2 = [_entry(LAMP, "λύχνος", [("lamp|LOWER", "lamp", 2)]), _entry(HOUSE, "οἶκος", [("house|LOWER", "house", 2)])]


def _save(rl_store, source_sha, entries, rl_id="syn-list-0123abcd"):
    """Store one version of the fabricated list."""
    return rl_store.save(
        rl_id=rl_id, title="Syn list",
        reference={"project_id": "usNIVv2", "edition": "usNIVv2", "language_tag": "en", "content_sha256": source_sha,
                   "versification_id": "eng"},
        license={"license_id": "SYNTHETIC", "local_only": True, "note": ""},
        build={"mode": "SCRATCH", "settings": {"suffixes": ["s"], "cased": True}}, entries=entries,
        created_utc="2026-11-25T00:00:00Z")


def _job(store, language="sw"):
    """A PCC Job on the fabricated SOURCE."""
    return store.create_job(tool="pcc", job_id="", display_name="x", bindings={"source": "usNIVv2"},
                            defaults=pcc_default_settings(language))


def _repin(store, job, rl_store, version=None, sha="a" * 64):
    """Pin (or re-pin) the fabricated list."""
    return repin(store, job, rl_store, "syn-list-0123abcd", version, actor="tester",
                 lock_path=job.controller_root / "locks" / "pcc-journal.lock", source_corpus_sha256=sha,
                 reports_root=store.storage.reports_root)


def _terms(store, job):
    """Seal and execute one terms Run over MAT 1."""
    config = load_ecosystem(store.ensure_runtime_files(job))
    run = store.create_run(job, operation="terms", scope="MAT 1",
                           initialize_run=run_initializer(config, job, operation="terms", scope="MAT 1"))
    return config, run


def test_terms_run_locates_the_pinned_list_with_fixed_senses(workspace):
    """Same text: occurrences match the list's senses (CONFIRMED); an unknown wording stays UNRESOLVED."""
    store, _, source = workspace
    rl_store = ReferenceListStore(store.storage.resources_root)
    _save(rl_store, source_content_sha256(source), V1)
    job = _job(store)
    report = _repin(store, job, rl_store)
    job = store.load_job(job.job_id, tool="pcc")
    assert job.defaults["reference_list"] == pin_for(rl_store, "syn-list-0123abcd", 1)
    assert report.added == 3 and report.report_path.is_file()
    config, run = _terms(store, job)
    snapshot = load_run_snapshot(run.root)
    assert snapshot["reference_list"]["rl_id"] == "syn-list-0123abcd"
    summary = execute_pcc_run(store, config, job, run)
    assert "pinned reference list" in summary["limitations"][0]
    output = run.root / "validation" / "pcc"
    assert read_json(output / "run-manifest.json")["reference_index_version"] == "syn-list-0123abcd@1"
    occurrences = read_jsonl(output / "occurrences.jsonl", kind="occurrence")
    lamp = sorted((o["canonical_ref"], o["source_text_span"], o["sense_state"], o["sense_id"]) for o in occurrences
                  if o["source_text_span"].casefold() == "lamp")
    assert lamp == [("MAT 1:1", "lamp", "CONFIRMED", sense_key(LAMP, "lamp|LOWER")),
                    ("MAT 1:2", "lamp", "CONFIRMED", sense_key(LAMP, "lamp|LOWER")),
                    ("MAT 1:3", "Lamp", "UNRESOLVED", None)]
    groups = {g["group_id"]: g for g in read_jsonl(output / "groups.jsonl")}
    assert group_id(LAMP, sense_key(LAMP, "lamp|LOWER")) in groups
    assert group_id(HOUSE, sense_key(HOUSE, "house|LOWER")) in groups
    rows = glossary.terms_rows(output, curate=False)
    assert {r["entry_id"] for r in rows if r["sense_id"]} >= set(groups)
    assert any(r["sense"] == glossary.UNRESOLVED_LABEL and r["occurrences"] == 1 for r in rows)
    assert store.load_run(job, run.run_id).status == "COMPLETE"


def test_list_built_on_another_text_gives_provisional_senses(workspace):
    """Another content hash: the same matching, PROVISIONAL, reported; the terms list still shows the senses."""
    store, _, _ = workspace
    rl_store = ReferenceListStore(store.storage.resources_root)
    _save(rl_store, "f" * 64, V1)
    job = _job(store)
    _repin(store, job, rl_store)
    job = store.load_job(job.job_id, tool="pcc")
    config, run = _terms(store, job)
    execute_pcc_run(store, config, job, run)
    output = run.root / "validation" / "pcc"
    states = {o["sense_state"] for o in read_jsonl(output / "occurrences.jsonl") if o["sense_id"]}
    assert states == {"PROVISIONAL"}
    exceptions = (run.root / "diagnostics" / "EXCEPTION-REPORTS.jsonl").read_text(encoding="utf-8")
    assert "PCC_RL_OTHER_EDITION" in exceptions
    rows = glossary.terms_rows(output, curate=False)
    assert any(r["sense"] == "lamp" and r["occurrences"] == 2 for r in rows)


def test_changed_list_package_stops_a_sealed_run(workspace):
    """Editing the pinned package after the Run sealed it is an integrity stop."""
    store, _, source = workspace
    rl_store = ReferenceListStore(store.storage.resources_root)
    _save(rl_store, source_content_sha256(source), V1)
    job = _job(store)
    _repin(store, job, rl_store)
    job = store.load_job(job.job_id, tool="pcc")
    config, run = _terms(store, job)
    path = rl_store.path("syn-list-0123abcd", 1) / ENTRIES
    path.write_text(path.read_text(encoding="utf-8").replace('"lamp"', '"lantern"'), encoding="utf-8")
    with pytest.raises(ValidationError) as caught:
        execute_pcc_run(store, config, job, run)
    assert caught.value.code == "PCC_RUN_INPUT_STALE"


def test_repin_carries_rules_by_concept_and_marks_dropped_ones_stale(workspace):
    """Rules on concepts still listed carry over; a rule on a dropped concept becomes STALE, never deleted."""
    store, _, source = workspace
    rl_store = ReferenceListStore(store.storage.resources_root)
    _save(rl_store, source_content_sha256(source), V1)
    job = _job(store)
    _repin(store, job, rl_store, 1)
    job = store.load_job(job.job_id, tool="pcc")
    lock = job.controller_root / "locks" / "pcc-journal.lock"
    kept = glossary._rule(group_id(LAMP, sense_key(LAMP, "lamp|LOWER")), "sw", "taa", "ACCEPT", "APPROVED",
                          {"level": "SECG", "identifier": "x"}, "team", [], "tester", "2026-11-25T00:00:00Z")
    gone = glossary._rule(group_id(BREAD, sense_key(BREAD, "bread|LOWER")), "sw", "mkate", "ACCEPT", "APPROVED",
                          {"level": "SECG", "identifier": "y"}, "team", [], "tester", "2026-11-25T00:00:00Z")
    for rule in (kept, gone):
        glossary._append_rule(job, lock, "a" * 64, rule, "APPROVE", "tester", glossary.current_rules(job.root))
    _save(rl_store, source_content_sha256(source), V2)
    report = _repin(store, job, rl_store, 2)
    assert (report.dropped, report.unchanged, report.rules_carried, report.rules_stale) == (1, 2, 1, [gone["rule_id"]])
    rules = glossary.current_rules(job.root)
    assert rules[kept["rule_id"]]["state"] == "APPROVED" and rules[gone["rule_id"]]["state"] == "STALE"
    validate_record("variant_rule", rules[gone["rule_id"]])
    assert store.load_job(job.job_id, tool="pcc").defaults["reference_list"]["version"] == 2
    assert gone["rule_id"] in report.report_path.read_text(encoding="utf-8")


def test_repin_is_refused_while_a_run_is_open(workspace):
    """A pinned list is sealed into open Runs: re-pinning waits until they close."""
    store, _, source = workspace
    rl_store = ReferenceListStore(store.storage.resources_root)
    _save(rl_store, source_content_sha256(source), V1)
    job = _job(store)
    _repin(store, job, rl_store)
    job = store.load_job(job.job_id, tool="pcc")
    _terms(store, job)
    with pytest.raises(ValidationError) as caught:
        _repin(store, job, rl_store)
    assert caught.value.code == "JOB_DEFAULTS_RUN_OPEN"


def test_wip_attaches_once_and_the_job_id_stays(workspace):
    """A Job created without a WIP attaches one once; its ID and identity check are unchanged."""
    store, _, _ = workspace
    job = _job(store, language="en")
    attached = store.attach_pcc_wip(job, "usWIP")
    assert attached.job_id == job.job_id == "PCC_usNIVv2-en" and attached.bindings["wip"] == "usWIP"
    assert store.load_job(job.job_id, tool="pcc").bindings["wip"] == "usWIP"
    with pytest.raises(SageError) as caught:
        store.attach_pcc_wip(attached, "usWIP")
    assert caught.value.code == "PCC_WIP_ALREADY_BOUND"
    other = _job(store, language="sw")
    with pytest.raises(SageError) as caught:
        store.attach_pcc_wip(other, "usWIP")
    assert caught.value.code == "PCC_TARGET_LANGUAGE_MISMATCH"


def test_defaults_validate_the_pin_and_accept_jobs_without_one(workspace):
    """A malformed pin is refused; defaults written before reference lists still load."""
    store, _, _ = workspace
    bad = pcc_default_settings("sw") | {"reference_list": {"rl_id": "x", "version": 0, "sha256": "z"}}
    with pytest.raises(ValidationError) as caught:
        store.create_job(tool="pcc", job_id="", display_name="x", bindings={"source": "usNIVv2"}, defaults=bad)
    assert caught.value.code == "PCC_JOB_DEFAULTS_INVALID"
    legacy = {k: v for k, v in pcc_default_settings("sw").items() if k != "reference_list"}
    job = store.create_job(tool="pcc", job_id="", display_name="x", bindings={"source": "usNIVv2"}, defaults=legacy)
    assert job.defaults["reference_list"] is None
