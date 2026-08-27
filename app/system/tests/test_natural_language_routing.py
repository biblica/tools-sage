"""Governed natural-language routing regressions."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from sage.storage import storage_layout
from sage.natural_language import interpret_request
from sage.registry import load_ecosystem


def run_cli(
    package_root: Path,
    workspace: Path,
    *arguments: str,
    input_text: str | None = None,
    force_interactive: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run the SAGE CLI in an isolated subprocess for this test."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(package_root / "system" / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if force_interactive:
        environment["SAGE_FORCE_INTERACTIVE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "sage.cli",
            "--settings",
            str(workspace / "ecosystem.yml"),
            *arguments,
        ],
        input=input_text,
        text=True,
        capture_output=True,
        env=environment,
        check=False,
        timeout=40,
    )


def test_rtc_request_maps_to_registered_saw_command(make_workspace) -> None:
    """Verify that RTC request maps to registered SAW command."""
    root = make_workspace(configured=True)
    config = load_ecosystem(root / "ecosystem.yml")
    result = interpret_request("Run RTC on Amos for WIP", config)
    top = result["most_likely_command"]
    assert result["status"] == "INTERPRETATION_REQUIRED"
    assert top["command_id"] == "saw.rtc"
    assert top["output_project"] == "usWIP"
    assert top["contemporary_source"] == "usNIVv2"
    assert top["scope"] == "AMO"
    assert top["canonical_command"].startswith("./system/bin/sage task create --workflow saw")
    assert result["operator_choices"][1] == "Execute the suggested command"
    assert result["execution_policy"]["freestyle_project_execution_permitted"] is False


def test_unknown_book_is_corrected_inside_command_proposal(package_root: Path) -> None:
    """Verify that unknown book is corrected inside command proposal."""
    config = load_ecosystem(package_root / "ecosystem.yml")
    result = interpret_request("run rtc jun 10-11", config)
    top = result["most_likely_command"]
    assert top["scope"] == "JHN 10-11"
    assert top["corrections"] == [
        {
            "field": "Scripture book",
            "original": "JUN",
            "resolved": "JHN",
            "confidence": "HIGH",
        }
    ]
    assert "--scope 'JHN 10-11'" in top["canonical_command"]


def test_bic_request_uses_source_donor_target_vocabulary(make_workspace) -> None:
    """BIC natural-language proposals expose the three current BIC authority roles."""
    root = make_workspace(configured=True)
    config = load_ecosystem(root / "ecosystem.yml")
    result = interpret_request("Prepare 3 John from KKH to BOL", config)
    top = result["most_likely_command"]
    assert top["command_id"] == "bic.inspect"
    assert top["output_project"] == "usBOLx1"
    assert top["contemporary_source"] == "idKKHv0"
    assert top["lexical_donor"] == "usNIVv2"
    assert "--source idKKHv0" in top["canonical_command"]
    assert "--donor usNIVv2" in top["canonical_command"]
    assert "--target usBOLx1" in top["canonical_command"]


def test_ambiguous_bic_request_returns_ranked_existing_commands(make_workspace) -> None:
    """Verify that ambiguous BIC request returns ranked existing commands."""
    root = make_workspace(configured=True)
    config = load_ecosystem(root / "ecosystem.yml")
    result = interpret_request("Review 3 John from KKH to BOL", config)
    command_ids = [item["command_id"] for item in result["command_proposals"]]
    assert command_ids[0] == "bic.inspect"
    assert "saw.rtc" in command_ids
    assert result["exact_match"] is False
    assert result["operator_choices"][1] == "Execute the suggested command"


def test_broad_request_does_not_offer_unpredictable_execution(package_root: Path) -> None:
    """Verify that broad request does not offer unpredictable execution."""
    config = load_ecosystem(package_root / "ecosystem.yml")
    result = interpret_request("Make the translation better and fix everything", config)
    assert result["status"] == "UNSUPPORTED_OPERATION"
    assert result["most_likely_command"] is None
    assert result["operator_choices"] == [
        "Refine the request",
        "Show related supported operations",
        "Advisory response only - no project changes",
        "Cancel",
    ]


def test_noninteractive_request_returns_interpretation_and_audit_log(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify that noninteractive request returns interpretation and audit log."""
    root = make_workspace(configured=True)
    result = run_cli(
        package_root,
        root,
        "--json",
        "--no-prompt",
        "request",
        "Run RTC on Matthew for BOL",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "INTERPRETATION_REQUIRED"
    assert payload["most_likely_command"]["command_id"] == "saw.rtc"
    assert payload["most_likely_command"]["scope"] == "MAT"
    log = Path(payload["request_log"])
    assert log.is_file()
    record = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert record["original_request"] == "Run RTC on Matthew for BOL"
    assert record["decision"] == "INTERPRETATION_RETURNED"


def test_interactive_request_menu_places_command_at_option_two_and_can_cancel(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify that interactive request menu places command at option two and can cancel."""
    root = make_workspace(configured=True)
    result = run_cli(
        package_root,
        root,
        "request",
        "Run RTC on Matthew for BOL",
        input_text="7\n",
        force_interactive=True,
    )
    assert result.returncode == 2
    assert "2. Execute the suggested command" in result.stdout
    assert "Result: ABANDONED" in result.stderr
    assert "Reason code: OPERATOR_CANCELLED" in result.stderr


def test_advisory_mode_never_executes_project_command(package_root: Path, make_workspace) -> None:
    """Verify that advisory mode never executes project command."""
    root = make_workspace(configured=True)
    result = run_cli(
        package_root,
        root,
        "--json",
        "--no-prompt",
        "request",
        "Run RTC on Matthew for BOL",
        "--advisory",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "ADVISORY_ONLY"
    assert payload["project_execution"] is False
    assert not (storage_layout(root).workflow_root / "saw" / "output").exists()
