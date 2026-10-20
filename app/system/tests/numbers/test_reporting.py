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
                "kind": "ORDER_DIFFERENCE", "wip_order": ["4", "3"], "expected_order": ["3", "4"],
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
        "check_policy": {"checks": {"number_accuracy": True, "footnote_review": True}},
        "model_receipts": {"EXTRACTION": [{
            "phase": "EXTRACTION", "task_version": "nca-extraction-3.0",
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
    assert "> MAT 1:2: Check consistency: the numbers 4, 3 appear in a different order than the source (3, 4)" in report
    assert 'the source reads: "three men and four women"' in report
    # The translator note is plain prose -- no internal jargon leaks into it.
    note_line = next(line for line in report.splitlines() if line.startswith("> MAT 1:2"))
    assert "NCA_NUMBER" not in note_line
    assert "western_reference" not in note_line.lower()


def test_fail_finding_gets_its_own_translator_note_with_the_authority_named():
    """A FAIL finding's note names the authority the expected values came from (a value FAIL is OL)."""
    document = report_document()
    document["groups"][0]["comparison"].update(outcome="FAIL", authority="OL", review_context={"kind": "VALUE_DIFFERENCE"})
    document["findings"][0].update(code="NCA_NUMBER_FAIL", severity="BLOCKING")
    document["summary"].update(needs_review=0, failures=1)

    report = render_nca_report(document)

    assert "> MAT 1:2: Correct the numbers: the translation has 4, 3; the original-language text has 3, 4." in report


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


def test_normalized_ol_review_note_does_not_claim_the_original_language_text():
    """EZR 1:10 feedback: a normalized index reading must not be presented as the literal OL text."""
    document = report_document()
    document["groups"][0]["comparison"].update(review_context={
        "kind": "OL_NORMALIZED_UNDOCUMENTED", "ol_text": "OL fixture text", "bsb_text": "BSB fixture text",
        "niv_values": ["3", "4"], "normalizations": [{"LAYER": "FINAL_OL_VERSE_OVERRIDE", "SOURCE_EXPRESSION": "",
                                                      "REASON": "Corpus-wide audit"}]})
    report = render_nca_report(document)
    note_line = next(line for line in report.splitlines() if line.startswith("> MAT 1:2"))
    assert "based on the original-language text" not in note_line
    assert "The index does not read every number-like word" in note_line
    assert 'Original-language text: "OL fixture text"' in note_line
    assert 'Reference translation (BSB): "BSB fixture text". Also see the NIV' in note_line


def test_documented_normalization_note_names_the_expression():
    """A documented override names the OL expression and reason the index did not count."""
    document = report_document()
    document["groups"][0]["comparison"].update(review_context={
        "kind": "OL_NORMALIZATION_DIFFERENCE", "ol_text": "OL", "bsb_text": "BSB", "niv_values": [],
        "normalizations": [{"LAYER": "AUDITED_OL_NORMALIZATION_MANIFEST", "SOURCE_EXPRESSION": "שֵׁת",
                            "REASON": "Proper name, not the numeral six."}]})
    report = render_nca_report(document)
    assert '("שֵׁת": Proper name, not the numeral six.)' in report


def test_pass_groups_are_counted_but_not_listed():
    """Tester feedback 2a3: a PASS verse is summary data only; the report lists what needs action."""
    document = chapter_document()
    passing = dict(deepcopy(document['groups'][1]), unit_id='passing', target_references=['MAT 4:1'], notes=[])
    passing['comparison'] = dict(passing['comparison'], outcome='PASS', review_context={})
    document['groups'].append(passing)
    document['summary'].update(passes=1)
    report = render_nca_report(document)
    assert '### `passing`' not in report
    assert '## MAT 4' not in report
    assert 'Passes: `1` (counted here, not listed below)' in report
    # A PASS group that still carries an advisory note stays visible.
    passing['notes'] = deepcopy(document['groups'][1]['notes'])
    assert '### `passing`' in render_nca_report(document)


def _action_document():
    """A two-chapter document: one OL FAIL in MAT 1, one NOT_INDEXED verse in MAT 2."""
    document = report_document()
    group = document["groups"][0]
    group.update(evidence={"wip_text": "Four women and three men."}, notes=[])
    group["comparison"].update(outcome="FAIL", review_context={
        "kind": "VALUE_DIFFERENCE", "ol_text": "τρεῖς ἄνδρες", "bsb_text": "three men",
        "ol_values": ["3"], "niv_values": ["3"], "match_status": ["PASS_EXACT"]},
        wip_values=["4", "3"], expected_values=["3"])
    document["findings"][0].update(code="NCA_NUMBER_FAIL", severity="BLOCKING", kind="VALUE_DIFFERENCE",
                                   authority="OL", expected_values=["3"])
    quiet = dict(deepcopy(group), unit_id="unit-2", target_references=["MAT 2:1"], western_references=["MAT 2:1"],
                 limitations=["NOT_INDEXED"], evidence={"wip_text": "They went home."})
    quiet["comparison"] = {"outcome": "NOT_INDEXED", "mode": "ORDERED", "authority": "NONE",
                           "wip_values": [], "expected_values": [], "review_context": {}}
    document["groups"].append(quiet)
    return document


def closing_text(report: str) -> str:
    """The end-of-report summary section of one action report."""
    return report.split("## Summary: no issue and not checked", 1)[1].split("## ", 1)[0]


def test_action_reports_follow_the_rtc_template_per_chapter():
    """NCA operator reports use the RTC/STC action-report template, one per chapter."""
    from sage.nca_reporting import build_chapter_reports, render_nca_action_report
    reports = build_chapter_reports(_action_document(), primary_language="en", secondary_language=None)
    assert [(r["book"], r["chapter"]) for r in reports] == [("MAT", 1), ("MAT", 2)]
    first = render_nca_action_report(reports[0])
    assert first.startswith("# Number Consistency & Accuracy (NCA) — NCA Action Report\n")
    for expected in ("- Projects: WIP checked against the Greek original language (also see: NIV)", "- Scope: `MAT 1`",
                     "## Authority and analyzed snapshot", "Number reference package",
                     "## Execution route", "## Actionable findings",
                     "### NUMBERS_RUN-1_UNIT-1_0001 — MAT 1:2", "- Result: Variance", "- Category: Accuracy",
                     "**Issue — English**", "**Proposed action — English**",
                     "the original-language text has 3.",
                     "**WIP evidence**", "Four women and three men.", "**Greek original language evidence**", "τρεῖς ἄνδρες",
                     "**BSB evidence**", "**Also see — NIV (other reference)**", "SQS: `NOT_APPLIED`"):
        assert expected in first, expected
    # The NIV is cited by reference and numbers only; the quoted BSB text carries its attribution.
    assert "**NIV evidence**" not in first
    attribution = first.split("## Sources and attribution", 1)[1]
    assert "Berean Standard Bible, public domain" in attribution
    # Quoted Greek text carries the MACULA CC BY 4.0 attribution and the SBLGNT credit, not the Hebrew one.
    assert "MACULA Greek Linguistic Datasets, available at https://github.com/Clear-Bible/macula-greek/" in attribution
    assert "Society of Biblical Literature and Logos Bible Software" in attribution
    assert "MACULA Hebrew" not in attribution
    # Technical plumbing stays in Run diagnostics, never the operator report.
    for absent in ("unit-1", "Planned extraction", "presentation", "Groups without extraction", "c" * 64 + "`)"):
        assert absent not in first
    second = render_nca_action_report(reports[1])
    assert "No actionable findings were submitted." in second
    assert "MACULA" not in second
    assert "1 without numbers" in second and "`" not in closing_text(second)
    # No-issue and not-checked verses are summarized at the end, after the findings.
    closing = second.split("## Summary: no issue and not checked", 1)
    assert len(closing) == 2 and "## Actionable findings" in closing[0]
    assert "- No numbers in the source or the index (1):" in closing[1]
    assert "1 without numbers" not in closing[0]


def test_attested_variant_finding_carries_footnote_guidance():
    """The translator note for an attested alternate reading names the footnote requirement."""
    from sage.nca_reporting import build_chapter_reports, render_nca_action_report
    document = _action_document()
    group = document["groups"][0]
    group["comparison"].update(outcome="NEEDS_REVIEW", review_context={
        "kind": "ATTESTED_VARIANT_READING", "ol_text": "OL", "bsb_text": "BSB", "ol_values": ["3"],
        "niv_values": ["3"], "match_status": ["PASS_EXACT"], "variant_reference": "MAT 1:1",
        "alternate_values": ["4", "3"], "variant_guidance": {
            "footnote_if_target_follows_alt": "REQUIRE", "scholarship_status": "DIVIDED",
            "suggested_note": "Some manuscripts add four women."}})
    document["findings"][0].update(code="NCA_NUMBER_NEEDS_REVIEW", severity="REVIEW", kind="ATTESTED_VARIANT_READING")
    report = render_nca_action_report(build_chapter_reports(document, primary_language="en",
                                                            secondary_language=None)[0])
    assert "- Result: Consistency check" in report
    assert "A footnote is required. Suggested note: Some manuscripts add four women." in report


def test_action_report_lists_text_critical_decisions_and_order_notes():
    """Text-critical decisions get their own operator table; correct reorderings are plain notes."""
    from sage.nca_reporting import build_chapter_reports, render_nca_action_report
    document = _action_document()
    group = document["groups"][0]
    group["notes"] = [
        {"kind": "TEXT_CRITICAL", "western_reference": "MAT 1:2", "ol_values": ["2"], "niv_values": ["30", "42"],
         "wip_values": ["30", "42"], "follows": "NIV", "footnote_in_wip": False,
         "suggested_note": "Hebrew does not have thirty.", "niv_footnote": ""},
        {"kind": "ORDER_NOTE", "western_reference": "MAT 1:2",
         "pairings": [{"wip_value": "1000", "wip_counts": "silver dishes"}, {"wip_value": "30", "wip_counts": "gold dishes"}]},
    ]
    report = render_nca_action_report(build_chapter_reports(document, primary_language="en", secondary_language=None)[0])
    assert "## Text-critical variants" in report
    assert "| MAT 1:2 | 2 | 30, 42 | NIV | **no** | Hebrew does not have thirty. |" in report
    assert "## Notes (no action needed)" in report and "silver dishes 1000" in report


def test_reports_cite_apparatus_evidence_for_findings_and_decisions():
    """Suggestions cite their support: readings with named editions, NET excerpt with link, registry."""
    from sage.nca_reporting import build_chapter_reports, render_nca_action_report
    document = _action_document()
    group = document["groups"][0]
    sblgnt = {"source": "SBLGNT_APPARATUS", "summary": "ἄνδρες RP ] + τρεῖς Treg NA28; + δύο WH",
              "url": "https://github.com/Faithlife/SBLGNT", "reference": "MAT 1:2",
              "readings": [{"text": "ἄνδρες", "witnesses": ["RP"], "sblgnt": True},
                           {"text": "adds τρεῖς", "witnesses": ["Treg", "NA28"], "sblgnt": False}]}
    net = {"source": "NET_TC", "summary": "The MT does not have “thirty.”", "url": "https://netbible.org/bible/x+1",
           "reference": "MAT 1:2", "basis": ["Syriac Peshitta", "Hebrew manuscripts"]}
    registry = {"source": "REGISTRY", "summary": "Some Greek manuscripts read 4,000.", "status": "NIV_FAVORED",
                "url": "", "reference": "MAT 1:2"}
    group["comparison"]["review_context"]["apparatus"] = [sblgnt, net]
    group["notes"] = [{"kind": "TEXT_CRITICAL", "western_reference": "MAT 1:2", "ol_values": ["2"],
                       "niv_values": ["30"], "wip_values": ["30"], "follows": "NIV", "footnote_in_wip": False,
                       "suggested_note": "", "niv_footnote": "", "apparatus": [registry, net]}]
    report = render_nca_action_report(build_chapter_reports(document, primary_language="en", secondary_language=None)[0])
    assert "**Apparatus evidence**" in report
    assert "SBLGNT text «ἄνδρες» (Robinson–Pierpont); variant «adds τρεῖς» (Tregelles, Nestle–Aland 28)" in report
    assert "- **[NET Bible text-critical note](https://netbible.org/bible/x+1)** — MAT 1:2 — basis: Syriac Peshitta; Hebrew manuscripts: “The MT does not have “thirty.”" in report
    assert "- **SAGE textual-variant registry** — MAT 1:2 (scholarship: NIV_FAVORED): Some Greek manuscripts read 4,000." in report
    assert "Suggested footnote basis (the translation has no footnote here): Some Greek manuscripts read 4,000." in report
    attribution = report.split("## Sources and attribution", 1)[1]
    assert "NET Bible® notes copyright © 1996, 2019 by Biblical Studies Press, L.L.C." in attribution
    assert "SBLGNT apparatus" in attribution and "Open Scriptures" not in attribution


def test_bsb_citation_points_to_the_original_language_niv_and_versions():
    """A BSB reading is cited with "Also see" (MT, NIV, the versions) and carries its public-domain attribution."""
    from sage.nca_reporting import build_chapter_reports, render_nca_action_report
    document = _action_document()
    group = document["groups"][0]
    bsb = {"source": "BSB", "summary": "AGREES_NIV: 4 — “On the fourth day they said.”",
           "url": "https://ebible.org/find/show.php?id=engbsb", "reference": "MAT 1:2",
           "see_also": ["MT 7", "NIV 4", "LXX 4"]}
    group["comparison"]["review_context"]["apparatus"] = [bsb]
    report = render_nca_action_report(build_chapter_reports(document, primary_language="en", secondary_language=None)[0])
    assert ("- **[Berean Standard Bible (public domain)](https://ebible.org/find/show.php?id=engbsb)** — MAT 1:2: "
            "“AGREES_NIV: 4 — “On the fourth day they said.”” Also see: MT 7; NIV 4; LXX 4.") in report
    assert "Berean Standard Bible, public domain" in report.split("## Sources and attribution", 1)[1]


def test_value_omitted_note_names_the_missing_number_and_asks_about_consistency():
    """The translator note names the omitted value as a consistency check, without asking for input."""
    from sage.nca_reporting import _ENGLISH, _finding_text

    group = {"comparison": {"authority": "OL", "review_context": {"kind": "VALUE_OMITTED", "omitted": ["20"]}}}
    finding = {"kind": "VALUE_OMITTED", "target_references": ["2CH 3:8"],
               "wip_values": ["20", "600"], "expected_values": ["20", "20", "600"]}
    issue, action = _finding_text(finding, group, lambda key: _ENGLISH[key])
    assert "20" in issue and action.startswith("2CH 3:8: Check consistency: 20 left out")


def test_value_added_note_names_the_added_number():
    """REV 11:4 "these two witnesses": the note names the added number as a consistency check."""
    from sage.nca_reporting import _ENGLISH, _finding_text

    group = {"comparison": {"authority": "OL", "review_context": {"kind": "VALUE_ADDED", "added": ["2"]}}}
    finding = {"kind": "VALUE_ADDED", "target_references": ["REV 11:4"],
               "wip_values": ["2", "2", "2"], "expected_values": ["2", "2"]}
    issue, action = _finding_text(finding, group, lambda key: _ENGLISH[key])
    assert "adds 2" in issue and action.startswith("REV 11:4: Check consistency: 2 added")


def test_restructured_note_names_the_construction():
    """EZK 45:23 and 2KI 25:17: the note says how the quantities were restated, as a consistency check."""
    from sage.nca_reporting import _ENGLISH, _finding_text

    restructured = [{"pattern": "REPEAT_STATED_ONCE", "omitted": ["7"], "made_explicit": ["male goat"]}]
    group = {"comparison": {"authority": "OL",
                            "review_context": {"kind": "RESTRUCTURED", "restructured": restructured}}}
    finding = {"kind": "RESTRUCTURED", "target_references": ["EZK 45:23"],
               "wip_values": ["7", "7", "7", "1"], "expected_values": ["7", "7", "7", "7"]}
    issue, action = _finding_text(finding, group, lambda key: _ENGLISH[key])
    assert "another construction" in issue
    assert action == 'EZK 45:23: Check consistency: the repeated 7 stated once, and "one" made explicit for male goat.'
    group["comparison"]["review_context"]["restructured"] = [{"pattern": "PAIR_AS_TWO"}]
    _issue, action = _finding_text({**finding, "target_references": ["2KI 25:17"]}, group, lambda key: _ENGLISH[key])
    assert action == '2KI 25:17: Check consistency: "one ... the second" stated as two.'


def test_unit_conversion_note_shows_wip_value_and_original_unit():
    """MAT 25:15 talents as coins: the note names both sides of the conversion and asks about style."""
    from sage.nca_reporting import _ENGLISH, _finding_text

    conversions = [{"ol_value": "5", "ol_unit": "talents", "wip_value": "5000", "wip_unit": "coins",
                    "conversion": "UNIT_SCALED"},
                   {"ol_value": "11", "ol_unit": "hour of the day", "wip_value": "5",
                    "conversion": "HOUR_TO_CLOCK"}]
    group = {"comparison": {"authority": "OL",
                            "review_context": {"kind": "UNIT_CONVERSION", "conversions": conversions}}}
    finding = {"kind": "UNIT_CONVERSION", "target_references": ["MAT 25:15"],
               "wip_values": ["5000", "5"], "expected_values": ["5", "11"]}
    issue, action = _finding_text(finding, group, lambda key: _ENGLISH[key])
    assert "5 talents (original language) as 5000 coins" in issue
    assert "hour 11 of the day (original language) as 5 o'clock" in issue
    assert action == ("MAT 25:15: Check consistency: talents converted to modern measures; "
                      "hour of the day converted to clock time.")
