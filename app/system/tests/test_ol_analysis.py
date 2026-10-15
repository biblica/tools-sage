"""Pinned MACULA analysis package and deterministic checks of model claims about original-language words."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sage.errors import ValidationError
from sage.ol_analysis import check_ol_words, load_ol_analysis, make_ol_checker, ol_words_schema
from sage.stc import validate_stc_submission

APP_ROOT = Path(__file__).resolve().parents[2]
PARSE = {field: None for field in ("pos", "type", "tense", "voice", "mood", "stem", "person", "number", "gender", "case", "state")}


def _claim(surface: str, lemma: str, **fields: str) -> dict:
    """One ol_words entry as a provider returns it: every parse field present, unused ones null."""
    return {"surface": surface, "lemma": lemma, **PARSE, **fields}


def test_package_is_pinned_and_checks_hebrew_and_greek_claims() -> None:
    """VERIFIED for a correct parse, MISMATCH naming MACULA's value, NOT_FOUND for a word not in the verse."""
    analysis = load_ol_analysis(APP_ROOT)
    assert analysis is not None and analysis.package_id == "SAGE_OL_ANALYSIS_2026-10-15"
    checks = check_ol_words(analysis, "HEB", ["GEN 1:1"], [
        _claim("בָּרָא", "ברא", stem="qal", type="qatal", person="third"),
        _claim("בָּרָא", "ברא", stem="piel"),
        _claim("בְּרֵאשִׁית", "רֵאשִׁית"),  # quoted with its prefix segment
        _claim("שָׁלוֹם", "שָׁלוֹם"),
    ])
    assert [check["status"] for check in checks] == ["VERIFIED", "MISMATCH", "VERIFIED", "NOT_FOUND"]
    assert checks[1]["differences"] == {"stem": {"claimed": "piel", "macula": "qal"}}
    assert checks[0]["macula"]["gloss"] == "created"
    greek = check_ol_words(analysis, "GRK", ["JHN 1:14"], [
        _claim("ἐγένετο", "γίνομαι", tense="aorist", mood="indicative"),
        _claim("λόγος", "λέγω"),
    ])
    assert [check["status"] for check in greek] == ["VERIFIED", "MISMATCH"]
    assert greek[1]["differences"]["lemma"]["macula"] == "λόγος"


def test_schema_offers_macula_vocabularies() -> None:
    """The ol_words schema constrains each parse field to MACULA's own values."""
    analysis = load_ol_analysis(APP_ROOT)
    schema = ol_words_schema(analysis, "HEB")
    stem = schema["items"]["properties"]["stem"]
    assert "qal" in stem["enum"] and "piel" in stem["enum"] and None in stem["enum"]
    assert "wayyiqtol" in schema["items"]["properties"]["type"]["enum"]


def test_tampered_package_degrades_to_not_checked(tmp_path: Path) -> None:
    """A package that fails its checksum never blocks: claims come back NOT_CHECKED with the reason."""
    root = tmp_path / "app"
    (root / "system/config").mkdir(parents=True)
    shutil.copy2(APP_ROOT / "system/config/ol-analysis-reference.json", root / "system/config/ol-analysis-reference.json")
    shutil.copytree(APP_ROOT / "system/resources/ol-analysis", root / "system/resources/ol-analysis")
    manifest = next((root / "system/resources/ol-analysis").glob("*/MANIFEST.json"))
    manifest.write_text(manifest.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValidationError) as caught:
        load_ol_analysis(root)
    assert caught.value.code == "OL_ANALYSIS_INTEGRITY"
    checker, package_id = make_ol_checker(root, "GEN")
    assert package_id is None
    result = checker([_claim("בָּרָא", "ברא")], "GEN 1:1")
    assert result[0]["status"] == "NOT_CHECKED" and "unavailable" in result[0]["reason"]


def test_stc_finding_with_a_contradicted_parse_is_kept_and_flagged(tmp_path: Path) -> None:
    """STC keeps the finding, records MACULA's checks, and flags OL_CLAIM_UNVERIFIED on a mismatch."""
    output = tmp_path / "findings.json"
    finding = {
        "category": "VARIATION",
        "target_reference": "GEN 1:1",
        "summary": "The verb is rendered as an ongoing action.",
        "wip_evidence": "In the beginning God was creating",
        "ol_evidence": "בָּרָא",
    }
    output.write_text(json.dumps({
        "review_summary": "Reviewed GEN 1:1.",
        "report_language": "en",
        "findings": [
            {**finding, "ol_words": [_claim("בָּרָא", "ברא", stem="piel")]},
            {**finding, "category": "OMISSION", "ol_words": [_claim("בָּרָא", "ברא", stem="qal")]},
        ],
    }), encoding="utf-8")
    checker, _ = make_ol_checker(APP_ROOT, "GEN")
    result = validate_stc_submission(
        output, task_id="T", work_unit_id="U", scope_value="GEN 1:1", expected_references=["GEN 1:1"],
        authority_family="HEB", task_fingerprint="F", narrative_language="en", ol_checker=checker,
    )
    flagged, verified = result["findings"]
    assert flagged["ol_analysis_verified"] is False and flagged["ol_word_checks"][0]["status"] == "MISMATCH"
    assert verified["ol_analysis_verified"] is True
    records = [row for row in result["salvage_records"] if row["code"] == "OL_CLAIM_UNVERIFIED"]
    assert len(records) == 1 and "stem piel (MACULA: qal)" in records[0]["message"]


def test_rtc_ol_resolution_carries_macula_checks_and_flags_a_mismatch(tmp_path: Path) -> None:
    """A selective-OL resolution keeps its MACULA checks, and a contradicted lemma is flagged."""
    from sage.act_outputs import validate_analysis_findings

    request = {"request_id": "OLR-A1", "target_reference": "MAT 1:1", "deferred_finding_id": "OL-F-001"}
    document = {
        "schema_version": "2.0",
        "narrative_language": {"tag": "en", "authority": "CANONICAL_REPORT_NARRATIVE"},
        "task_id": "rtc-ol", "operation": "rtc", "stage": "SELECTIVE_OL_ADJUDICATION", "scope": "MAT 1:1",
        "focus": None, "check_type": None,
        "coverage": {"status": "COMPLETE", "reviewed_references": ["MAT 1:1"]},
        "review_receipts": [{
            "receipt_id": "R-1", "work_unit_id": "WU-1", "task_fingerprint": "F",
            "reviewed_references": ["MAT 1:1"], "checks_performed": ["OL_ADJUDICATION"],
            "evidence_summary": "Checked the inherited request against the Greek.",
        }],
        "structural_adjudications": [],
        "ol_resolutions": [{
            "request_id": "OLR-A1", "target_reference": "MAT 1:1", "outcome": "NO_FINDING",
            "decision": "BOTH_DEFENSIBLE", "finding_id": None,
            "original_language_evidence": "βίβλος γενέσεως",
            "ol_words": [_claim("Βίβλος", "βιβλίον", case="nominative")],
            "rationale": "Both renderings are defensible.",
        }],
        "findings": [],
    }
    output = tmp_path / "findings.json"
    output.write_text(json.dumps(document), encoding="utf-8")
    checker, _ = make_ol_checker(APP_ROOT, "MAT")
    result = validate_analysis_findings(
        output, task_id="rtc-ol", operation="rtc", rtc_stage="SELECTIVE_OL_ADJUDICATION", scope_value="MAT 1:1",
        focus=None, check_type=None, expected_references=["MAT 1:1"], structural_candidate_ids=[],
        grammar_rule_ids=[], allowed_evidence_ids=["WIP", "REFERENCE", "ORIGINAL_LANGUAGE_GREEK"],
        task_fingerprint="F", required_review_checks=["OL_ADJUDICATION"], expected_work_unit_ids=["WU-1"],
        expected_ol_request_ids=["OLR-A1"], expected_ol_requests=[request], narrative_language="en",
        workflow="rtc", ol_checker=checker,
    )
    resolution = result["ol_resolutions"][0]
    assert resolution["ol_analysis_verified"] is False
    assert resolution["ol_word_checks"][0]["differences"]["lemma"] == {"claimed": "βιβλίον", "macula": "βίβλος"}
    assert [row["code"] for row in result["salvage_records"]] == ["OL_CLAIM_UNVERIFIED"]
    from sage.act_outputs import _render_ol_resolutions

    report = "\n".join(_render_ol_resolutions({"ol_resolutions": [resolution], "narrative_language": {"tag": "en"}}))
    assert "MACULA does not support `Βίβλος`: lemma βιβλίον (MACULA: βίβλος)" in report
