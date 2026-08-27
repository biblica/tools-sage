"""BIC 4 protected-contract, vocabulary, generated-ACT, and terminology regressions."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage.act_tasks import ACT_OPERATIONS, create_act_task, submit_act_task
from sage.bounded_target import extract_scope_usfm
from sage.bic_memory import record_human_memory_review
from sage.runtime_paths import workflow_memory_root
from sage.cli import ALLOWED_OPERATIONS, SHORTCUT_COMMANDS, build_parser
from sage.guided_input import ArgumentChoiceProblem
from sage.hashing import sha256_file
from sage.natural_language import interpret_request
from sage.registry import load_ecosystem
from sage.jobs import JobStore
from sage.vocabulary import (
    CANONICAL_TARGET_TEXT_OPERATION,
    PROHIBITED_TARGET_TEXT_VERBS,
    prohibited_target_text_verbs,
)

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_BIC4_CONTRACT_SHA256 = "f2c8b9bc3d0626260021a042fdb3aed36909c13056156c3a7ea9bc6cc49b3aea"
EXPECTED_VERB_POLICY_SHA256 = "5bdc196242b320ec24273d48051e372a7a03c266ca4016b53517065cbfef6e53"
PRIVATE_ALIAS_START = "# BEGIN PRIVATE OPERATOR INPUT ALIASES"
PRIVATE_ALIAS_END = "# END PRIVATE OPERATOR INPUT ALIASES"


def _run_cli(package_root: Path, workspace: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the canonical CLI against one disposable fixture without writing bytecode."""
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


def _initialise(package_root: Path, workspace: Path) -> None:
    """Initialize one disposable workspace before creating governed ACT tasks."""
    result = _run_cli(package_root, workspace, "workspace", "initialize")
    assert result.returncode == 0, result.stderr + result.stdout


def _submit_inspect(config, task: dict) -> None:
    """Write and submit the minimum valid INSPECT record needed for REWRITE testing."""
    manifest = Path(task["manifest_path"])
    payload = {
        "schema_version": "1.0",
        "operation_id": task["task_id"],
        "scope": task["scope"],
        "resource_fingerprints": task["resource_fingerprints"],
        "proposals": [
            {
                "submitted_id": "P1",
                "record_type": "LANGUAGE_RENDERING",
                "payload": {"source": "fixture", "target": "fixture"},
                "evidence_refs": [task["expected_references"][0]],
            }
        ],
        "challenges": [],
    }
    (manifest.parent / "output" / "inspect-submission.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    submit_act_task(config, manifest)


def _approve_rewrite(config, task: dict) -> None:
    """Record review provenance inside the exact Job that owns the committed INSPECT."""
    store = JobStore(config.root, config.settings_path)
    job = store.load_job(task["job_id"], tool="bic")
    runtime = load_ecosystem(store.ensure_runtime_files(job))
    record_human_memory_review(
        memory_root=workflow_memory_root(runtime.workflow("bic")),
        transaction_root=runtime.workflow("bic").transaction_root,
        scope=task["scope"],
        decision_id="BIC4-CONTRACT-TEST",
        reviewer="Fixture Reviewer",
        decision="APPROVED_FOR_REWRITE",
        notes="Fixture progression approval after reviewing the committed INSPECT record.",
    )


def _write_assessment(task: dict, output_path: Path) -> None:
    """Write a complete grammar assessment bound to one generated candidate hash."""
    grammar = task["project_grammar"]
    payload = {
        "schema_version": "1.0",
        "task_id": task["task_id"],
        "scope": task["scope"],
        "profile_id": grammar["profile_id"],
        "profile_sha256": grammar["profile_sha256"],
        "output_sha256": sha256_file(output_path),
        "rules": [
            {
                "rule_id": rule_id,
                "status": "PASS",
                "evidence": "The bounded fixture candidate was checked against this rule.",
            }
            for rule_id in grammar["rule_ids"]
        ],
        "unresolved": [],
    }
    (output_path.parent / "grammar-assessment.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    if str(task.get("operation", "")) == "rewrite":
        (output_path.parent / "translation-challenges.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.2",
                    "task_id": task["task_id"],
                    "operation": "rewrite",
                    "scope": task["scope"],
                    "output_sha256": sha256_file(output_path),
                    "challenges": [],
                }
            ),
            encoding="utf-8",
        )


def _strip_private_input_aliases(text: str) -> str:
    """Remove the governed untrusted-input alias block before emitted-surface assertions."""
    start = text.index(PRIVATE_ALIAS_START)
    end = text.index(PRIVATE_ALIAS_END, start) + len(PRIVATE_ALIAS_END)
    return text[:start] + text[end:]


def _current_operational_files(root: Path):
    """Yield current operational text while excluding governed evidence and test fixtures."""
    exempt_files = {
        "system/src/sage/vocabulary.py",
        "system/tools/deep_audit.py",
    }
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        parts = Path(rel).parts
        if rel in exempt_files:
            continue
        if parts and parts[0] in {".venv", "projects", "tests", "cache", "workspace_data"}:
            continue
        if any(part.startswith("historical-") for part in parts):
            continue
        if "/references/ORIGINAL-" in f"/{rel}":
            continue
        if path.suffix.lower() not in {".md", ".txt", ".yml", ".yaml", ".json", ".py", ".sh", ".cmd"} and path.name not in {"sage", "bic", "saw"}:
            continue
        yield path, rel


def test_bic_verb_selection_policy_is_hash_pinned_independently() -> None:
    """Verify the protected verb-selection policy can evolve independently from Python refactors."""
    policy_path = ROOT / "system" / "config" / "contracts" / "bic-verb-selection-policy.yml"
    pin_path = ROOT / "system" / "config" / "bic-protected-verb-selection-pin.json"
    pin = json.loads(pin_path.read_text(encoding="utf-8"))["contract"]
    assert pin["status"] == "PINNED"
    assert pin["baseline"] == "1.00"
    assert pin["sha256"] == EXPECTED_VERB_POLICY_SHA256
    assert sha256_file(policy_path) == EXPECTED_VERB_POLICY_SHA256
    assert pin["canonical_file"] == "system/config/contracts/bic-verb-selection-policy.yml"


def test_complete_bic4_contract_is_hash_pinned_without_abbreviation() -> None:
    """Verify that both active stages retain the complete explicitly pinned BIC 4 contract."""
    rewrite_path = ROOT / "system" / "skills" / "bic-rewrite" / "references" / "PROTECTED-REWRITE-DETAIL-RULES.md"
    self_check_path = ROOT / "system" / "skills" / "bic-self-check" / "references" / "PROTECTED-REWRITE-DETAIL-RULES.md"
    rewrite_text = rewrite_path.read_text(encoding="utf-8")
    self_check_text = self_check_path.read_text(encoding="utf-8")
    assert rewrite_text == self_check_text
    assert sha256_file(rewrite_path) == EXPECTED_BIC4_CONTRACT_SHA256
    assert sha256_file(self_check_path) == EXPECTED_BIC4_CONTRACT_SHA256
    required_fragments = (
        "tense contribution",
        "information focus",
        "honorifics",
        "connectors",
        "literary form",
        "every source marker, level, caller, reference target, attribute",
        "nested `\\+` marker identity",
        "heading, poetry line, footnote, cross-reference",
        "`\\add`, `\\nd`, `\\qt`, `\\wj`",
        "Retain the source content-marker sequence inside scope",
        "`START` content",
        "layout-only paragraph or poetry marker levels",
    )
    for fragment in required_fragments:
        assert fragment in rewrite_text
    pin = json.loads((ROOT / "system" / "config" / "bic-protected-rewrite-pin.json").read_text(encoding="utf-8"))["contract"]
    assert pin["sha256"] == EXPECTED_BIC4_CONTRACT_SHA256
    assert pin["canonical_file"] == rewrite_path.relative_to(ROOT).as_posix()
    assert self_check_path.relative_to(ROOT).as_posix() in pin["mirror_files"]


def test_review_and_flow_have_distinct_system_grammar_meanings() -> None:
    """Verify that system grammar separates assessment language from sequence language."""
    grammar = (ROOT / "docs" / "advanced" / "architecture" / "SAGE-SYSTEM-GRAMMAR.md").read_text(encoding="utf-8")
    assert "## Review versus flow" in grammar
    assert "Use `review` for an examination, assessment, adjudication" in grammar
    assert "Use `flow` for an ordered sequence of stages" in grammar
    assert "Do not use `review` as a synonym for a process sequence" in grammar
    assert "Do not use `flow` as a synonym for an assessment or approval gate" in grammar


def test_emitted_operational_surfaces_exclude_prohibited_target_text_verbs() -> None:
    """Verify that current prompts, commands, Skills, help, and code emit canonical vocabulary."""
    failures: list[str] = []
    for path, rel in _current_operational_files(ROOT):
        text = path.read_text(encoding="utf-8")
        if rel == "system/src/sage/natural_language.py":
            text = _strip_private_input_aliases(text)
        matches = prohibited_target_text_verbs(text)
        if matches:
            failures.append(f"{rel}: {', '.join(matches)}")
    assert failures == []
    bic_text = (ROOT / "system" / "skills" / "bic-inspect" / "SKILL.md").read_text(encoding="utf-8")
    assert "translation challenges" in bic_text


def test_untrusted_input_synonym_maps_to_canonical_rewrite_without_emission(package_root: Path) -> None:
    """Verify that a private input synonym resolves to REWRITE without entering output vocabulary."""
    config = load_ecosystem(package_root / "ecosystem.yml")
    request = f"{PROHIBITED_TARGET_TEXT_VERBS[0]} 3 John from KKH to BOL"
    result = interpret_request(request, config)
    top = result["most_likely_command"]
    assert top["command_id"] == "bic.rewrite"
    assert top["operation"] == CANONICAL_TARGET_TEXT_OPERATION
    assert f"--operation {CANONICAL_TARGET_TEXT_OPERATION}" in top["canonical_command"]
    emitted = json.dumps(
        {
            "most_likely_command": top,
            "operator_choices": result["operator_choices"],
            "related_operations": result["related_operations"],
        },
        ensure_ascii=False,
    )
    assert prohibited_target_text_verbs(emitted) == ()


def test_rewrite_is_the_only_canonical_bic_target_text_operation() -> None:
    """Verify that all parser and shortcut contracts expose REWRITE as the sole production action."""
    assert ACT_OPERATIONS["bic"] == {"inspect", CANONICAL_TARGET_TEXT_OPERATION, "self_check"}
    assert ALLOWED_OPERATIONS["bic"] == ACT_OPERATIONS["bic"]
    assert CANONICAL_TARGET_TEXT_OPERATION in SHORTCUT_COMMANDS["bic"]
    assert not set(PROHIBITED_TARGET_TEXT_VERBS).intersection(SHORTCUT_COMMANDS["bic"])
    parser = build_parser()
    with pytest.raises(ArgumentChoiceProblem):
        parser.parse_args(
            [
                "task",
                "create",
                "--workflow",
                "bic",
                "--operation",
                PROHIBITED_TARGET_TEXT_VERBS[0],
                "--output-project",
                "usBOLx1",
                "--contemporary-source",
                "idKKHv0",
                "--scope",
                "3JN",
            ]
        )


def test_generated_rewrite_and_self_check_acts_enforce_contract_and_vocabulary(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify actual generated BIC ACT files route the pinned contract without prohibited output."""
    workspace = make_workspace(qualification_status="VALIDATED")
    _initialise(package_root, workspace)
    config = load_ecosystem(workspace / "ecosystem.yml")
    inspect = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1",
    )
    _submit_inspect(config, inspect)
    _approve_rewrite(config, inspect)

    rewrite = create_act_task(
        config,
        workflow="bic",
        operation=CANONICAL_TARGET_TEXT_OPERATION,
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1",
    )
    rewrite_manifest = Path(rewrite["manifest_path"])
    rewrite_act = rewrite_manifest.parent / "ACT.md"
    assert prohibited_target_text_verbs(rewrite_act.read_text(encoding="utf-8")) == ()
    assert rewrite["protected_rewrite_contract"]["sha256"] == EXPECTED_BIC4_CONTRACT_SHA256
    assert rewrite["resource_fingerprints"]["bic.protected_rewrite_contract"] == EXPECTED_BIC4_CONTRACT_SHA256
    routed_rewrite_contract = [
        item for item in rewrite["governance_inputs"]
        if item["path"].endswith("PROTECTED-REWRITE-DETAIL-RULES.md")
    ]
    assert routed_rewrite_contract == [
        {
            "path": "system/skills/bic-rewrite/references/PROTECTED-REWRITE-DETAIL-RULES.md",
            "sha256": EXPECTED_BIC4_CONTRACT_SHA256,
            "evidence_class": "PROCESS_CONTROL",
        }
    ]

    rewrite_output = rewrite_manifest.parent / "output" / "rewrite.usfm"
    rewrite_output.write_text(
        "\\id MAT Fixture\n" + extract_scope_usfm(
            (workspace.parent / "localdata" / "work" / "projects" / "idKKHv0" / "41MAT.SFM").read_text(encoding="utf-8"),
            "MAT 1",
        ),
        encoding="utf-8",
    )
    _write_assessment(rewrite, rewrite_output)
    submit_act_task(config, rewrite_manifest)

    self_check = create_act_task(
        config,
        workflow="bic",
        operation="self_check",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1",
        predecessor_task=str(rewrite_manifest),
    )
    self_manifest = Path(self_check["manifest_path"])
    self_act = self_manifest.parent / "ACT.md"
    assert prohibited_target_text_verbs(self_act.read_text(encoding="utf-8")) == ()
    assert self_check["protected_rewrite_contract"]["sha256"] == EXPECTED_BIC4_CONTRACT_SHA256
    routed_self_contract = [
        item for item in self_check["governance_inputs"]
        if item["path"].endswith("PROTECTED-REWRITE-DETAIL-RULES.md")
    ]
    assert routed_self_contract == [
        {
            "path": "system/skills/bic-self-check/references/PROTECTED-REWRITE-DETAIL-RULES.md",
            "sha256": EXPECTED_BIC4_CONTRACT_SHA256,
            "evidence_class": "PROCESS_CONTROL",
        }
    ]
