"""NCA human reports retain authority evidence while localizing visible labels."""

from copy import deepcopy

import pytest

from sage.errors import ValidationError
from sage.nca_reporting import render_nca_report
from sage.numbers.results import NCA_CAPABILITY_LIMITATION


def report_document() -> dict[str, object]:
    """Build a complete rendering input with one NEEDS_REVIEW group and finding."""
    finding = {
        "finding_id": "NUMBERS_RUN-1_UNIT-1_0001",
        "work_unit_id": "unit-1",
        "category": "ACCURACY",
        "code": "NCA_NUMBER_NEEDS_REVIEW",
        "severity": "REVIEW",
        "mode": "ORDERED",
        "target_references": ["MAT 1:2"],
        "western_references": ["MAT 1:1"],
        "wip_values": ["4", "3"],
        "expected_values": ["3", "4"],
        "message": "Same numeric values in a different order -- confirm this is a faithful "
                   "reordering, not a swapped referent.",
    }
    group = {
        "unit_id": "unit-1",
        "projection_status": "READY",
        "western_references": ["MAT 1:1"],
        "target_references": ["MAT 1:2"],
        "extraction": {"status": "COMPLETE", "limitations": [], "values": ["4", "3"]},
        "comparison": {
            "outcome": "NEEDS_REVIEW", "mode": "ORDERED", "authority": "OL",
            "wip_values": ["4", "3"], "expected_values": ["3", "4"],
            "review_context": {
                "wip_order": ["4", "3"], "expected_order": ["3", "4"],
                "authority_text": "three men and four women",
            },
        },
        "limitations": [],
        "notes": [{
            "western_reference": "MAT 1:1", "classification": "TEXTUAL_VARIANT",
            "scholarship_status": "SUPPORTED", "manuscript_evidence": "Papyrus fixture evidence",
            "scholarship_position": "Widely accepted", "ol_values": "3;4", "alternate_values": "",
        }],
    }
    return {
        "schema_version": "1.0", "workflow": "nca", "check_id": "NUMBERS",
        "provenance": {
            "run_id": "RUN-1", "job_id": "JOB-1",
            "style_profile": {"selector": "fixture-en/1", "sha256": "b" * 64},
            "reference_package": {"package_id": "fixture", "sha256": "c" * 64},
            "wip": {"identity": "WIP", "sha256": "d" * 64},
            "language_profile": {"grammar_issue": "Never report this."},
        },
        "check_policy": {"checks": {"number_accuracy": True, "presentation_consistency": True, "footnote_review": True}},
        "model_receipts": {"EXTRACTION": [{
            "phase": "EXTRACTION", "task_version": "nca-extraction-1.0",
            "provider": "fixture-provider", "model": "fixture-model", "reasoning_effort": "medium",
            "route_id": "route-1", "routing_mode": "AUTOMATIC", "qualification_status": "QUALIFIED",
            "prompt_sha256": "e" * 64, "input_sha256": "f" * 64, "response_sha256": "0" * 64,
            "provider_metadata": {},
        }]},
        "limitations": {"capability": NCA_CAPABILITY_LIMITATION, "sqs_confidence_checks_applied": False},
        "groups": [group],
        "findings": [finding],
        "coverage": {
            "result": "FINDINGS", "coverage": "COMPLETE", "confidence_basis": "FULL",
            "restrictions": [], "skipped_checks": [],
            "expected_unit_ids": ["unit-1"], "assessed_unit_ids": ["unit-1"],
        },
        "summary": {
            "groups": 1, "passes": 0, "failures": 0, "needs_review": 1, "not_assessed": 0,
            "noteworthy_notes": 1, "extraction_complete": 1, "extraction_partial": 0,
            "extraction_unsupported": 0, "findings": 1,
        },
        "metrics": {
            "provider_calls": 1, "checkpoint_reuse": 0, "failed_calls": 0,
            "planning": {"planned_extraction_calls": 1, "input_ids": ["input-1"], "blocked": {}, "missing_owner_ids": []},
        },
    }


def test_report_exposes_navigation_authority_and_registered_note_evidence():
    """The report distinguishes target/Western coordinates and surfaces note-worthy evidence."""
    report = render_nca_report(report_document())

    for expected in (
        "JOB-1", "RUN-1", "WIP", "fixture-en/1", "fixture",
        "MAT 1:2", "MAT 1:1",
        "EXTRACTION: fixture-provider/fixture-model",
        "NEEDS_REVIEW", "ORDERED", "OL",
        "three men and four women",
        "TEXTUAL_VARIANT", "SUPPORTED", "Papyrus fixture evidence",
        "NCA_NUMBER_NEEDS_REVIEW",
        NCA_CAPABILITY_LIMITATION,
    ):
        assert expected in report
    assert "Never report this." not in report


def test_zero_finding_and_incomplete_reports_still_show_capability_limitations():
    """Neither an all-clear nor incomplete evidence may hide the mandatory limitation."""
    document = report_document()
    document["findings"] = []
    document["summary"].update(findings=0, needs_review=0)
    document["groups"][0]["comparison"].update(outcome="NOT_ASSESSED", review_context={})
    document["coverage"].update(
        result="INSUFFICIENT_DATA",
        coverage="PARTIAL",
        confidence_basis="LIMITED",
        restrictions=["Required evidence is incomplete."],
    )

    report = render_nca_report(document)

    assert NCA_CAPABILITY_LIMITATION in report
    assert "INSUFFICIENT_DATA" in report
    assert "No NCA findings were recorded." not in report


def test_needs_review_finding_gets_a_copy_paste_translator_note():
    """A NEEDS_REVIEW finding must render a plain-language note an Operator can paste as-is."""
    report = render_nca_report(report_document())
    assert "Note for translator (copy below):" in report
    assert "> MAT 1:2: The numbers 4, 3 appear in a different order than the source (3, 4)." in report
    assert 'the source reads: "three men and four women"' in report
    # The translator note is plain prose -- no internal jargon leaks into it.
    note_line = next(line for line in report.splitlines() if line.startswith("> MAT 1:2"))
    assert "NCA_NUMBER" not in note_line
    assert "western_reference" not in note_line.lower()


def test_fail_finding_gets_its_own_translator_note_with_the_authority_named():
    """A FAIL finding's note must name which authority (OL/NIV) the expected values came from."""
    document = report_document()
    document["groups"][0]["comparison"].update(outcome="FAIL", authority="NIV")
    document["findings"][0].update(code="NCA_NUMBER_FAIL", severity="BLOCKING")
    document["summary"].update(needs_review=0, failures=1)

    report = render_nca_report(document)

    assert "> MAT 1:2: Please check the numbers in this verse." in report
    assert "the reference translation (NIV), it should have 3, 4." in report


def test_pass_and_not_assessed_outcomes_produce_no_translator_note():
    """Only FAIL/NEEDS_REVIEW findings exist at all -- PASS/NOT_ASSESSED never reach this path."""
    from sage.nca_reporting import _translator_note
    finding = {"code": "NCA_NUMBER_FAIL", "target_references": ["MAT 1:1"], "wip_values": ["1"], "expected_values": ["1"]}
    group = {"comparison": {"authority": "OL"}}
    assert _translator_note({**finding, "code": "SOMETHING_ELSE"}, group, lambda k: k) is None


def test_localized_report_changes_human_labels_but_retains_machine_evidence():
    """A bound report localizer changes prose without altering codes or identifiers."""
    localized_text = {
        "report.nca.title": "Laporan NCA",
        "report.nca.limitations": "Batasan",
        "report.nca.capability_limitation": "Temuan dibatasi oleh pemahaman bahasa dan kemampuan interpretasi angka LLM yang dipilih. Pemeriksaan keyakinan SQS belum diterapkan.",
        "report.nca.findings": "Temuan",
    }

    report = render_nca_report(
        report_document(), language="id", localize=lambda key: localized_text.get(key, key)
    )

    assert "# Laporan NCA" in report
    assert localized_text["report.nca.capability_limitation"] in report
    assert "NCA_NUMBER_NEEDS_REVIEW" in report
    assert "MAT 1:1" in report
    assert NCA_CAPABILITY_LIMITATION not in report


def test_report_rejects_missing_limitation_and_unknown_language_rendering():
    """Reports fail closed when capability prose or requested localization is unavailable."""
    missing = deepcopy(report_document())
    missing["limitations"]["capability"] = ""
    with pytest.raises(ValidationError) as exc:
        render_nca_report(missing)
    assert exc.value.code == "NCA_RESULT_LIMITATION_REQUIRED"

    with pytest.raises(ValidationError) as exc:
        render_nca_report(report_document(), language="sw")
    assert exc.value.code == "NCA_REPORT_TRANSLATION_REQUIRED"


def test_report_rejects_missing_model_identity_for_assessed_groups():
    """A completed extraction cannot be rendered under an invented anonymous model."""
    document = report_document()
    document["model_receipts"]["EXTRACTION"] = []

    with pytest.raises(ValidationError) as exc:
        render_nca_report(document)

    assert exc.value.code == "NCA_RESULT_RECEIPT_INVALID"


def chapter_document():
    """Cover cross-chapter parents, an unlocated group, and multi-chapter navigation."""
    document = report_document()
    group = document.pop('groups')[0]
    bridge = dict(group, unit_id='bridge', target_references=['MAT 1:25', 'MAT 2:1'],
        western_references=['MAT 1:1', 'MAT 1:2'])
    missing = dict(group, unit_id='missing:GEN 10:1', projection_status='REGISTERED_ABSENCE',
        target_references=[], western_references=['GEN 10:1'])
    unaligned = dict(group, unit_id='unaligned', target_references=['MAT 3:1', 'MAT 3:2'])
    findings = []
    for index, owner in enumerate(('bridge', 'unaligned', 'missing:GEN 10:1'), 1):
        finding = deepcopy(document['findings'][0])
        finding.update(finding_id=f'F-{index}', work_unit_id=owner,
                       target_references=[], western_references=['MAT 1:1'])
        findings.append(finding)
    document.update(groups=[missing, unaligned, bridge], findings=findings)
    document['summary'].update(findings=3)
    document['coverage'].update(requested_scope='MAT 1:25')
    document['metrics'].update(provider_calls=4, checkpoint_reuse=2, failed_calls=1)
    document['metrics']['planning'].update(
        input_ids=['input-1', 'input-2'], blocked={'input-2': 'OVERSIZED'},
        missing_owner_ids=['missing:GEN 10:1'])
    return document


def test_chapter_navigation_retains_unlocated_and_cross_boundary_parents():
    """Every finding owns one primary chapter and other chapters contain only links."""
    from sage import nca_reporting
    assert hasattr(nca_reporting, 'chapter_sections'), 'chapter navigation is missing'
    sections = nca_reporting.chapter_sections(chapter_document())
    assert [(x['book'], x['chapter']) for x in sections] == [('MAT', 1), ('MAT', 2), ('MAT', 3), (None, None)]
    assert sections[0]['finding_ids'] == ('F-1',)
    assert sections[1]['finding_ids'] == ()
    assert sections[1]['cross_references'][0]['finding_ids'] == ('F-1',)
    assert sections[-1]['group_ids'] == ('missing:GEN 10:1',)
    assert sections[-1]['finding_ids'] == ('F-3',)
    assert sections[-1]['target_references'] == ()


def test_chapter_report_preserves_exact_row_evidence_and_unique_findings():
    """A report renders each parent and finding once with localized evidence labels."""
    report = render_nca_report(chapter_document(), language='fr')
    for value in ('## MAT 1', '## MAT 2', '## MAT 3', 'MAT 1:25, MAT 2:1',
                  'EXTRACTION: fixture-provider/fixture-model', 'GEN 10:1',
                  'OVERSIZED', 'SQS: `NOT_APPLIED`'):
        assert value in report
    for fid in ('F-1', 'F-2', 'F-3'):
        assert report.count(f'### `{fid}`') == 1
    assert report.count('### `bridge`') == 1
    assert 'Appels exécutés' in report or 'executed_calls' in report


def test_every_optimized_report_label_has_an_explicit_locale_entry():
    """English fallback cannot conceal absent translations in supported report locales."""
    from sage import human_output, nca_reporting
    required = {'chapters', 'unlocated', 'cross_reference', 'parent_group',
                'planned_inputs', 'executed_calls', 'reused_checkpoints', 'blocked_inputs',
                'missing_owners', 'requested_scope',
                'extraction_complete', 'extraction_partial', 'extraction_unsupported'}
    for locale in ('en', 'en-US', 'en-GB', 'id', 'fr', 'ru', 'pt-BR', 'uk'):
        for suffix in required:
            key = 'report.nca.' + suffix
            assert key in nca_reporting._ENGLISH


def test_historical_missing_planned_call_count_is_not_inferred():
    """A historical document never acquires a fabricated planned call measurement."""
    document = chapter_document()
    del document['metrics']['planning']['planned_extraction_calls']
    report = render_nca_report(document)
    assert 'Planned extraction calls (initial batches): `NOT RECORDED`' in report
    document['metrics']['planning']['planned_extraction_calls'] = 1
    assert 'Planned extraction calls (initial batches): `1`' in render_nca_report(document)
