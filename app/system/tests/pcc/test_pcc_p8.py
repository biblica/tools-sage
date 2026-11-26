"""PCC P8: reverse scan (PC12) and issue clusters. Fabricated texts only (AT08, AT09, AT29)."""

from __future__ import annotations

from types import SimpleNamespace

from sage.pcc.check import run_check
from sage.pcc.contracts import validate_record
from sage.pcc.decisions import current_finding_decisions, import_finding_decisions

from .test_pcc_check import _corpus, _input, _token_occurrences, _units, _wordy
from .test_pcc_p7 import _decide

CONCEPT, RENDERING = "sb", "tb"          # SOURCE word 1 and its consistent rendering in the fabricated corpus


def _texts():
    """The consistent fabricated corpus as editable {verse: text} maps (SOURCE has 'sb' in every 4th verse)."""
    s, t = _wordy(_corpus()[0]), _wordy(_corpus()[1])
    return dict(s), dict(t)


def _run(s, t, *, qualify=False, scope=None, occs=None):
    """Check the concept over the texts."""
    source, target = _units("S", sorted(s.items())), _units("T", sorted(t.items()))
    inp, gid = _input(source, target, occs if occs is not None else _token_occurrences(source, CONCEPT))
    if scope is not None:
        inp.scope_units = frozenset(scope)
    return run_check(inp, qualify=qualify), gid, inp


def _rows(result, ref):
    """Reverse-scan rows at one SOURCE verse."""
    return [r for r in result.reverse if r["source_ref"] == ref]


def _pc12(result):
    """PC12 findings."""
    return [f for f in result.findings if f["code"] == "PC12"]


def test_rendering_without_source_support_is_a_pc12_candidate():
    """AT08: the concept's rendering added to a verse whose SOURCE lacks the concept is PC12, low and open."""
    s, t = _texts()
    assert CONCEPT not in s[10].split()
    t[10] = t[10] + " " + RENDERING
    result, gid, _ = _run(s, t)
    rows = _rows(result, "GEN 1:10")
    assert [r["disposition"] for r in rows] == ["ADDED"] and rows[0]["form"] == RENDERING
    finding = next(f for f in _pc12(result) if "GEN 1:10" in f["source_refs"])
    assert finding["group_id"] == gid and finding["severity"] == "LOW" and finding["review_status"] == "OPEN"
    assert finding["detection_confidence"] <= 0.3 and not finding["is_blocking"]
    assert finding["target_refs"] == ["GEN 1:10"] and not finding["source_occurrence_ids"]
    for record in result.findings:
        validate_record("finding", record)
    clean, _, _ = _run(*_texts())
    assert not any(r["disposition"] == "ADDED" for r in clean.reverse) and not _pc12(clean)


def test_alternate_source_construction_suppresses_pc12():
    """AT09: where another SOURCE word is regularly rendered the same way, the rendering is supported there."""
    s, t = _texts()
    alternate = "sh"                                          # SOURCE word 7, rendered 'th'
    for n in s:
        if alternate in s[n].split():
            t[n] = " ".join(RENDERING if w == "th" else w for w in t[n].split())
    result, _, _ = _run(s, t)
    supported = [r for r in result.reverse if r["disposition"] == "SUPPORTED_ALIGNMENT"]
    assert supported and not any(r["disposition"] == "ADDED" for r in result.reverse)
    assert not _pc12(result)


def test_same_wording_in_another_sense_and_weak_verses_are_not_pc12():
    """REV02/REV03: the group's SOURCE wording in another sense supports it; a verse that does not align is
    UNCERTAIN, never PC12."""
    s, t = _texts()
    s[10], t[10] = s[10] + " " + CONCEPT, t[10] + " " + RENDERING
    source = _units("S", sorted(s.items()))
    occs = _token_occurrences(source, CONCEPT)
    other = next(o for o in occs if o["canonical_ref"] == "GEN 1:10")
    other.update(sense_id="SENSE-2", sense_state="CONFIRMED")   # no group for this sense
    present = set(s[9].split())
    t[9] = " ".join([w for w in ("tc", "td", "te", "tf", "tg", "ti", "tj") if "s" + w[1:] not in present][:4] + [RENDERING])
    result, _, _ = _run(s, t, occs=occs)
    assert [r["disposition"] for r in _rows(result, "GEN 1:10")] == ["SUPPORTED_WORDING"]
    assert [r["disposition"] for r in _rows(result, "GEN 1:9")] == ["UNCERTAIN"]
    assert not _pc12(result)


def test_moved_rendering_shares_the_omission_cluster():
    """AT29: an omission in one verse and the rendering in the next are one issue: PC11 and PC12 share a cluster;
    an unrelated addition elsewhere is its own issue."""
    s, t = _texts()
    assert CONCEPT in s[4].split() and CONCEPT not in s[5].split() and CONCEPT not in s[30].split()
    t[4] = " ".join(w for w in t[4].split() if w != RENDERING)
    t[5], t[30] = t[5] + " " + RENDERING, t[30] + " " + RENDERING
    result, _, _ = _run(s, t)
    pc11 = next(f for f in result.findings if f["code"] == "PC11")
    moved = next(f for f in _pc12(result) if "NEAR_OMISSION" in f["reason"])
    added = next(f for f in _pc12(result) if "NEAR_OMISSION" not in f["reason"])
    assert moved["source_refs"] == ["GEN 1:5"] and added["source_refs"] == ["GEN 1:30"]
    assert moved["issue_cluster_id"] == pc11["issue_cluster_id"] != added["issue_cluster_id"]
    assert len({f["issue_cluster_id"] for f in result.findings}) == len(result.findings) - 1


def test_reverse_scan_stays_inside_the_scope():
    """Verses outside the Run's scope are not scanned."""
    s, t = _texts()
    t[200] = t[200] + " " + RENDERING
    inside = [f"S{n}" for n in range(1, 101)]
    result, _, _ = _run(s, t, scope=inside, occs=[o for o in _token_occurrences(_units("S", sorted(s.items())), CONCEPT)
                                                  if o["source_unit_id"] in inside])
    assert not _rows(result, "GEN 1:200") and not _pc12(result)


def test_insertion_self_qualification_and_determinism():
    """L4: planted insertions into verses without the concept are found as PC12; output is deterministic."""
    s, t = _texts()
    first, _, _ = _run(s, t, qualify=True)
    q = first.qualification["INSERTION"]
    assert q["trials"] >= 20 and q["recall"] >= 0.8 and q["status"] == "CHECKED"
    second, _, _ = _run(s, t, qualify=True)
    assert first.findings == second.findings and first.reverse == second.reverse


def test_pc12_takes_status_decisions_only(tmp_path):
    """P7-4 on PC12: DISMISS holds in the next Run; APPROVE_VARIANT is refused with the row number."""
    s, t = _texts()
    t[10] = t[10] + " " + RENDERING
    result, _, inp = _run(s, t)
    finding = _pc12(result)[0]
    job = SimpleNamespace(root=tmp_path / "job", job_id="PCC_T-en")
    xlsx, output = _decide(tmp_path, result, inp, "RUN-1", {"PC12": {"Decision": "APPROVE_VARIANT"}})
    report = import_finding_decisions(job, xlsx, output, lock_path=tmp_path / "lock", source_corpus_sha256="a" * 64,
                                      target_language="en")
    assert report.imported == 0 and "PC12 is a possible addition" in report.problems[0]
    xlsx, output = _decide(tmp_path, result, inp, "RUN-1", {"PC12": {"Decision": "DISMISS"}})
    import_finding_decisions(job, xlsx, output, lock_path=tmp_path / "lock", source_corpus_sha256="a" * 64,
                             target_language="en")
    assert current_finding_decisions(job.root) == {finding["finding_id"]: "DISMISS"}
    inp.decisions = current_finding_decisions(job.root)
    again = run_check(inp, qualify=False)
    assert next(f for f in again.findings if f["finding_id"] == finding["finding_id"])["review_status"] == "DISMISSED"
