"""Scoped, superseding, MACULA-anchored routing of BIC INSPECT challenges."""

from __future__ import annotations

import json
from pathlib import Path

from sage.bic_anchors import MAX_ROUTED_PER_VERSE, MAX_ROUTED_TOTAL, anchor_verse, ol_anchor, routed_challenges
from sage.bic_memory import submit_inspect_transactionally
from sage.llm_tasks import _conditional_requests
from sage.references import parse_scope, reference_overlaps_scope
from sage.rewrite_risk import render_rewrite_challenge_report

ROOT = Path(__file__).resolve().parents[2]
FINGERPRINTS = {"packet.contemporary_source": "a" * 64}


def _row(challenge_id: str, reference: str, *, job: str = "J", status: str = "OPEN", summary: str = "s") -> dict:
    """Build one stored INSPECT challenge with the bulky provenance real rows carry."""
    return {
        "challenge_id": challenge_id,
        "scripture_reference": reference,
        "challenge_type": "LEXICAL",
        "summary": summary,
        "recommended_action": "Review.",
        "bic_job_id": job,
        "status": status,
        "provenance": {"resource_fingerprints": {"x": "y" * 500}},
    }


def test_reference_overlap_handles_verses_ranges_chapters_and_books() -> None:
    """A challenge reference overlaps a scope when they share any coordinate."""
    scope = parse_scope("MRK 4:35-41")
    assert reference_overlaps_scope(scope, "MRK 4:39")
    assert reference_overlaps_scope(scope, "MRK 4:30-36")
    assert reference_overlaps_scope(scope, "MRK 4")
    assert reference_overlaps_scope(scope, "MRK")
    assert reference_overlaps_scope(parse_scope("MRK 4:35-5:2"), "MRK 5:1")
    assert not reference_overlaps_scope(scope, "MRK 4:42")
    assert not reference_overlaps_scope(scope, "MRK 5:1")
    assert not reference_overlaps_scope(scope, "MAT 4:39")
    assert not reference_overlaps_scope(scope, "not a reference")


def test_a_newer_inspect_supersedes_earlier_challenges_on_its_verses(tmp_path: Path) -> None:
    """Re-running INSPECT replaces the Job's challenges on the same verses; other verses stay current."""
    memory, transactions = tmp_path / "memory", tmp_path / "transactions"
    memory.mkdir()

    def inspect(operation_id: str, scope: str, references: list[str]) -> None:
        """Commit one INSPECT with one challenge per reference."""
        submit_inspect_transactionally(
            {
                "schema_version": "1.0",
                "operation_id": operation_id,
                "scope": scope,
                "resource_fingerprints": FINGERPRINTS,
                "proposals": [],
                "challenges": [
                    {"submitted_id": f"C{index}", "scripture_reference": reference, "challenge_type": "LEXICAL",
                     "summary": f"Challenge at {reference}", "recommended_action": "Review."}
                    for index, reference in enumerate(references, start=1)
                ],
            },
            memory_root=memory,
            transaction_root=transactions,
            bic_job_id="J",
        )

    inspect("op-1", "MRK 4:35-41", ["MRK 4:36", "MRK 4:39"])
    inspect("op-2", "MRK 1:40-45", ["MRK 1:43"])
    inspect("op-3", "MRK 4:35-41", ["MRK 4:39"])
    rows = json.loads((memory / "translation-challenges.json").read_text(encoding="utf-8"))
    status = {(row["operation_id"], row["scripture_reference"]): row["status"] for row in rows}
    assert status == {
        ("op-1", "MRK 4:36"): "SUPERSEDED",
        ("op-1", "MRK 4:39"): "SUPERSEDED",
        ("op-2", "MRK 1:43"): "OPEN",
        ("op-3", "MRK 4:39"): "OPEN",
    }
    assert {row["superseded_by"] for row in rows if row["status"] == "SUPERSEDED"} == {"op-3"}
    routed = routed_challenges(rows, parse_scope("MRK 4:35-41"), "J")
    assert [row["scripture_reference"] for row in routed] == ["MRK 4:39"]


def test_routed_challenges_keep_only_current_in_scope_rows_in_compact_form() -> None:
    """Out-of-scope, superseded, and other-Job challenges never reach the task; provenance is not routed."""
    rows = [
        _row("A", "MRK 4:39"),
        _row("B", "MRK 1:43"),
        _row("C", "MRK 4:39", status="SUPERSEDED"),
        _row("D", "MRK 4:40", job="OTHER"),
        _row("E", "MRK 4:38-39", summary="t"),
    ]
    routed = routed_challenges(rows, parse_scope("MRK 4:35-41"), "J")
    assert [row["challenge_id"] for row in routed] == ["E", "A"]
    assert set(routed[0]) == {"challenge_id", "scripture_reference", "challenge_type", "summary", "recommended_action"}


def test_routed_challenges_drop_duplicates_and_cap_per_verse_and_total() -> None:
    """The newest of duplicate challenges wins, and the caps bound the routed set."""
    rows = [_row(f"R{index}", "MRK 4:39", summary=f"distinct {index}") for index in range(6)]
    rows += [_row("DUP-OLD", "MRK 4:40", summary="Same wording"), _row("DUP-NEW", "MRK 4:40", summary="same  wording")]
    ids = [row["challenge_id"] for row in routed_challenges(rows, parse_scope("MRK 4"), "J")]
    assert ids[:MAX_ROUTED_PER_VERSE] == ["R5", "R4", "R3"]
    assert "DUP-NEW" in ids and "DUP-OLD" not in ids
    many = [_row(f"V{verse}-{index}", f"MRK 4:{verse}", summary=f"{verse}-{index}") for verse in range(1, 30) for index in range(2)]
    assert len(routed_challenges(many, parse_scope("MRK 4"), "J")) == MAX_ROUTED_TOTAL


def test_macula_anchor_merges_differently_worded_challenges_on_the_same_word() -> None:
    """Two challenges about the same original-language word in one verse route once."""
    rows = [
        _row("OLD", "MRK 4:39", summary="Whether he rebuked or warned the wind."),
        _row("NEW", "MRK 4:39", summary="The rebuke addressed to the wind needs its force kept."),
    ]
    routed = routed_challenges(rows, parse_scope("MRK 4:35-41"), "J", root=ROOT)
    assert [row["challenge_id"] for row in routed] == ["NEW"]


def test_anchor_follows_the_challenge_text_and_never_guesses_a_verse() -> None:
    """Anchors match the challenge's words to MACULA glosses; a range narrows only when its text decides."""
    words = ol_anchor(ROOT, "MRK 4:39", hint="He rebuked the wind")["words"]
    assert words[0]["lemma"] == "ἐπιτιμάω" and words[0]["strong"] == "2008"
    summary = "The severe warning in verse 43 introduces the commands in verse 44."
    assert anchor_verse(ROOT, "MRK 1:43-44", hint=summary) == "MRK 1:43"
    assert anchor_verse(ROOT, "MRK 1:43-44", hint="A sternly warned dismissal.") == "MRK 1:43"
    assert anchor_verse(ROOT, "MRK 1:40-44", hint="healing versus cleansing") is None
    assert ol_anchor(ROOT, "XYZ 1:1") is None


def test_ol_step_narrows_a_range_challenge_to_its_anchored_verse() -> None:
    """A range challenge gets a single-verse OL question when its text points to one verse."""
    raw = json.dumps({"challenges": [{
        "challenge_id": "CH-RANGE",
        "scripture_reference": "MRK 1:43-44",
        "category": "DISCOURSE_FUNCTION",
        "summary": "The severe warning in verse 43 introduces the commands in verse 44.",
        "risk": {"before_ol": 3, "material_triggers": ["DISCOURSE_DEPENDENCY"]},
        "ol_referral": {"performed": False},
    }]})
    files = {"output/translation-challenges.json": raw}
    [request] = _conditional_requests(files, anchor_verse=lambda reference, hint: anchor_verse(ROOT, reference, hint=hint))
    assert request["scripture_reference"] == "MRK 1:43"
    assert request["narrowed_from"] == "MRK 1:43-44"
    assert "unavailable_code" not in request


def test_challenge_report_names_the_anchored_word_with_macula_attribution() -> None:
    """A material challenge with an anchor shows its lemma, Strong's number, and gloss, credited to MACULA."""
    anchor = ol_anchor(ROOT, "MRK 4:39", hint="He rebuked the wind", limit=1)
    document = {
        "task_id": "T", "operation": "rewrite", "scope": "MRK 4:35-41", "status": "COMPLETED_WITH_CHALLENGES",
        "highest_urgency": 3,
        "reporting": {"material_challenge_ids": ["C1"], "minor_summary": {"total": 0, "by_category": {}, "notes": []}},
        "challenges": [{
            "challenge_id": "C1", "scripture_reference": "MRK 4:39", "category": "VERB_CHOICE",
            "summary": "Rebuke or warn.", "messages": {}, "selected_candidate_id": "A",
            "candidates": [{"candidate_id": "A", "form": "rebuked"}], "risk": {"urgency": 3},
            "ol_referral": {}, "recommended_action": "Keep rebuked.", "ol_anchor": anchor,
            "consolidation_key": "k", "human_reporting": {"material": True},
        }],
    }
    report = render_rewrite_challenge_report(document)
    assert "Original language (MACULA): MRK 4:39 ἐπιτιμάω (2008," in report
    assert "MACULA Greek Linguistic Datasets" in report and "CC BY 4.0" in report
