"""Deterministic candidates the model adjudicates in RTC and STC."""

from __future__ import annotations

from sage.candidates import candidate_inventory, reconcile_adjudications


def _inventory() -> list[dict]:
    """Return one marker, one number, and one length candidate."""
    return candidate_inventory(
        markers=[{"target_reference": "MAT 1:2", "marker": "nd", "wip_count": 0, "reference_count": 1}],
        numeric={
            "rows": [
                {"reference": "MAT 1:3", "status": "MATCH", "index_values": ["3"], "wip_digit_values": ["3"]},
                {"reference": "MAT 1:4", "status": "DIFFERS", "index_values": ["12"], "wip_digit_values": ["11"]},
            ]
        },
        lengths=[{"wip_reference": "MAT 1:5", "direction": "SHORT", "relative_length": 0.3}],
    )


def test_inventory_skips_matching_numbers_and_gives_stable_ids() -> None:
    """MATCH rows need no adjudication; every other difference gets one stable candidate ID."""
    assert [row["candidate_id"] for row in _inventory()] == ["MC-MAT1:2-nd", "NC-MAT1:4", "LC-MAT1:5"]


def test_reconcile_corrects_unreported_confirms_and_records_missing_verdicts() -> None:
    """A CONFIRM must point at a reported finding; unknown IDs drop; silence becomes UNSURE."""
    rows, records = reconcile_adjudications(
        [
            {"candidate_id": "MC-MAT1:2-nd", "verdict": "CONFIRM", "finding_id": "F001", "rationale": "Divine name lost."},
            {"candidate_id": "NC-MAT1:4", "verdict": "CONFIRM", "finding_id": "F999", "rationale": "Wrong count."},
            {"candidate_id": "XX", "verdict": "REJECT", "finding_id": None, "rationale": ""},
        ],
        _inventory(),
        {"F001"},
        code_prefix="RTC",
    )
    assert [(row["candidate_id"], row["verdict"], row["finding_id"]) for row in rows] == [
        ("MC-MAT1:2-nd", "CONFIRM", "F001"),
        ("NC-MAT1:4", "UNSURE", None),
        ("LC-MAT1:5", "UNSURE", None),
    ]
    assert [row["code"] for row in records] == [
        "RTC_CANDIDATE_CONFIRM_UNREPORTED",
        "RTC_CANDIDATE_ADJUDICATION_DROPPED",
        "RTC_CANDIDATE_NOT_ADJUDICATED",
    ]


def test_stc_schema_requires_one_adjudication_per_candidate() -> None:
    """The STC response schema lists the unit's candidate IDs."""
    from sage.llm_tasks import _stc_findings_file_schema

    schema = _stc_findings_file_schema(
        {
            "expected_references": ["MAT 1:5"],
            "narrative_language": {"tag": "en", "authority": "CANONICAL_REPORT_NARRATIVE"},
            "deterministic_candidates": _inventory(),
        }
    )
    assert "candidate_adjudications" in schema["required"]
    item = schema["properties"]["candidate_adjudications"]["items"]
    assert item["properties"]["candidate_id"]["enum"] == ["MC-MAT1:2-nd", "NC-MAT1:4", "LC-MAT1:5"]
