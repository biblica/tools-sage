"""Independent human-output language, materiality, and readable-log regressions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage.act_outputs import render_action_report, render_operator_note_text
from sage.human_output import (
    LocalizedConsoleStream,
    OperationalLogger,
    parse_human_output,
    report_language_authority,
    render_report_language_authority,
    resolved_languages,
)
from sage.rewrite_risk import render_rewrite_challenge_report
from sage.storage import storage_layout


def _run_cli(package_root: Path, workspace: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run one canonical command without writing Python bytecode into the fixture."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(package_root / "system" / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "sage.cli",
            "--settings",
            str(workspace / "ecosystem.yml"),
            *arguments,
        ],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
        timeout=50,
    )


def _spec() -> object:
    """Return a fixture with different language order for the two human channels."""
    return parse_human_output(
        {
            "operator_language": "en",
            "logs_and_reports": {
                "primary_language": "en",
                "secondary_language": "id",
                "bilingual": True,
                "verbosity": "normal",
            },
            "translation_challenges": {
                "primary_language": "id",
                "secondary_language": "en",
                "bilingual": True,
                "minimum_individual_urgency": 2,
                "aggregate_lower_levels": True,
                "consolidate_repeated_cause": True,
                "render_only_material_fields": True,
            },
            "machine_records": {"language": "canonical", "localise_codes": False},
        }
    )


def test_language_channels_resolve_independently() -> None:
    """Verify operational and linguistic output can use different language order."""
    spec = _spec()
    assert resolved_languages(
        spec.logs_and_reports,
        operator_language=spec.operator_language,
        source_language="id",
        target_language="en",
    ) == ("en", "id")
    assert resolved_languages(
        spec.translation_challenges,
        operator_language=spec.operator_language,
        source_language="id",
        target_language="en",
    ) == ("id", "en")


def test_operator_language_policy_requires_manual_pilot_promotion() -> None:
    """Pilot-only tags remain unavailable until an advanced Operator adds a candidate."""
    default = parse_human_output({"operator_language": "en"})
    assert default.operator_language_policy.status("en") == "APPROVED"
    assert default.operator_language_policy.status("es") == "CANDIDATE"
    assert default.operator_language_policy.operational_priorities == ("id", "fr")
    assert default.operator_language_policy.status("sw") == "PILOT_ONLY"
    assert "sw" not in default.operator_language_policy.selectable()

    promoted = parse_human_output(
        {
            "operator_language": "sw",
            "operator_language_policy": {
                "approved": ["en"],
                "candidates": ["es", "sw"],
                "operational_priorities": ["sw"],
                "pilot_only": ["sw", "ha-Latn"],
            },
        }
    )
    assert promoted.operator_language_policy.status("sw") == "CANDIDATE"
    assert "sw" in promoted.operator_language_policy.selectable()


def test_bilingual_reports_declare_primary_authority_and_secondary_confidence() -> None:
    """A secondary rendering is visibly assistive and never silently co-authoritative."""
    spec = _spec()
    authority = report_language_authority(
        spec.logs_and_reports,
        operator_language=spec.operator_language,
    )
    assert authority == {
        "schema_version": "1.0",
        "primary_language": "en",
        "primary_authority": "GOVERNING_HUMAN_RENDERING",
        "primary_confidence": "BASELINE_NOT_CORRECTNESS_GUARANTEE",
        "secondary_language": "id",
        "secondary_authority": "ASSISTIVE_TRANSLATION_ONLY",
        "secondary_confidence": "LOWER_UNVERIFIED_TRANSLATION_CONFIDENCE",
        "secondary_generation_cost": "ADDITIONAL_MODEL_USAGE_AND_COMPILATION_TIME",
        "secondary_review_requirement": "GREATER_THAN_SINGLE_LANGUAGE_REPORT",
        "canonical_machine_evidence": "AUTHORITATIVE",
    }
    notice = render_report_language_authority(authority, markdown=True)
    assert "`en` is the governing Operator-language rendering" in notice
    assert "`id` is an assistive secondary translation" in notice
    assert "may contain ambiguity" in notice
    assert "adds model usage and report compilation time" in notice
    assert "more human review than a single-language report" in notice
    assert "Canonical machine records" in notice

    monolingual = parse_human_output({"operator_language": "en"})
    assert report_language_authority(
        monolingual.logs_and_reports,
        operator_language=monolingual.operator_language,
    ) is None

    document = {
        "task_id": "SAW-001",
        "operation": "qa",
        "stage": "COMPOSITE_FINALIZED",
        "scope": "GEN 1",
        "coverage": {"status": "COMPLETE", "reviewed_references": ["GEN 1:1"]},
        "findings": [],
        "language_authority": authority,
    }
    assert "assistive secondary translation" in render_action_report(document)
    assert "assistive secondary translation" in render_operator_note_text(document)


def test_operational_logger_writes_canonical_and_readable_records(tmp_path: Path) -> None:
    """Verify one event produces canonical JSONL and concise bilingual text."""
    app_root = tmp_path / "SAGE" / "app"
    app_root.mkdir(parents=True)
    logger = OperationalLogger(root=app_root, spec=_spec(), mode="normal")
    record = logger.emit(
        "REWRITE_COMPLETED",
        severity="SUCCESS",
        context={"task": "BIC-3JN-001", "challenges": 2},
        console=False,
    )
    assert record["event_code"] == "REWRITE_COMPLETED"
    json_record = json.loads(logger.path.read_text(encoding="utf-8").strip())
    assert json_record["event_code"] == "REWRITE_COMPLETED"
    assert "message" not in json_record
    human = logger.human_path.read_text(encoding="utf-8")
    assert "REWRITE completed / REWRITE selesai" in human
    assert "task=BIC-3JN-001" in human
    assert "challenges=2" in human


def test_translation_report_lists_material_and_aggregates_minor() -> None:
    """Verify bilingual challenge reports remain concise and count canonical records once."""
    document = {
        "task_id": "BIC-REWRITE-001",
        "operation": "rewrite",
        "scope": "3JN 1:1-15",
        "status": "STAGED_VALIDATED_WITH_CHALLENGES",
        "highest_urgency": 3,
        "reporting": {
            "material_challenge_ids": ["TC-1"],
            "automatic_resolution_ids": [],
            "minor_summary": {"total": 4, "by_category": {"REGISTER": 4}},
        },
        "challenges": [
            {
                "challenge_id": "TC-1",
                "scripture_reference": "3JN 1:4",
                "category": "VERB_CHOICE",
                "selected_candidate_id": "REMAIN",
                "recommended_candidate_id": "REMAIN",
                "consolidation_key": "3JN-REMAIN",
                "candidates": [
                    {"candidate_id": "REMAIN", "form": "remain"},
                    {"candidate_id": "ABIDE", "form": "abide"},
                ],
                "risk": {"before_ol": 3, "after_ol": 3, "urgency": 3},
                "ol_referral": {"evidence_summary": "Bounded evidence remains inconclusive."},
                "summary": "The candidates differ in relational force.",
                "recommended_action": "Carry the issue into SELF-CHECK.",
                "messages": {
                    "id": {
                        "summary": "Kandidat berbeda dalam daya relasional.",
                        "risk": "Pilihan dapat mengurangi unsur hubungan.",
                        "evidence": "Bukti terbatas belum menentukan satu pilihan.",
                        "action": "Bawa ke SELF-CHECK.",
                    },
                    "en": {
                        "summary": "The candidates differ in relational force.",
                        "risk": "The choice may weaken the relational component.",
                        "evidence": "The bounded evidence remains inconclusive.",
                        "action": "Carry into SELF-CHECK.",
                    },
                },
            }
        ],
    }
    report = render_rewrite_challenge_report(
        document,
        human_output=_spec(),
        source_language="id",
        target_language="en",
    )
    assert "Tantangan Terjemahan BIC / BIC Translation Challenges" in report
    assert "Pilihan / Selected: **remain**" in report
    assert "Hal minor digabungkan / Minor matters aggregated: `4`" in report
    assert "`en` is the governing Operator-language rendering" in report
    assert "`id` is an assistive secondary translation" in report
    assert report.count("TC-1") == 0
    assert report.count("3JN 1:4") == 1


def test_initialization_report_uses_logs_and_reports_language_pair(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify INIT reports follow the operational channel rather than challenge languages."""
    workspace = make_workspace(qualification_status="VALIDATED")
    settings_path = workspace / "ecosystem.yml"
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    settings["human_output"] = {
        "operator_language": "en",
        "logs_and_reports": {
            "primary_language": "id",
            "secondary_language": "en",
            "bilingual": True,
            "verbosity": "normal",
        },
        "translation_challenges": {
            "primary_language": "en",
            "secondary_language": "id",
            "bilingual": True,
            "minimum_individual_urgency": 2,
            "aggregate_lower_levels": True,
            "consolidate_repeated_cause": True,
            "render_only_material_fields": True,
        },
        "machine_records": {"language": "canonical", "localise_codes": False},
    }
    settings_path.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
    result = _run_cli(package_root, workspace, "workspace", "initialize")
    assert result.returncode == 0, result.stderr + result.stdout
    report = (
        storage_layout(workspace).reports_root
        / "initialization"
        / "initialization-report.md"
    ).read_text(encoding="utf-8")
    assert "Laporan inisialisasi ekosistem SAGE / SAGE ecosystem initialization report" in report
    assert "Bahasa laporan / Report languages: `id/en`" in report


def test_auto_resolution_report_uses_logs_and_reports_channel(make_workspace) -> None:
    """Verify auto-resolution Markdown follows the operational language channel."""
    from sage.auto_resolution import render_auto_resolution_report, resolve_auto_settings
    from sage.registry import load_ecosystem

    workspace = make_workspace(qualification_status="VALIDATED")
    settings_path = workspace / "ecosystem.yml"
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    settings["human_output"] = {
        "operator_language": "en",
        "logs_and_reports": {
            "primary_language": "id",
            "secondary_language": "en",
            "bilingual": True,
            "verbosity": "normal",
        },
        "translation_challenges": {
            "primary_language": "en",
            "secondary_language": "id",
            "bilingual": True,
            "minimum_individual_urgency": 2,
            "aggregate_lower_levels": True,
            "consolidate_repeated_cause": True,
            "render_only_material_fields": True,
        },
        "machine_records": {"language": "canonical", "localise_codes": False},
    }
    settings_path.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
    config = load_ecosystem(settings_path)
    report = render_auto_resolution_report(config, resolve_auto_settings(config))
    assert "Laporan penyelesaian otomatis SAGE / SAGE auto-resolution report" in report
    assert "Bahasa laporan / Report languages: id, en" in report


def test_guided_prompt_uses_logs_and_reports_channel() -> None:
    """Verify guided correction text uses the operational channel, not challenge text."""
    import io

    from sage.guided_input import configure_prompt_renderer, prompt_for_value
    from sage.human_output import paired_catalogue_text

    spec = _spec()
    configure_prompt_renderer(
        lambda key: paired_catalogue_text(
            spec.logs_and_reports,
            key,
            operator_language=spec.operator_language,
        )
    )
    output = io.StringIO()
    value = prompt_for_value(
        label="Book code / Kode kitab",
        input_stream=io.StringIO("JHN\n"),
        output_stream=output,
    )
    assert value == "JHN"
    assert "is required." in output.getvalue()
    assert "wajib diisi." in output.getvalue()


def test_console_report_stream_localises_recognised_lines() -> None:
    """Verify fixed-English command summaries follow the logs/reports language pair."""
    import io

    output = io.StringIO()
    stream = LocalizedConsoleStream(output, spec=_spec())
    print("SAGE STATUS", file=stream)
    print("State: READY", file=stream)
    print("3JN 1:4", file=stream)
    stream.flush()
    rendered = output.getvalue()
    assert "SAGE status / Status SAGE" in rendered
    assert "State: READY / Status: READY" in rendered
    assert "3JN 1:4" in rendered


def test_status_console_uses_configured_report_language_order(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify command summaries use the configured report channel without changing codes."""
    workspace = make_workspace(qualification_status="VALIDATED")
    settings_path = workspace / "ecosystem.yml"
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    settings["human_output"] = {
        "operator_language": "en",
        "logs_and_reports": {
            "primary_language": "id",
            "secondary_language": "en",
            "bilingual": True,
            "verbosity": "normal",
        },
        "translation_challenges": {
            "primary_language": "id",
            "secondary_language": "en",
            "bilingual": True,
            "minimum_individual_urgency": 2,
            "aggregate_lower_levels": True,
            "consolidate_repeated_cause": True,
            "render_only_material_fields": True,
        },
        "machine_records": {"language": "canonical", "localise_codes": False},
    }
    settings_path.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
    result = _run_cli(package_root, workspace, "workspace", "status")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "Status SAGE / SAGE status" in result.stdout
    assert "Status: NOT_RUN / State: NOT_RUN" in result.stdout


def test_action_report_renders_nonblocking_versification_advisories() -> None:
    """SAW Action Report must retain VRS differences that were advisory at preflight."""
    document = {
        "task_id": "SAW-DAN-001",
        "operation": "qa",
        "stage": "COMPOSITE_FINALIZED",
        "scope": "DAN",
        "coverage": {"status": "COMPLETE", "reviewed_references": ["DAN 3:30", "DAN 4:1"]},
        "findings": [],
        "versification_advisories": [
            {
                "scope": "DAN 3:27-4:1",
                "role": "SAW REFERENCE",
                "project_id": "usNASB",
                "code": "EXPECTED_COORDINATE_MISSING",
                "reference": "DAN 3:31",
                "message": "Coordinate is expected by the effective VRS and is not covered by a verse marker or bridge.",
                "effective_vrs": "org.vrs",
                "default_vrs": "eng.vrs",
            }
        ],
    }
    report = render_action_report(document)
    assert "## Versification advisories" in report
    assert "did not block SAW execution" in report
    assert "DAN 3:31" in report
    assert "usNASB" in report


def test_saw_action_report_uses_compact_project_ids_and_omits_empty_ol_metadata() -> None:
    """Finding prose resolves bare roles to Project IDs and never prints synthetic OL filler."""
    document = {
        "task_id": "SAW-DAN-001",
        "job_id": "SAW_fixture",
        "operation": "qa",
        "stage": "COMPOSITE_FINALIZED",
        "scope": "DAN 1",
        "resource_bindings": {"WIP": "ukrNPUv1", "REFERENCE": "usNIVv2"},
        "resource_display_names": {"WIP": "Ukrainian NPU", "REFERENCE": "New International Version"},
        "coverage": {"status": "COMPLETE", "reviewed_references": ["DAN 1:1"]},
        "findings": [{
            "finding_id": "F-1",
            "target_reference": "DAN 1:1",
            "category": "MEANING",
            "issue": "Compare WIP with REFERENCE.",
            "required_action": "Review WIP against REFERENCE.",
            "action_level": "REVIEW",
            "confidence": "MEDIUM",
            "evidence_ids": ["WIP", "REFERENCE"],
            "grammar_rule_ids": [],
            "original_language_evidence": "",
        }],
    }
    rendered = render_action_report(document)
    assert "`Ukrainian NPU` checked against `New International Version`" in rendered
    assert "Compare ukrNPUv1 with usNIVv2." in rendered
    assert "Evidence: `ukrNPUv1, usNIVv2`" in rendered
    assert "Original-language:" not in rendered
    assert "NOT CONSULTED" not in rendered


@pytest.mark.parametrize(
    ("ol_role", "ol_resource"),
    (("ORIGINAL_LANGUAGE_HEBREW", "HEB"), ("ORIGINAL_LANGUAGE_GREEK", "GRK")),
)
def test_saw_action_report_resolves_source_to_the_routed_ol_resource(
    ol_role: str,
    ol_resource: str,
) -> None:
    """Bare source wording names HEB/GRK OL rather than leaving its authority ambiguous."""
    document = {
        "scope": "EXO 2",
        "resource_bindings": {
            "WIP": "faTMNv4",
            "REFERENCE": "usNIVv2",
            ol_role: ol_resource,
        },
        "coverage": {"status": "COMPLETE", "reviewed_references": ["EXO 2:3"]},
        "findings": [{
            "finding_id": "F-HEB-1",
            "target_reference": "EXO 2:3",
            "category": "MEANING",
            "issue": "WIP adds a purpose not stated in the source or the reference.",
            "required_action": "Align WIP with the source.",
            "action_level": "CHANGE",
            "confidence": "HIGH",
            "evidence_ids": ["WIP", "REFERENCE", ol_role],
            "grammar_rule_ids": [],
            "original_language_evidence": "The source has two coating expressions.",
        }],
    }

    rendered = render_action_report(document)

    assert f"faTMNv4 adds a purpose not stated in the {ol_resource} OL or the usNIVv2." in rendered
    assert f"Align faTMNv4 with the {ol_resource} OL." in rendered
    assert f"Evidence: `faTMNv4, usNIVv2, {ol_resource} OL`" in rendered
    assert f"Original-language: `The {ol_resource} OL has two coating expressions.`" in rendered
