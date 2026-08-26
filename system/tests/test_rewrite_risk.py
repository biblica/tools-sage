"""REWRITE lexical-burden, OL-risk, challenge, and decision regressions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage.storage import storage_layout
from sage.act_tasks import create_act_task, submit_act_task
from sage.bounded_target import extract_scope_usfm
from sage.errors import ValidationError
from sage.hashing import sha256_file
from sage.registry import load_ecosystem
from sage.rewrite_risk import (
    lexical_burden_total,
    longman_familiarity_score,
    validate_rewrite_challenges,
)


def _run_cli(package_root: Path, workspace: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run one canonical command against a disposable workspace."""
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
        timeout=40,
    )


def _candidate(
    candidate_id: str,
    form: str,
    *,
    familiarity: int,
    register: int = 0,
    ambiguity: int = 0,
    construction: int = 0,
    specialist: int = 0,
) -> dict:
    """Return one candidate fixture whose total follows the governed weighting formula."""
    components = {
        "familiarity": familiarity,
        "register_markedness": register,
        "sense_ambiguity": ambiguity,
        "construction_burden": construction,
        "specialist_load": specialist,
    }
    return {
        "candidate_id": candidate_id,
        "form": form,
        "meaning_features": ["CONTINUATION"],
        "tone_and_force": "Neutral continuing relation.",
        "register": "Contemporary general English.",
        "lexical_burden": {**components, "overall": lexical_burden_total(components)},
        "frequency_evidence": {
            "source": "PROJECT_ESTIMATE",
            "bands": ["UNKNOWN"],
            "note": "No licensed Longman band was routed; the project estimate is explicit.",
        },
        "main_risk": "May underrepresent the relational component.",
    }


def _initialised_rewrite(package_root: Path, make_workspace) -> tuple[object, dict, Path]:
    """Create one valid REWRITE task after committed INSPECT without a human gate."""
    workspace = make_workspace(qualification_status="VALIDATED")
    result = _run_cli(package_root, workspace, "workspace", "initialize")
    assert result.returncode == 0, result.stderr + result.stdout
    config = load_ecosystem(workspace / "ecosystem.yml")
    inspect = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1",
    )
    inspect_manifest = Path(inspect["manifest_path"])
    (inspect_manifest.parent / "output" / "inspect-submission.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "operation_id": inspect["task_id"],
                "scope": inspect["scope"],
                "resource_fingerprints": inspect["resource_fingerprints"],
                "proposals": [],
                "challenges": [
                    {
                        "submitted_id": "C1",
                        "scripture_reference": "MAT 1:1",
                        "challenge_type": "LEXICAL",
                        "summary": "The target verb may need a bounded risk check.",
                        "recommended_action": "Assess during REWRITE.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    inspect_document = json.loads(inspect_manifest.read_text(encoding="utf-8"))
    submit_act_task(config, inspect_manifest)
    rewrite = create_act_task(
        config,
        workflow="bic",
        operation="rewrite",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1",
    )
    rewrite["_test_inspect_manifest"] = inspect_document
    manifest = Path(rewrite["manifest_path"])
    output = manifest.parent / "output" / "rewrite.usfm"
    output.write_text(
        "\\id MAT Fixture\n" + extract_scope_usfm(
            (storage_layout(config.root).projects_root / "idKKHv0" / "41MAT.SFM").read_text(encoding="utf-8"),
            "MAT 1",
        ),
        encoding="utf-8",
    )
    grammar = rewrite["project_grammar"]
    (manifest.parent / "output" / "grammar-assessment.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "task_id": rewrite["task_id"],
                "scope": rewrite["scope"],
                "profile_id": grammar["profile_id"],
                "profile_sha256": grammar["profile_sha256"],
                "output_sha256": sha256_file(output),
                "rules": [
                    {
                        "rule_id": rule_id,
                        "status": "PASS",
                        "evidence": "Checked against the bounded fixture candidate.",
                    }
                    for rule_id in grammar["rule_ids"]
                ],
                "unresolved": [],
            }
        ),
        encoding="utf-8",
    )
    return config, rewrite, manifest


def _challenge_document(task: dict, output: Path, *, resolved: bool) -> dict:
    """Build one resolved or unresolved current verb-choice challenge fixture."""
    candidates = [
        _candidate("REMAIN", "remain", familiarity=0),
        _candidate("ABIDE", "abide", familiarity=2, register=2),
    ]
    if resolved:
        before, after = 2, 1
        recommended = "ABIDE"
        before_candidate = "REMAIN"
        rejected = candidates[0]
        rejected["rejection_code"] = "FORCE_WEAKENED"
        rejected["rejection_reason"] = "The bounded OL evidence favors the stronger continuing relational sense."
    else:
        before = after = 4
        recommended = "REMAIN"
        before_candidate = "REMAIN"
        rejected = candidates[1]
        rejected["rejection_code"] = "REGISTER_MISMATCH"
        rejected["rejection_reason"] = "The alternative is less accessible without a semantic gain in this context."
    document = {
        "schema_version": "1.2",
        "task_id": task["task_id"],
        "operation": "rewrite",
        "scope": task["scope"],
        "output_sha256": sha256_file(output),
        "challenges": [
            {
                "challenge_id": "TC-MAT-1-1-001",
                "scripture_reference": "MAT 1:1",
                "category": "VERB_CHOICE",
                "summary": "Two target verbs differ in relational force and lexical burden.",
                "confidence": "MEDIUM",
                "candidates": candidates,
                "recommended_candidate_id": recommended,
                "risk": {
                    "before_ol": before,
                    "after_ol": after,
                    "material_triggers": ["COMPETING_NON_EQUIVALENT_SENSES"],
                },
                "ol_referral": {
                    "performed": True,
                    "question": "Does the bounded source form require continuing relational presence?",
                    "evidence_scope": "MAT 1:1",
                    "evidence_summary": "The bounded evidence supports the recorded post-OL assessment.",
                    "before_candidate_id": before_candidate,
                },
                "messages": {
                    "id": {
                        "summary": "Dua kata kerja sasaran berbeda dalam daya relasional dan beban leksikal.",
                        "risk": "Pilihan saat ini mungkin kurang menyatakan komponen relasional.",
                        "evidence": "Bukti OL terbatas mendukung penilaian risiko yang dicatat.",
                        "action": "Lanjutkan dengan rekomendasi dan bawa tantangan ke SELF-CHECK.",
                    },
                    "en": {
                        "summary": "Two target verbs differ in relational force and lexical burden.",
                        "risk": "The current choice may underrepresent the relational component.",
                        "evidence": "The bounded OL evidence supports the recorded risk assessment.",
                        "action": "Proceed with the recommendation and carry the challenge into SELF-CHECK.",
                    },
                },
                "inherited_challenge_ids": [],
                "recommended_action": "Proceed with the recommendation and retain the challenge in the report.",
            }
        ],
    }
    if "human_output" in task:
        document["reporting_languages"] = ["en"]
    return document


def test_lexical_burden_formula_uses_fixed_weights() -> None:
    """Verify that lexical burden is reproducible rather than an intuitive single rating."""
    assert lexical_burden_total(
        {
            "familiarity": 4,
            "register_markedness": 2,
            "sense_ambiguity": 1,
            "construction_burden": 0,
            "specialist_load": 0,
        }
    ) == 2


def test_low_semantic_risk_rejects_unnecessary_automatic_ol(tmp_path: Path) -> None:
    """Verify that lexical burden alone cannot trigger routine OL consultation."""
    output = tmp_path / "candidate.usfm"
    output.write_text("fixture", encoding="utf-8")
    document = _challenge_document({"task_id": "TASK", "scope": "MAT 1:1"}, output, resolved=True)
    challenge = document["challenges"][0]
    challenge["risk"] = {"before_ol": 1, "after_ol": 1, "material_triggers": []}
    path = tmp_path / "translation-challenges.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValidationError, match="without both the risk threshold"):
        validate_rewrite_challenges(
            path, task_id="TASK", operation="rewrite", scope_value="MAT 1:1", output_path=output
        )


def test_resolved_ol_referral_updates_candidate_without_operator_gate(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify that better bounded OL evidence can lower risk and complete REWRITE automatically."""
    config, rewrite, manifest = _initialised_rewrite(package_root, make_workspace)
    output = manifest.parent / "output" / "rewrite.usfm"
    payload = _challenge_document(rewrite, output, resolved=True)
    (manifest.parent / "output" / "translation-challenges.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    result = submit_act_task(config, manifest)
    assert result["status"] == "STAGED_VALIDATED_WITH_CHALLENGES"
    assert result["decision_required"] is False
    assert result["validation"]["translation_challenges"]["highest_urgency"] == 1


def test_unresolved_critical_choice_completes_without_operator_input(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify risk four completes with the recommended candidate and no decision sidecar."""
    config, rewrite, manifest = _initialised_rewrite(package_root, make_workspace)
    output = manifest.parent / "output" / "rewrite.usfm"
    payload = _challenge_document(rewrite, output, resolved=False)
    (manifest.parent / "output" / "translation-challenges.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    result = submit_act_task(config, manifest)
    assert result["status"] == "STAGED_VALIDATED_WITH_CHALLENGES"
    assert result["decision_required"] is False
    assert result["validation"]["translation_challenges"]["highest_urgency"] == 4
    assert "operator_prompt" not in result
    assert "critical_prompt_available" not in result
    self_check = create_act_task(
        config,
        workflow="bic",
        operation="self_check",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1",
        predecessor_task=str(manifest),
    )
    paths = {item["path"] for item in self_check["allowed_reads"]}
    assert not any(path.endswith("operator-decisions.json") for path in paths)
    assert any(path.endswith("predecessor-translation-challenges.json") for path in paths)
    assert any(path.endswith("original-language.usj.json") for path in paths)
    assert any(path.endswith("inherited-ol-vrs-evidence.json") for path in paths)

    predecessor = json.loads(manifest.read_text(encoding="utf-8"))
    conditional = {item["path"]: item["sha256"] for item in predecessor["conditional_reads"]}
    self_root = Path(self_check["manifest_path"]).parent
    inherited_usj = self_root / "packet" / "original-language.usj.json"
    inherited_vrs = self_root / "packet" / "inherited-ol-vrs-evidence.json"
    assert sha256_file(inherited_usj) == next(
        digest for path, digest in conditional.items() if path.endswith("original-language.usj.json")
    )
    assert sha256_file(inherited_vrs) == next(
        digest for path, digest in conditional.items() if path.endswith("conditional-ol-vrs-evidence.json")
    )


def test_unresolved_urgent_choice_logs_and_flows_without_prompt(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify urgency three is reporting-only and never requests Operator input."""
    config, rewrite, manifest = _initialised_rewrite(package_root, make_workspace)
    output = manifest.parent / "output" / "rewrite.usfm"
    payload = _challenge_document(rewrite, output, resolved=False)
    challenge = payload["challenges"][0]
    challenge["risk"]["before_ol"] = 3
    challenge["risk"]["after_ol"] = 3
    (manifest.parent / "output" / "translation-challenges.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    result = submit_act_task(config, manifest)
    assert result["status"] == "STAGED_VALIDATED_WITH_CHALLENGES"
    assert result["validation"]["translation_challenges"]["highest_urgency"] == 3
    assert "operator_prompt" not in result
    self_check = create_act_task(
        config, workflow="bic", operation="self_check", output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0", scope_value="MAT 1", predecessor_task=str(manifest),
    )
    assert self_check["operation"] == "self_check"


def test_generated_rewrite_act_and_skill_share_current_risk_contract(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify ACT wording, Skill, schema, and protected policy share current controls."""
    _, rewrite, _ = _initialised_rewrite(package_root, make_workspace)
    act_text = Path(rewrite["act_path"]).read_text(encoding="utf-8")
    skill_text = (package_root / "system/skills/bic-rewrite/SKILL.md").read_text(encoding="utf-8")
    for required_text in (
        "translation-challenges.json",
        "automatic bounded OL check",
        "material semantic-risk level 2 or higher",
        "Linguistic uncertainty",
        "no Operator candidate input",
    ):
        assert required_text in act_text
        assert required_text in skill_text
    challenge_schema = yaml.safe_load(
        (package_root / "system/config/schemas/bic-translation-challenges.schema.yml").read_text(encoding="utf-8")
    )
    policy = yaml.safe_load(
        (package_root / "system/config/contracts/bic-verb-selection-policy.yml").read_text(encoding="utf-8")
    )["policy"]
    assert challenge_schema["ol_policy"]["risk_3_behavior"] == "REPORT_AND_CONTINUE"
    assert challenge_schema["ol_policy"]["risk_4_behavior"] == "CRITICAL_REPORT_AND_CONTINUE"
    assert challenge_schema["ol_policy"]["operator_input_during_rewrite"] == "prohibited"
    assert policy["design_rules"]["operator_input_during_rewrite"] == "PROHIBITED"
    assert not (package_root / "system/config/schemas/bic-operator-decisions.schema.yml").exists()


def test_task_decide_command_is_removed(package_root: Path, make_workspace) -> None:
    """Verify BIC candidate selection is not exposed through the task command surface."""
    workspace = make_workspace(qualification_status="VALIDATED")
    result = _run_cli(package_root, workspace, "task", "decide", "--help")
    assert result.returncode != 0
    assert "invalid value for task_command" in (result.stderr + result.stdout).casefold()


def test_longman_frequency_bands_map_to_governed_familiarity_scores() -> None:
    """Verify the spoken-first Longman mapping and conservative fallback bands."""
    assert longman_familiarity_score(["S1", "W3"]) == 0
    assert longman_familiarity_score(["W2"]) == 1
    assert longman_familiarity_score(["L3000"]) == 2
    assert longman_familiarity_score(["L6000"]) == 3
    assert longman_familiarity_score(["L9000"]) == 4
    assert longman_familiarity_score(["UNKNOWN"]) is None


def test_longman_evidence_rejects_inconsistent_familiarity_score(tmp_path: Path) -> None:
    """Verify licensed Longman evidence cannot be paired with an incompatible score."""
    output = tmp_path / "candidate.usfm"
    output.write_text("fixture", encoding="utf-8")
    challenge = _challenge_document({"task_id": "TASK", "scope": "MAT 1:1"}, output, resolved=True)
    candidate = challenge["challenges"][0]["candidates"][0]
    candidate["frequency_evidence"] = {
        "source": "LONGMAN",
        "bands": ["S1", "W3"],
        "note": "Licensed project evidence records the spoken and written bands.",
    }
    candidate["lexical_burden"]["familiarity"] = 2
    candidate["lexical_burden"]["overall"] = lexical_burden_total(candidate["lexical_burden"])
    path = tmp_path / "translation-challenges.json"
    path.write_text(json.dumps(challenge), encoding="utf-8")
    with pytest.raises(ValidationError, match="must equal Longman score 0"):
        validate_rewrite_challenges(
            path,
            task_id="TASK",
            operation="rewrite",
            scope_value="MAT 1:1",
            output_path=output,
        )


def test_bic_ol_evidence_is_conditional_not_an_ordinary_read(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify INSPECT excludes OL and REWRITE exposes it only through conditional reads."""
    _, rewrite, _ = _initialised_rewrite(package_root, make_workspace)
    allowed = {item["path"] for item in rewrite["allowed_reads"]}
    conditional = {item["path"] for item in rewrite["conditional_reads"]}
    assert not any("original-language" in path for path in allowed)
    assert any(path.endswith("original-language.usj.json") for path in conditional)
    assert any(path.endswith("conditional-ol-vrs-evidence.json") for path in conditional)
    assert {
        item["routing"] for item in rewrite["original_language_sources"]
    } == {"CONDITIONAL_MATERIAL_RISK"}
    inspect = rewrite["_test_inspect_manifest"]
    assert inspect["original_language_sources"] == []
    assert inspect["conditional_reads"] == []


def test_challenge_validator_rejects_unrouted_ol_evidence(tmp_path: Path) -> None:
    """Verify a challenge cannot cite OL evidence when no conditional packet was routed."""
    output = tmp_path / "candidate.usfm"
    output.write_text("fixture", encoding="utf-8")
    document = _challenge_document(
        {"task_id": "TASK", "scope": "MAT 1:1"},
        output,
        resolved=True,
    )
    path = tmp_path / "translation-challenges.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValidationError, match="was not conditionally routed"):
        validate_rewrite_challenges(
            path,
            task_id="TASK",
            operation="rewrite",
            scope_value="MAT 1:1",
            output_path=output,
            ol_evidence_available=False,
        )
