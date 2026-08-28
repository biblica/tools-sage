"""Universal SAGE linguistic-specificity policy regressions."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from sage.act_tasks import create_act_task, submit_act_task
from sage.evidence_policy import AUTHORITY_INTERPRETATION_RULES, READ_CLASSES, task_evidence_policy
from sage.registry import load_ecosystem


def _initialize(package_root: Path, root: Path) -> None:
    """Initialize one isolated fixture through the real controller."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "system" / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sage.cli",
            "--settings",
            str(root / "ecosystem.yml"),
            "workspace",
            "initialize",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def _profile_rows(task: dict) -> dict[str, dict]:
    """Index canonical linguistic-profile bindings by routed stream."""
    return {str(row["stream_id"]): row for row in task["linguistic_profile_bindings"]}


def test_every_governed_task_declares_canonical_linguistic_specificity() -> None:
    """Bounded model requests cannot infer canonical language/dialect/register from text."""
    for workflow in ("bic", "saw"):
        policy = task_evidence_policy(workflow)
        rule = policy["language_specificity"]
        assert rule["canonical_profiles_required"] is True
        assert rule["infer_language_from_text"] is False
        assert rule["profiles_are_sliced"] is False
        assert rule["sfm_budget_contribution"] == "NONE"
        assert rule["missing_or_ambiguous_profile"] == "FAIL_CLOSED"


def test_ol_authority_profile_has_dedicated_noncontent_read_class() -> None:
    """Historical OL identity rules are context, never additional Scripture evidence."""
    assert AUTHORITY_INTERPRETATION_RULES in READ_CLASSES


def test_default_report_language_has_explicit_canonical_profile_alias(package_root: Path) -> None:
    """The packaged bare-English Job default must resolve explicitly, not by model inference."""
    config = load_ecosystem(package_root / "ecosystem.yml")
    namespace = config.language_profile("en")
    assert namespace.profile_alias == "en-US"
    assert namespace.profile_language == "en-US"


def test_bic_microtransactions_carry_source_donor_target_and_report_profiles(
    package_root: Path,
    make_workspace,
) -> None:
    """INSPECT and REWRITE must not drop target/report dialect specificity between stages."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    inspect = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1:1",
    )
    inspect_profiles = _profile_rows(inspect)
    assert set(inspect_profiles) >= {"SOURCE", "DONOR", "TARGET", "REPORT:PRIMARY"}

    manifest = Path(inspect["manifest_path"])
    (manifest.parent / "output" / "inspect-submission.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation_id": inspect["task_id"],
                "scope": inspect["scope"],
                "resource_fingerprints": inspect["resource_fingerprints"],
                "proposals": [
                    {
                        "submitted_id": "P1",
                        "record_type": "LANGUAGE_RENDERING",
                        "payload": {"source": "fixture", "target": "fixture"},
                        "evidence_refs": [inspect["expected_references"][0]],
                    }
                ],
                "challenges": [],
            }
        ),
        encoding="utf-8",
    )
    submit_act_task(config, manifest)

    rewrite = create_act_task(
        config,
        workflow="bic",
        operation="rewrite",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1:1",
    )
    rewrite_profiles = _profile_rows(rewrite)
    assert set(rewrite_profiles) >= {"SOURCE", "DONOR", "TARGET", "REPORT:PRIMARY"}
    assert rewrite_profiles["DONOR"]["path"] == rewrite_profiles["TARGET"]["path"]
    assert rewrite_profiles["DONOR"]["sha256"] == rewrite_profiles["TARGET"]["sha256"]


def test_saw_rtc_targeted_and_ol_routes_bind_every_natural_language_stream(
    package_root: Path,
    make_workspace,
) -> None:
    """RTC, Targeted Check, and OL Review retain explicit profiles and deduplicate exact matches."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    rtc = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        rtc_stage="REFERENCE_TEXT_COMPARISON",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    rtc_profiles = _profile_rows(rtc)
    assert set(rtc_profiles) >= {"WIP", "REFERENCE", "REPORT:PRIMARY"}
    assert rtc_profiles["WIP"]["path"] == rtc_profiles["REFERENCE"]["path"]
    assert rtc_profiles["WIP"]["sha256"] == rtc_profiles["REFERENCE"]["sha256"]

    focused = create_act_task(
        config,
        workflow="saw",
        operation="focused",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
        focus="Check this bounded wording relationship.",
    )
    assert set(_profile_rows(focused)) >= {"WIP", "REFERENCE", "REPORT:PRIMARY"}

    ol = create_act_task(
        config,
        workflow="saw",
        operation="ol",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
        focus="Which rendering best corresponds to the bounded source form?",
    )
    ol_profiles = _profile_rows(ol)
    assert set(ol_profiles) >= {"WIP", "REFERENCE", "GRK:PRIMARY", "REPORT:PRIMARY"}
    assert ol_profiles["GRK:PRIMARY"]["profile_class"] == "OL_AUTHORITY_PROFILE"
