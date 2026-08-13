"""Independent human-output language, materiality, and readable-log regressions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from sage_core.human_output import (
    LocalizedConsoleStream,
    OperationalLogger,
    parse_human_output,
    resolved_languages,
)
from sage_core.rewrite_risk import render_rewrite_challenge_report


def _run_cli(package_root: Path, workspace: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run one canonical command without writing Python bytecode into the fixture."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(package_root / "core")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "sage_core.cli",
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


def test_operational_logger_writes_canonical_and_readable_records(tmp_path: Path) -> None:
    """Verify one event produces canonical JSONL and concise bilingual text."""
    logger = OperationalLogger(root=tmp_path, spec=_spec(), mode="normal")
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
    assert report.count("TC-1") == 0
    assert report.count("3JN 1:4") == 1


def test_initialisation_report_uses_logs_and_reports_language_pair(
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
        workspace
        / "workspace-data"
        / "sage"
        / "output"
        / "initialization-report.md"
    ).read_text(encoding="utf-8")
    assert "Laporan inisialisasi ekosistem SAGE / SAGE ecosystem initialisation report" in report
    assert "Bahasa laporan / Report languages: `id/en`" in report


def test_auto_resolution_report_uses_logs_and_reports_channel(make_workspace) -> None:
    """Verify auto-resolution Markdown follows the operational language channel."""
    from sage_core.auto_resolution import render_auto_resolution_report, resolve_auto_settings
    from sage_core.registry import load_ecosystem

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

    from sage_core.guided_input import configure_prompt_renderer, prompt_for_value
    from sage_core.human_output import paired_catalogue_text

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
