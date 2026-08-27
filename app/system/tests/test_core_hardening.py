"""Regression tests for hardening and optimisation closure."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage.storage import storage_layout
from sage.act_outputs import validate_bic_usfm_output
from sage.act_tasks import create_act_task, load_skill_registry, submit_act_task
from sage.errors import InputRequiredError, MemoryGovernanceError, ValidationError
from sage.grammar_governance import record_grammar_profile_review
from sage.registry import load_ecosystem
from sage.llm_tasks import execute_task
from sage.usj import compile_usfm_file
from sage.vrs import VerseRef


def run_cli(
    package_root: Path,
    workspace: Path,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    """Run the SAGE CLI in an isolated subprocess for this test."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "system" / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "sage.cli",
            "--settings",
            str(workspace / "ecosystem.yml"),
            *args,
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=45,
    )


def initialize(package_root: Path, root: Path) -> None:
    """Initialize the isolated test workspace before creating governed tasks."""
    result = run_cli(package_root, root, "workspace", "initialize")
    assert result.returncode == 0, result.stderr + result.stdout


def saw_document(task: dict, *, include_receipts: bool = True) -> dict:
    """Build a complete bounded SAW submission fixture for this test."""
    value = {
        "schema_version": "2.0",
        "narrative_language": task["narrative_language"],
        "task_id": task["task_id"],
        "operation": task["operation"],
        "stage": {
            "rtc": "REFERENCE_TEXT_COMPARISON",
            "focused": "FOCUSED_CHECK",
            "ol": "FOCUSED_OL",
        }[task["operation"]],
        "scope": task["scope"],
        "focus": task.get("focus"),
        "check_type": task.get("check_type"),
        "coverage": {
            "status": "COMPLETE",
            "reviewed_references": list(task["expected_references"]),
        },
        "structural_adjudications": [
            {
                "candidate_id": candidate_id,
                "outcome": "NO_FINDING",
                "finding_id": None,
                "rationale": "Reviewed against bounded VRS evidence.",
            }
            for candidate_id in task.get("structural_candidate_ids", [])
        ],
        "findings": [],
    }
    if include_receipts:
        value["review_receipts"] = [
            {
                "receipt_id": "R-1",
                "work_unit_id": task["review_requirements"][
                    "expected_work_unit_ids"
                ][0],
                "task_fingerprint": task["task_fingerprint"],
                "reviewed_references": list(task["expected_references"]),
                "checks_performed": list(
                    task["review_requirements"]["required_checks"]
                ),
                "evidence_summary": (
                    "Every bounded coordinate was compared against each routed "
                    "source and every required check was completed."
                ),
            }
        ]
    return value


def test_ior_pair_is_supported_and_subverse_failure_is_typed(
    tmp_path: Path,
) -> None:
    """Verify paired IOR markers and typed unsupported-subverse failures."""
    good = tmp_path / "good.SFM"
    good.write_text(
        "\\id MAT\n\\c 1\n\\p\n\\v 1 Text \\ior label\\ior* end.\n",
        encoding="utf-8",
    )
    assert compile_usfm_file(good)["sage"]["errors"] == []

    bad = tmp_path / "bad.SFM"
    bad.write_text("\\id MAT\n\\c 1\n\\v 1a Text.\n", encoding="utf-8")
    errors = compile_usfm_file(bad)["sage"]["errors"]
    assert any(item.startswith("UNSUPPORTED_SUBVERSE_LABEL:") for item in errors)


def test_layout_markers_may_normalize_but_semantic_markers_may_not(
    tmp_path: Path,
) -> None:
    """Verify layout normalization without protected semantic-marker drift."""
    path = tmp_path / "out.usfm"
    path.write_text("\\id MAT\n\\c 1\n\\q1\n\\v 1 Text.\n", encoding="utf-8")
    result = validate_bic_usfm_output(
        path,
        expected_book="MAT",
        expected_references={VerseRef("MAT", 1, 1)},
        source_marker_sequence=("id", "c", "p", "v"),
    )
    assert result["marker_policy"] == "SEMANTIC_STRUCTURE_V1"

    path.write_text(
        "\\id MAT\n\\c 1\n\\v 1 Text \\add extra\\add*.\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError) as caught:
        validate_bic_usfm_output(
            path,
            expected_book="MAT",
            expected_references={VerseRef("MAT", 1, 1)},
            source_marker_sequence=("id", "c", "p", "v"),
        )
    assert caught.value.code == "USFM_PROTECTED_MARKER_MISMATCH"


def test_inspect_rejects_out_of_scope_challenge(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify that INSPECT rejects a challenge outside its immutable scope."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1:1",
    )
    manifest = Path(task["manifest_path"])
    payload = {
        "schema_version": "1.0",
        "operation_id": task["task_id"],
        "scope": task["scope"],
        "resource_fingerprints": task["resource_fingerprints"],
        "proposals": [],
        "challenges": [
            {
                "submitted_id": "C1",
                "scripture_reference": "MAT 1:2",
                "issue": "Outside scope",
                "evidence_refs": ["MAT 1:2"],
            }
        ],
    }
    (manifest.parent / "output" / "inspect-submission.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    with pytest.raises(MemoryGovernanceError) as caught:
        submit_act_task(config, manifest)
    assert caught.value.code == "INSPECT_REFERENCE_OUTSIDE_SCOPE"


def test_saw_rejects_coverage_without_review_receipt(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify that complete SAW coverage still requires review evidence."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    manifest = Path(task["manifest_path"])
    (manifest.parent / "output" / "findings.json").write_text(
        json.dumps(saw_document(task, include_receipts=False)),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError) as caught:
        submit_act_task(config, manifest)
    assert caught.value.code == "RTC_REVIEW_EVIDENCE_MISSING"


def test_project_review_required_is_provisional_without_execution_gate(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify structurally valid provisional grammar is logged and routed without blocking."""
    root = make_workspace(qualification_status="VALIDATED")
    profile = root / "system/config/profiles/grammar/en/bol-target.yml"
    data = yaml.safe_load(profile.read_text(encoding="utf-8"))
    data["profile"]["status"] = "PROJECT_REVIEW_REQUIRED"
    profile.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    task = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    assert task["grammar_override"]["status"] == "PROVISIONAL_PROFILE_USE"
    assert task["grammar_override"]["override_id"] is None
    assert task["grammar_override"]["attention"]["next_stage_allowed"] is True

    receipt = record_grammar_profile_review(
        config,
        profile_key="en/bol-target",
        decision_id="OVERRIDE-001",
        operator="TEST_OPERATOR",
        decision="APPROVED",
        notes="Exact-hash governed override fixture.",
    )
    documented = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:2",
        grammar_override_id=receipt["decision_id"],
    )
    assert documented["grammar_override"]["override_id"] == "OVERRIDE-001"


def test_skill_registry_routes_no_legacy_contracts(package_root: Path) -> None:
    """Verify that routed Skill material contains no legacy command contracts."""
    registry = load_skill_registry(package_root)
    for binding in registry.values():
        files = [binding.path]
        reference_root = binding.path.parent / "references"
        files.extend(
            path
            for path in reference_root.glob("*")
            if path.is_file()
            and not path.name.startswith("ORIGINAL-")
            and path.name != "RUN-RTC.md"
        )
        text = "\n".join(path.read_text(encoding="utf-8") for path in files)
        assert "system/tools/bic.py" not in text
        assert "./system/bin/saw run" not in text
        assert "preflight.json" not in text.replace("saw-preflight.json", "")


def test_pytest_cache_provider_is_disabled_and_reset_removes_state(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify that pytest cache state cannot affect package validation."""
    assert "-p no:cacheprovider" in (package_root / "system" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    root = make_workspace(qualification_status="VALIDATED")
    layout = storage_layout(root, create=True)
    (root / ".pytest_cache").mkdir()
    generated = layout.cache_root / "generated.bin"
    generated.write_bytes(b"generated")
    operator_file = layout.projects_root / "operator-preserved" / "41MAT.SFM"
    operator_file.parent.mkdir(parents=True, exist_ok=True)
    operator_file.write_text("\\id MAT\n", encoding="utf-8")

    result = run_cli(package_root, root, "--json", "workspace", "reset-state")
    assert result.returncode == 0, result.stderr + result.stdout
    assert not (root / ".pytest_cache").exists()
    assert not generated.exists()
    assert operator_file.is_file()


def test_rtc_context_excludes_ol_and_raw_profile(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify that Reference Text Comparison (RTC) routes neither OL text nor a raw profile."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    paths = {item["path"] for item in task["allowed_reads"]}
    assert not any(path.endswith("original-language.usj.json") for path in paths)
    assert not any(
        path.endswith("system/config/profiles/grammar/en/bol-target.yml") for path in paths
    )
    assert any(path.endswith("project-grammar-contract.json") for path in paths)
    assert (
        task["context_budget"]["final_estimated_tokens"]
        <= task["context_budget"]["policy"]["hard_estimated_tokens"]
    )


def test_task_budget_uses_exact_projected_handoff_and_retains_governance_measurement(
    package_root: Path,
    make_workspace,
) -> None:
    """Plan against the provider representation while retaining the legacy full-context audit metric."""
    root = make_workspace(qualification_status="VALIDATED")
    initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )

    budget = task["context_budget"]
    governance = budget["governance_context"]
    assert budget["planning_basis"] == "PROJECTED_HANDOFF_ESTIMATED_TOKENS"
    assert budget["measurement_scope"] == "projected_provider_handoff"
    assert budget["final_estimated_tokens"] == budget["provider_handoff"]["total_estimated_tokens"]
    assert governance["final_estimated_tokens"] >= budget["final_estimated_tokens"]

    dry = execute_task(config, task_manifest=Path(task["manifest_path"]), dry_run=True)
    assert dry["handoff_measurement"]["total_estimated_tokens"] == budget["final_estimated_tokens"]
    assert dry["handoff_measurement"]["total_bytes"] == budget["final_serialized_bytes"]


def test_bic_allows_empty_generated_target_for_requested_scope(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify that an allowed empty target is not treated as a missing source."""
    root = make_workspace(qualification_status="VALIDATED")
    settings = root / "ecosystem.yml"
    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    data["projects"]["usBOLx1"]["allow_empty"] = True
    settings.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )
    for path in (storage_layout(root).projects_root / "usBOLx1").glob("*.SFM"):
        path.unlink()

    initialize(package_root, root)
    config = load_ecosystem(settings)
    task = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1:1",
    )
    assert task["scope"] == "MAT 1:1"
    assert Path(task["manifest_path"]).exists()


def test_hardening_runner_auto_discovers_isolates_and_resets_after_tests(
    package_root: Path,
) -> None:
    """Verify that hardening auto-discovers isolated modules and restores clean state."""
    text = (package_root / "system" / "tools" / "hardening.py").read_text(encoding="utf-8")
    assert '.glob("test_*.py")' in text
    assert 'Path(path).stem.removeprefix("test_")' in text
    assert "timeout: int = 300" in text
    assert 'env["SAGE_DISABLE_OPERATIONAL_LOG"] = "1"' in text
    assert "start_new_session=True" in text
    assert "os.killpg" in text
    assert "_cleanup_completed_process_group(process)" in text
    assert 'name="post_test_reset"' in text
    assert 'executor.submit(\n                        _run_test_module_isolated,' in text
    assert '"workspace_governed_source_unchanged"' in text
    assert 'steps.extend(_validation_steps(target, prefix="post"))' in text
    assert 'name=f"{prefix}_package_validation"' in text
    assert 'name=f"{prefix}_deep_audit"' in text
