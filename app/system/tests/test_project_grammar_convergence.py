"""Cross-layer project grammar and workflow convergence tests."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage.storage import storage_layout
from sage.act_outputs import render_operator_note_text
from sage.act_tasks import create_act_task, submit_act_task
from sage.errors import ConfigurationError, ValidationError
from sage.grammar import load_grammar_profile
from sage.profiles import load_workflow_profile
from sage.plan_continuation import continue_saw_plan
from sage.registry import load_ecosystem
from sage.jobs import JobStore, default_job_name


def _write_yaml(path: Path, value: dict) -> None:
    """Write one deterministic YAML mutation for a convergence test."""
    path.write_text(yaml.safe_dump(value, sort_keys=False, allow_unicode=True), encoding="utf-8")



def _initialize(package_root: Path, root: Path) -> None:
    """Initialize one disposable workspace through the public CLI."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "system" / "src")
    result = subprocess.run(
        [sys.executable, "-m", "sage.cli", "--settings", str(root / "ecosystem.yml"), "workspace", "initialize"],
        text=True, capture_output=True, check=False, timeout=45, env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr



def _qa_stage_document(manifest: dict, *, ol_request: bool = False, resolved_ids: list[str] | None = None) -> dict:
    """Build one complete no-finding SAW QA stage submission for transition tests."""
    document = {
        "schema_version": "2.0",
        "task_id": manifest["task_id"],
        "operation": "qa",
        "stage": manifest["qa_stage"],
        "scope": manifest["scope"],
        "focus": None,
        "check_type": None,
        "coverage": {
            "status": "COMPLETE",
            "reviewed_references": list(manifest["expected_references"]),
        },
        "structural_adjudications": [
            {
                "candidate_id": candidate_id,
                "outcome": "NO_FINDING",
                "finding_id": None,
                "rationale": "Bounded structural evidence does not support a finding.",
            }
            for candidate_id in manifest.get("structural_candidate_ids", [])
        ],
        "review_receipts": [
            {
                "receipt_id": "R-1",
                "work_unit_id": manifest["review_requirements"]["expected_work_unit_ids"][0],
                "task_fingerprint": manifest["task_fingerprint"],
                "reviewed_references": list(manifest["expected_references"]),
                "checks_performed": list(manifest["review_requirements"]["required_checks"]),
                "evidence_summary": "Reviewed every bounded coordinate against every evidence source and required check routed to this isolated QA stage.",
            }
        ],
        "findings": [],
    }
    if ol_request:
        document["ol_review_requests"] = [{
            "request_id": "OLR-1",
            "deferred_finding_id": "OL-F-001",
            "target_reference": manifest["expected_references"][0],
            "question": "Does the bounded original-language evidence resolve this specific meaning ambiguity?",
            "reason": "The WIP and REFERENCE comparison leaves one bounded semantic ambiguity unresolved.",
            "evidence_ids": [manifest["allowed_evidence_ids"][0]],
        }]
    if resolved_ids is not None:
        expected = {row["request_id"]: row for row in manifest["review_requirements"].get("expected_ol_requests", [])}
        document["ol_resolutions"] = [
            {
                "request_id": request_id,
                "target_reference": expected[request_id]["target_reference"],
                "outcome": "NO_FINDING",
                "finding_id": None,
                "original_language_evidence": "The routed Greek evidence resolves the inherited ambiguity without supporting a finding.",
                "rationale": "No discrepancy remains after bounded OL comparison.",
            }
            for request_id in resolved_ids
        ]
        document["resolved_ol_request_ids"] = list(resolved_ids)
    return document


def test_grammar_profile_schema_is_executable(make_workspace) -> None:
    """Reject missing required metadata and structurally invalid contract sections."""
    root = make_workspace(qualification_status="VALIDATED")
    path = root / "system/config/profiles/grammar/en/bol-target.yml"
    original = yaml.safe_load(path.read_text(encoding="utf-8"))
    for missing in ("schema_version", "script", "owner_role", "last_reviewed"):
        broken = yaml.safe_load(yaml.safe_dump(original))
        broken["profile"].pop(missing)
        _write_yaml(path, broken)
        with pytest.raises((ConfigurationError, ValidationError)):
            load_grammar_profile(path, expected_profile_id="bol-target", expected_language="en", expected_role="TARGET")
    broken = yaml.safe_load(yaml.safe_dump(original))
    broken["finding_requirements"] = "BAD"
    _write_yaml(path, broken)
    with pytest.raises((ConfigurationError, ValidationError)):
        load_grammar_profile(path, expected_profile_id="bol-target", expected_language="en", expected_role="TARGET")


def test_ai_drafted_requires_llm_general_language_provenance(make_workspace) -> None:
    """Require explicit LLM-general-language provenance for accepted AI_DRAFTED profiles."""
    root = make_workspace(qualification_status="VALIDATED")
    path = root / "system/config/profiles/grammar/en/bol-target.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["profile"]["status"] = "AI_DRAFTED"
    _write_yaml(path, data)
    with pytest.raises((ConfigurationError, ValidationError)):
        load_grammar_profile(path, expected_profile_id="bol-target", expected_language="en", expected_role="TARGET")
    data["provenance"] = {
        "type": "LLM_GENERAL_LANGUAGE_KNOWLEDGE",
        "provider": "OPENAI",
        "model": "UNSPECIFIED",
        "project_validated": False,
    }
    _write_yaml(path, data)
    profile = load_grammar_profile(path, expected_profile_id="bol-target", expected_language="en", expected_role="TARGET")
    assert profile.status == "AI_DRAFTED"
    assert profile.contract()["provenance"]["type"] == "LLM_GENERAL_LANGUAGE_KNOWLEDGE"


def test_workflow_profile_schema_is_executable(make_workspace) -> None:
    """Reject a workflow profile that omits schema-required process metadata."""
    root = make_workspace(qualification_status="VALIDATED")
    path = root / "system/config/workflows/saw/profile.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["workflow"].pop("purpose")
    data.pop("process")
    _write_yaml(path, data)
    config = load_ecosystem(root / "ecosystem.yml")
    with pytest.raises(ConfigurationError):
        load_workflow_profile(config, config.workflow("saw"))


def test_job_manifest_and_bic_cardinality_are_enforced(make_workspace) -> None:
    """Require a strict manifest and one distinct bound SOURCE, DONOR, and TARGET relationship."""
    root = make_workspace(qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    store = JobStore(config.root, config.settings_path)
    with pytest.raises(ValidationError, match="three bindings must be distinct"):
        store.create_job(
            tool="bic",
            job_id="BIC_idKKHv0-usNIVv2-usNIVv2",
            display_name="Invalid",
            bindings={
                "content_source": "idKKHv0",
                "lexical_donor": "usNIVv2",
                "generated_target": "usNIVv2",
                "original_language_greek": "GRK",
                "original_language_hebrew": "HEB",
            },
        )
    project = store.create_job(
        tool="bic",
        job_id="BIC_idKKHv0-usNIVv2-usBOLx1",
        display_name="Valid",
        bindings={
            "content_source": "idKKHv0",
            "lexical_donor": "usNIVv2",
            "generated_target": "usBOLx1",
            "original_language_greek": "GRK",
            "original_language_hebrew": "HEB",
        },
    )
    raw = yaml.safe_load(project.manifest_path.read_text(encoding="utf-8"))
    raw.pop("display_name")
    _write_yaml(project.manifest_path, raw)
    with pytest.raises(ConfigurationError, match="missing required fields"):
        store.load_job("BIC_idKKHv0-usNIVv2-usBOLx1", tool="bic")


def test_direct_task_always_persists_job_and_run(package_root: Path, make_workspace) -> None:
    """Normal direct task creation resolves the canonical Project -> Job -> Run -> task grammar."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        lexical_donor_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    manifest = json.loads(Path(task["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["job_id"]
    assert manifest["run_id"]
    store = JobStore(config.root, config.settings_path)
    job = store.load_job(manifest["job_id"], tool="bic")
    assert job.bindings["generated_target"] == "usBOLx1"
    assert (job.root / "runs" / manifest["run_id"] / "run.json").is_file()


def test_ol_authority_resolves_exact_job_binding(package_root: Path, make_workspace) -> None:
    """Ignore globally available same-role OL resources when the Job binds GRK explicitly."""
    root = make_workspace(qualification_status="VALIDATED")
    settings = root / "ecosystem.yml"
    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    data["projects"]["GRK2"] = yaml.safe_load(yaml.safe_dump(data["projects"]["GRK"]))
    data["projects"]["GRK2"]["path"] = "GRK2"
    _write_yaml(settings, data)
    folder = storage_layout(root).projects_root / "GRK2"
    folder.mkdir()
    (folder / "41MAT.SFM").write_text("\\id MAT\n\\c 1\n\\v 1 Alternate Greek fixture.\n", encoding="utf-8")
    _initialize(package_root, root)
    config = load_ecosystem(settings)
    task = create_act_task(
        config,
        workflow="saw",
        operation="ol",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
        focus="Resolve the bounded OL question.",
    )
    manifest = json.loads(Path(task["manifest_path"]).read_text(encoding="utf-8"))
    assert [row["project"] for row in manifest["original_language_sources"]] == ["GRK"]


def test_bic_cohort_pins_target_identity_and_target_grammar(package_root: Path, make_workspace) -> None:
    """Pin the TARGET contract without treating pre-existing TARGET Scripture as evidence."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    task = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        lexical_donor_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    components = task["bic_evidence_cohort"]["components"]
    assert components["target_project"] == "usBOLx1"
    assert components["target_grammar_sha256"]
    routed = {Path(row["path"]).name for row in task["allowed_reads"]}
    assert not any(name == "target.usfm" for name in routed)


def test_normal_qa_starts_as_composite_meaning_stage_without_ol(package_root: Path, make_workspace) -> None:
    """Create one composite Standard QA plan whose first model stage has no OL evidence."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")
    result = create_act_task(
        config,
        workflow="saw",
        operation="qa",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    assert result["status"] == "COMPOSITE"
    assert result["current_stage"] in {"STRUCTURAL_ADJUDICATION", "TRANSLATION_AND_MEANING_QA"}
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["job_id"] and manifest["run_id"]
    if manifest["qa_stage"] in {"STRUCTURAL_ADJUDICATION", "TRANSLATION_AND_MEANING_QA"}:
        assert not manifest["original_language_sources"]
        assert not any(str(row["path"]).endswith("original-language.usj.json") for row in manifest["allowed_reads"])


def test_operator_note_text_is_plain_copy_paste_material() -> None:
    """Render SAW issues as plain text and never as a Paratext XML Notes document."""
    text = render_operator_note_text({
        "scope": "MAT 1:1",
        "coverage": {"status": "COMPLETE", "reviewed_references": ["MAT 1:1"]},
        "findings": [{
            "finding_id": "F-1",
            "target_reference": "MAT 1:1",
            "category": "Meaning",
            "issue": "Check the bounded wording.",
            "required_action": "Review with the Team.",
            "action_level": 2,
            "confidence": "MEDIUM",
            "evidence_ids": ["WIP:MAT 1:1", "REFERENCE:MAT 1:1"],
            "grammar_rule_ids": [],
            "original_language_evidence": [],
        }]
    })
    assert "REFERENCE:MAT 1:1" in text
    assert "Issue — English" in text
    assert "Proposed action — English" in text
    assert "<?xml" not in text and "<Note" not in text


def test_live_skill_contracts_have_no_stale_authority_terms(package_root: Path) -> None:
    """Lint only routed Skill material for current authority and note-output terminology."""
    files = []
    for root in (package_root / "system" / "skills").iterdir():
        if not root.is_dir():
            continue
        skill = root / "SKILL.md"
        if skill.is_file():
            files.append(skill)
        refs = root / "references"
        if refs.is_dir():
            files.extend(p for p in refs.iterdir() if p.is_file() and not p.name.startswith("ORIGINAL-") and p.name != "RUN-QA.md")
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert re.search(r"(?<!AI_)\bDRAFT\b", text) is None
    assert "reviewed-target" not in text.casefold()
    assert "reviewed target" not in text.casefold()
    inspect_text = "\n".join((package_root / "system/skills/bic-inspect" / rel).read_text(encoding="utf-8") for rel in [Path("SKILL.md"), Path("references/INSPECT-CONTRACT.md"), Path("references/SOURCE-AUTHORITY-AND-USFM.md")])
    assert "passage-relevant authoritative Greek or Hebrew packet" not in inspect_text
    assert "Apply the routed `PROTECTED-REWRITE-DETAIL-RULES.md`" not in inspect_text


def test_composite_qa_meaning_to_selective_ol_to_final_text(package_root: Path, make_workspace) -> None:
    """Carry one Standard QA Run through bounded meaning -> OL delta -> deterministic finalization."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    saw_profile = root / "system" / "config" / "workflows" / "saw" / "profile.yml"
    saw_raw = yaml.safe_load(saw_profile.read_text(encoding="utf-8"))
    saw_raw["check_policy"]["standard_qa"]["original_language"]["source_text_drift_adjudication"] = "ENABLED"
    _write_yaml(saw_profile, saw_raw)
    config = load_ecosystem(root / "ecosystem.yml")
    result = create_act_task(
        config,
        workflow="saw",
        operation="qa",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    assert result["current_stage"] == "TRANSLATION_AND_MEANING_QA"
    meaning_manifest_path = Path(result["manifest_path"])
    meaning_manifest = json.loads(meaning_manifest_path.read_text(encoding="utf-8"))
    output = meaning_manifest_path.parent / "output" / "findings.json"
    output.write_text(json.dumps(_qa_stage_document(meaning_manifest, ol_request=True)), encoding="utf-8")
    submit_act_task(config, meaning_manifest_path)

    advanced = continue_saw_plan(config, Path(result["plan_path"]))
    assert advanced["composite_stage"] == "SELECTIVE_OL_ADJUDICATION"
    ol_manifest_path = Path(advanced["next_unit"]["manifest_path"])
    ol_manifest = json.loads(ol_manifest_path.read_text(encoding="utf-8"))
    assert ol_manifest["qa_stage"] == "SELECTIVE_OL_ADJUDICATION"
    assert ol_manifest["review_requirements"]["expected_ol_request_ids"] == ["OLR-1"]
    assert [row["project"] for row in ol_manifest["original_language_sources"]] == ["GRK"]
    assert any("qa-predecessor" in str(row["path"]) for row in ol_manifest["allowed_reads"])

    ol_output = ol_manifest_path.parent / "output" / "findings.json"
    ol_output.write_text(json.dumps(_qa_stage_document(ol_manifest, resolved_ids=["OLR-1"])), encoding="utf-8")
    submit_act_task(config, ol_manifest_path)
    plan_document = json.loads(Path(result["plan_path"]).read_text(encoding="utf-8"))
    reports_root = storage_layout(root).reports_root / plan_document["job_id"] / "MAT"
    reports_root.mkdir(parents=True, exist_ok=True)
    final = continue_saw_plan(config, Path(result["plan_path"]))
    assert final["status"] == "COMPLETE"
    assert Path(final["aggregate_path"]).is_file()
    report_path = Path(final["report_path"])
    assert report_path.parent == reports_root
    assert report_path.name == "MAT_001_ACTION-REPORT.md"
    note_path = Path(final["operator_note_text_path"])
    assert note_path.is_file()
    assert note_path.parent == reports_root
    assert note_path.name == "MAT_001_OPERATOR-NOTE.txt"
    note_text = note_path.read_text(encoding="utf-8")
    assert "<?xml" not in note_text and "<Note" not in note_text

    # Older Book/scope directory layouts migrate into the flattened Book directory.
    plan_path = Path(result["plan_path"])
    nested_reports = reports_root / "MAT-001-001"
    nested_reports.mkdir()
    nested_report = nested_reports / report_path.name
    nested_note = nested_reports / note_path.name
    report_path.replace(nested_report)
    note_path.replace(nested_note)
    consolidated = Path(final["consolidated_data_path"])
    nested_data = consolidated.parent / "MAT-001-001"
    nested_data.mkdir()
    nested_consolidated = nested_data / consolidated.name
    consolidated.replace(nested_consolidated)
    nested_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    nested_plan["report_path"] = str(nested_report)
    nested_plan["operator_note_text_path"] = str(nested_note)
    nested_plan["consolidated_data_path"] = str(nested_consolidated)
    plan_path.write_text(json.dumps(nested_plan), encoding="utf-8")

    flattened = continue_saw_plan(config, plan_path)
    report_path = Path(flattened["report_path"])
    note_path = Path(flattened["operator_note_text_path"])
    assert report_path.parent == reports_root
    assert note_path.parent == reports_root
    assert not nested_reports.exists()
    assert not nested_data.exists()

    # Finalized plans from older builds migrate their plan-adjacent reports on resume.
    legacy_report = plan_path.with_name("legacy-ACTION-REPORT.md")
    legacy_note = plan_path.with_name("legacy-OPERATOR-NOTE.txt")
    report_path.replace(legacy_report)
    note_path.replace(legacy_note)
    legacy_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    legacy_plan["report_path"] = str(legacy_report)
    legacy_plan["operator_note_text_path"] = str(legacy_note)
    plan_path.write_text(json.dumps(legacy_plan), encoding="utf-8")

    migrated = continue_saw_plan(config, plan_path)

    assert Path(migrated["report_path"]).parent == reports_root
    assert Path(migrated["operator_note_text_path"]).parent == reports_root
    assert not legacy_report.exists()
    assert not legacy_note.exists()

    migrated_report = Path(migrated["report_path"])
    migrated_report.write_text("stale collision\n", encoding="utf-8")
    repaired = continue_saw_plan(config, plan_path)
    repaired_text = Path(repaired["report_path"]).read_text(encoding="utf-8")
    assert repaired_text != "stale collision\n"
    assert repaired_text.startswith("# SAW Action Report\n")
    assert "- Scope: `MAT 1`" in repaired_text
