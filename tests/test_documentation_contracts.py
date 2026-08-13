"""Documentation, Skill, grammar, and operator-contract regressions."""
from __future__ import annotations

import ast
import hashlib
import io
import os
import re
import tokenize
from pathlib import Path
from urllib.parse import unquote

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of one file for contract verification."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frontmatter(path: Path) -> dict[str, str]:
    """Parse and return the YAML frontmatter from one Skill file."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"missing YAML frontmatter: {path.relative_to(ROOT)}"
    _, header, _ = text.split("---", 2)
    data = yaml.safe_load(header)
    assert isinstance(data, dict), f"invalid frontmatter: {path.relative_to(ROOT)}"
    return {str(key): str(value) for key, value in data.items()}


def test_all_skills_have_consistent_frontmatter() -> None:
    """Verify that all skills have consistent frontmatter."""
    paths = sorted(SKILLS.glob("*/SKILL.md"))
    assert len(paths) == 6
    for path in paths:
        data = frontmatter(path)
        assert set(data) == {"name", "description"}
        assert data.get("name") == path.parent.name
        assert data.get("description", "").strip()
        agent_path = path.parent / "agents" / "openai.yaml"
        assert agent_path.is_file(), path.parent.name
        agent_doc = yaml.safe_load(agent_path.read_text(encoding="utf-8"))
        assert agent_doc["interface"]["display_name"].strip()
        assert agent_doc["interface"]["short_description"].strip()


def test_registered_skill_hashes_match_current_and_original_files() -> None:
    """Verify that registered skill hashes match current and original files."""
    document = yaml.safe_load((ROOT / "meta" / "skills.yml").read_text(encoding="utf-8"))
    assert len(document["skills"]) == 6
    for item in document["skills"]:
        assert sha256(ROOT / item["file"]) == item["adapted_sha256"]
        assert sha256(ROOT / item["original_file"]) == item["original_sha256"]
        assert item["qualification_status"] == "VALIDATED"


def test_routed_skill_material_has_no_obsolete_operational_contracts() -> None:
    """Verify that routed skill material has no obsolete operational contracts."""
    forbidden = {
        "scripts/bic.py",
        "./saw run",
        "meta/saw.yml",
        "output/audit/current-stage-prompt.md",
        "workflow-system/",
        "operator-files/",
        "project-resources/project-grammar.yml",
        "docs/internal/",
        "Cline",
        "SWITCH TO ACT MODE",
        "## Guided Operator input",
        "## Natural-language command mapping",
    }
    for path in sorted(SKILLS.glob("*/SKILL.md")):
        candidates = [path]
        candidates.extend(
            item
            for item in (path.parent / "references").glob("*")
            if item.is_file() and not item.name.startswith("ORIGINAL-")
        )
        text = "\n".join(item.read_text(encoding="utf-8") for item in candidates)
        for token in forbidden:
            assert token not in text, f"{token!r} remains in routed material for {path.parent.name}"
        assert "Normal QA uses OL" not in text


def test_documented_recovery_and_generation_flags_match_cli() -> None:
    """Verify that documented recovery and generation flags match CLI."""
    for platform in ("macos-linux", "windows"):
        cheat = (ROOT / "docs" / platform / "CHEAT-SHEET.md").read_text(encoding="utf-8")
        recovery = (ROOT / "docs" / platform / "RECOVERY.md").read_text(encoding="utf-8")
        combined = cheat + "\n" + recovery
        assert "Recovery & diagnostics" in combined
        assert "--help" in combined
        assert "operator-cues.jsonl" in combined
        assert "generation pin [--consumer saw]" not in combined


def test_current_documentation_links_resolve() -> None:
    """Verify that current documentation links resolve."""
    link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    paths = [ROOT / "README.md", ROOT / "HELP.md"] + sorted((ROOT / "docs").glob("*.md")) + sorted((ROOT / "docs" / "macos-linux").glob("*.md")) + sorted((ROOT / "docs" / "windows").glob("*.md"))
    for path in paths:
        for raw_target in link_re.findall(path.read_text(encoding="utf-8")):
            target = unquote(raw_target.strip().split("#", 1)[0])
            if not target or target.startswith(("http://", "https://", "mailto:", "sandbox:", "/")):
                continue
            candidate = (path.parent / target).resolve()
            candidate.relative_to(ROOT.resolve())
            assert candidate.exists(), f"broken link: {path.relative_to(ROOT)} -> {target}"


def test_required_operator_help_set_exists_and_has_no_placeholders() -> None:
    """Verify that required operator help set exists and has no placeholders."""
    required = {
        "HELP.md",
        "docs/INDEX.md",
        "docs/macos-linux/CHEAT-SHEET.md",
        "docs/windows/CHEAT-SHEET.md",
        "docs/macos-linux/RECOVERY.md",
        "docs/windows/RECOVERY.md",
        "docs/macos-linux/ERRORS.md",
        "docs/windows/ERRORS.md",
        "docs/PROJECT-TREE.md",
        "docs/PROJECT-CATALOGUE-AND-MAINTENANCE.md",
        "docs/PROJECT-OPERATOR-CHEAT-SHEET.md",
        "docs/ORIGINAL-LANGUAGE-RESOURCES.md",
        "docs/GOOD-PRACTICE.md",
        "docs/NATURAL-LANGUAGE-COMMAND-ROUTING.md",
        "docs/PROJECT-DOCUMENT-GRAMMAR.md",
        "docs/PYTHON-MAINTENANCE.md",
        "docs/BIC-CHEAT-SHEET.md",
        "docs/SAW-CHEAT-SHEET.md",
    }
    for relative in required:
        assert (ROOT / relative).is_file(), relative
    for path in [ROOT / "README.md", ROOT / "HELP.md"] + sorted((ROOT / "docs").glob("*.md")) + sorted((ROOT / "docs" / "macos-linux").glob("*.md")) + sorted((ROOT / "docs" / "windows").glob("*.md")):
        assert "{{" not in path.read_text(encoding="utf-8"), f"unresolved placeholder: {path.relative_to(ROOT)}"


def test_posix_launchers_are_executable() -> None:
    """Verify that POSIX launchers are executable."""
    if os.name == "nt":
        return
    for name in ("sage", "bic", "saw"):
        assert os.access(ROOT / name, os.X_OK), f"launcher not executable: {name}"


def test_source_audit_uses_platform_native_launcher_checks() -> None:
    """Keep source auditing executable on Windows without requiring a POSIX shell."""
    text = (ROOT / "scripts" / "deep_audit.py").read_text(encoding="utf-8")
    assert 'if os.name != "nt":\n                run_command(["sh", "-n", str(path)]' in text
    assert '["cmd.exe", "/d", "/c", str(root / f"{launcher}.cmd"), "--help"]' in text


def test_project_grammar_contains_explicit_spelling_and_syntax_rules() -> None:
    """Verify that project grammar contains explicit spelling and syntax rules."""
    expected = {
        "profiles/languages/en/bol-target.yml": {"EN-BOL-GR-013", "EN-BOL-GR-014", "EN-BOL-GR-015", "EN-BOL-GR-016"},
        "profiles/languages/id/source.yml": {"ID-GR-011", "ID-GR-012"},
        "profiles/languages/uk/wip.yml": {"UKR-GR-018"},
        "profiles/languages/fa/wip.yml": {"FA-GR-015"},
    }
    for relative, required_ids in expected.items():
        document = yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))
        rule_ids = {item["id"] for item in document["checks"]}
        assert required_ids <= rule_ids
        assert isinstance(document.get("normalization"), dict)


def test_bic_and_saw_documented_flows_match_enforced_scope() -> None:
    """Verify that BIC and SAW documented flows match enforced scope."""
    bic = (ROOT / "workflows" / "bic" / "README.md").read_text(encoding="utf-8")
    saw = (ROOT / "workflows" / "saw" / "README.md").read_text(encoding="utf-8")
    assert "INSPECT → REWRITE → SELF-CHECK" in bic
    assert "optional human memory-review receipt" in bic.casefold() and "as provenance" in bic.casefold()
    assert "no human receipt is required" in bic
    assert "urgency 3" in bic.casefold() and "carried" in bic.casefold()
    assert "--grammar-override-id" in bic
    assert "Normal QA is one Operator operation" in saw
    assert "Focused Check" in saw and "OL Review" in saw
    assert "task-bound review evidence" in saw
    assert "work units" in saw
    assert "SELECTIVE_OL_ADJUDICATION" in saw


def test_resource_guidance_is_scope_aware() -> None:
    """Verify that resource guidance is scope aware."""
    architecture = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "workflow, operation, bound Projects, book, and verse range" in architecture
    assert "defect outside that exact scope cannot deny the task" in architecture
    resource_testing_path = ROOT / "RESOURCE-TESTING.md"
    resource_report_path = ROOT / "RESOURCE-VALIDATION-REPORT.md"
    if resource_testing_path.is_file():
        resource_testing = resource_testing_path.read_text(encoding="utf-8")
        assert "exact workflow, operation, projects, book, and verse range" in resource_testing
        assert "unrelated defect outside that scope must not block" in resource_testing
    if resource_report_path.is_file():
        report = resource_report_path.read_text(encoding="utf-8")
        assert "Historical baseline evidence" in report
        assert "Valid paired" in report and "is not itself a blocker" in report


def test_guided_input_contract_is_documented_across_environment() -> None:
    """Verify that guided input contract is documented across environment."""
    guide = (ROOT / "docs" / "GUIDED-INPUT-AND-INIT-REMEDIATION.md").read_text(encoding="utf-8")
    assert "JUN 10-11" in guide and "JHN 10-11" in guide
    assert "INPUT_REQUIRED" in guide
    assert "operator-overrides.yml" in guide
    assert "source settings file is never rewritten" in guide
    assert "only for the projects selected by that exact task" in guide
    assert "generated task is immutable" in guide or "ACT.md" in guide
    for relative in (
        "README.md",
        "HELP.md",
        "docs/AUTO-RESOLUTION.md",
        "docs/macos-linux/ERRORS.md",
        "docs/windows/ERRORS.md",
        "workflows/bic/README.md",
        "workflows/saw/README.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "INPUT_REQUIRED" in text or "Guided Input" in text or "guided" in text.casefold(), relative


def test_workflow_skills_keep_controller_only_logic_out_of_model_context() -> None:
    """Verify routed analytical Skills contain only provider-neutral governed-task instructions."""
    for path in sorted(SKILLS.glob("*/SKILL.md")):
        text = path.read_text(encoding="utf-8")
        assert "task-manifest.json" in text, path.parent.name
        assert "sealed SAGE governed task" in text, path.parent.name
        assert "Cline" not in text, path.parent.name
        assert "SWITCH TO ACT MODE" not in text, path.parent.name
        assert "## Guided Operator input" not in text, path.parent.name
        assert "## Natural-language command mapping" not in text, path.parent.name


def test_natural_language_routing_remains_controller_owned() -> None:
    """Verify natural-language command mapping stays on the controller surface rather than in model Skills."""
    text = (ROOT / "docs" / "NATURAL-LANGUAGE-COMMAND-ROUTING.md").read_text(encoding="utf-8")
    assert './sage --json --no-prompt request' in text
    assert "canonical command" in text.casefold()
    for path in sorted(SKILLS.glob("*/SKILL.md")):
        assert "Natural-language command mapping" not in path.read_text(encoding="utf-8")


def test_guided_cli_and_init_options_are_in_command_help() -> None:
    """Verify advanced command surfaces remain available even though operator docs are cheat sheets."""
    cheat = "\n".join((ROOT / "docs" / platform / "CHEAT-SHEET.md").read_text(encoding="utf-8") for platform in ("macos-linux", "windows"))
    assert "--help" in cheat
    routing = (ROOT / "docs" / "NATURAL-LANGUAGE-COMMAND-ROUTING.md").read_text(encoding="utf-8")
    assert "--no-prompt" in routing
    assert './sage request "Run QA on Amos for NPU"' in routing
    limitations = (ROOT / "docs" / "KNOWN-LIMITATIONS.md").read_text(encoding="utf-8")
    assert "`./sage request`" in limitations
    assert "not unrestricted model-driven execution" in limitations
    validation_report = (ROOT / "docs" / "TEST-AND-VALIDATION-REPORT.md").read_text(encoding="utf-8")
    assert re.search(r"passed \*\*?\d+ tests|\d+ passed", validation_report)
    auto = (ROOT / "docs" / "AUTO-RESOLUTION.md").read_text(encoding="utf-8")
    assert "operator-overrides.yml" in auto
    assert "workspace reset-state" in auto
    assert "project init --clear-overrides" in auto

def test_project_document_grammar_is_self_consistent() -> None:
    """Verify that project document grammar is self consistent."""
    text = (ROOT / "docs" / "PROJECT-DOCUMENT-GRAMMAR.md").read_text(encoding="utf-8")
    assert "British English with the SAGE project convention `-ise` and `-isation`" in text
    assert "Oxford `-ize`" not in text
    for preferred in (
        "authorisation",
        "initialisation",
        "normalisation",
        "organisation",
        "recognised",
        "capitalisation",
    ):
        assert f"`{preferred}`" in text or preferred in text
    assert "GRAMMAR_REVIEW_ID" in text
    assert "GRAMMAR-REVIEW-ID" not in text


def test_current_operating_material_uses_current_release_and_placeholder_style() -> None:
    """Verify that current operating material uses current release and placeholder style."""
    paths = [
        ROOT / "README.md",
        ROOT / "HELP.md",
        ROOT / "docs" / "macos-linux" / "CHEAT-SHEET.md",
        ROOT / "docs" / "windows" / "CHEAT-SHEET.md",
        ROOT / "docs" / "KNOWN-LIMITATIONS.md",
        ROOT / "docs" / "macos-linux" / "RECOVERY.md",
        ROOT / "docs" / "windows" / "RECOVERY.md",
        ROOT / "docs" / "BIC-CHEAT-SHEET.md",
        ROOT / "docs" / "SAW-CHEAT-SHEET.md",
    ] + sorted(SKILLS.glob("*/SKILL.md"))
    for path in paths:
        text = path.read_text(encoding="utf-8")
        current = int(re.search(r"rc(\d+)", (ROOT / "VERSION").read_text(encoding="utf-8"), re.IGNORECASE).group(1))
        prior = [m.group(0) for m in re.finditer(r"(?i)\b(?:0\.01-)?rc(\d+)(?:\.\d+)?\b", text) if int(m.group(1)) < current]
        assert not prior, (path.relative_to(ROOT), prior)
        assert "GRAMMAR-REVIEW-ID" not in text, path.relative_to(ROOT)
        assert "GRAMMAR-DECISION-ID" not in text, path.relative_to(ROOT)


def test_project_tree_covers_governed_roots_and_handover_hygiene() -> None:
    """Verify that project tree covers governed roots and handover hygiene."""
    text = (ROOT / "docs" / "PROJECT-TREE.md").read_text(encoding="utf-8")
    for token in (
        "core/sage_core/",
        "skills/",
        "docs/",
        "meta/",
        "profiles/languages/",
        "jobs/",
        "state/",
        "scripts/",
        "tests/",
        "workflows/",
        "cache/",
        "workspace-data/",
        "scripture-projects/",
    ):
        assert token in text
    assert "must not contain runtime state" in text and "second full workspace mirror" in text
    assert "skills/" in text and "Provider-neutral analytical Skills" in text


def test_cheat_sheets_name_state_transitions_and_natural_language_boundary() -> None:
    """Verify that cheat sheets name state transitions and natural language boundary."""
    bic = (ROOT / "docs" / "BIC-CHEAT-SHEET.md").read_text(encoding="utf-8")
    saw = (ROOT / "docs" / "SAW-CHEAT-SHEET.md").read_text(encoding="utf-8")
    assert "Natural-language entry" in bic and "Natural-language entry" in saw
    assert "STAGED_VALIDATED" in bic
    assert "journalled target commit" in bic
    assert "FINALIZED" in saw
    assert "SAW never edits Scripture projects" in saw
    assert "INPUT_REQUIRED" in bic and "BLOCKED" in bic
    assert "INPUT_REQUIRED" in saw and "BLOCKED" in saw
    assert "BIC_TOOL_PROJECT_ID" not in bic
    assert "--job BIC_JOB_ID" in bic


def test_representative_documented_commands_parse() -> None:
    """Verify that representative documented commands parse."""
    from sage_core.cli import build_parser

    parser = build_parser()
    commands = [
        ["--settings", "ecosystem.yml", "workspace", "reset-state"],
        ["--settings", "ecosystem.yml", "project", "init", "--non-interactive", "--clear-overrides"],
        ["--settings", "ecosystem.yml", "workspace", "validate"],
        ["--settings", "ecosystem.yml", "workspace", "initialize"],
        ["--settings", "ecosystem.yml", "request", "Run QA on Amos for NPU"],
        [
            "--settings", "ecosystem.yml", "task", "create",
            "--workflow", "bic", "--operation", "inspect",
            "--output-project", "usBOLx1", "--contemporary-source", "idKKHv0",
            "--scope", "3JN 1:1-15",
        ],
        [
            "--settings", "ecosystem.yml", "task", "create",
            "--workflow", "saw", "--operation", "qa",
            "--output-project", "ukrNPUv0", "--contemporary-source", "usNIVv2",
            "--scope", "AMO 1:1-9:15", "--grammar-override-id", "GRAMMAR_REVIEW_ID",
        ],
        ["--settings", "ecosystem.yml", "task", "aggregate", "--plan", "PATH/partition-plan.json"],
        [
            "--settings", "ecosystem.yml", "memory", "review",
            "--scope", "3JN 1:1-15", "--decision-id", "REVIEW_ID",
            "--reviewer", "REVIEWER_NAME", "--decision", "APPROVED_FOR_REWRITE",
        ],
        ["transaction", "recover", "--workflow", "bic", "--id", "TRANSACTION_ID"],
        ["generation", "verify", "--project", "usBOLx1", "--selector", "current"],
        ["project", "restart-scope", "--job", "BIC_idKKHv0-usNIVv2-usBOLx1", "--scope", "3JN 1:1-15"],
        ["project", "target-history", "--job", "BIC_idKKHv0-usNIVv2-usBOLx1", "--scope", "3JN 1:1-15"],
        ["project", "revert-target-scope", "--job", "BIC_idKKHv0-usNIVv2-usBOLx1", "--scope", "3JN 1:1-15"],
    ]
    for argv in commands:
        parsed = parser.parse_args(argv)
        assert parsed.command


def test_maintenance_scripts_suppress_workspace_bytecode() -> None:
    """Verify that maintenance scripts suppress workspace bytecode."""
    for relative in (
        "scripts/validate_package.py",
        "scripts/reset_project_state.py",
        "scripts/deep_audit.py",
        "scripts/hardening.py",
        "scripts/build_release.py",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "sys.dont_write_bytecode = True" in text, relative


def test_bic_stage_references_are_operation_specific() -> None:
    """Verify that BIC stage references are operation specific."""
    inspect_refs = ROOT / "skills" / "bic-inspect" / "references"
    rewrite_refs = ROOT / "skills" / "bic-rewrite" / "references"
    self_check_refs = ROOT / "skills" / "bic-self-check" / "references"

    assert not (inspect_refs / "PROTECTED-REWRITE-DETAIL-RULES.md").exists()

    rewrite = (rewrite_refs / "REWRITE-CONTRACT.md").read_text(encoding="utf-8")
    assert rewrite.startswith("# BIC REWRITE contract")
    assert "A valid submission creates `STAGED_VALIDATED` or `STAGED_VALIDATED_WITH_CHALLENGES`" in rewrite
    assert "must not commit the target project" in rewrite
    assert "## Self-check controls" not in rewrite

    self_check = (self_check_refs / "SELF-CHECK-CONTRACT.md").read_text(encoding="utf-8")
    assert self_check.startswith("# BIC SELF-CHECK contract")
    assert "Do not receive, request, or reconstruct the first-pass REWRITE rationale" in self_check
    assert "## Commit boundary" in self_check
    assert not (self_check_refs / "REWRITE-AND-SELF-CHECK-CONTRACT.md").exists()


def _python_nodes(tree: ast.AST):
    """Yield every class, function, method, and nested procedure in one syntax tree."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def test_every_python_procedure_has_human_editing_documentation() -> None:
    """Verify that every Python module and procedure explains its maintenance purpose."""
    forbidden = (
        "support the surrounding governed operation",
        "surrounding governed operation",
        "return or update",
        "todo",
        "fixme",
    )
    for path in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert ast.get_docstring(tree), f"module docstring missing: {path.relative_to(ROOT)}"
        tokens = list(tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline))
        meaningful_comments = {
            token.start[0]
            for token in tokens
            if token.type == tokenize.COMMENT
            and not token.string.lstrip("# ").startswith(("noqa", "type:", "pragma:"))
        }
        for node in _python_nodes(tree):
            doc = ast.get_docstring(node)
            location = f"{path.relative_to(ROOT)}:{node.lineno} {node.name}"
            assert doc, f"procedure docstring missing: {location}"
            lowered = doc.casefold()
            assert not any(phrase in lowered for phrase in forbidden), location
            assert doc.strip()[-1] in ".!?`", f"docstring punctuation missing: {location}"
            end_line = getattr(node, "end_lineno", node.lineno)
            if end_line - node.lineno + 1 >= 120:
                assert any(node.lineno < line <= end_line for line in meaningful_comments), (
                    f"long procedure lacks an internal maintenance comment: {location}"
                )


def test_python_source_avoids_semicolon_compression_and_us_prose() -> None:
    """Verify that Python remains readable and its comments follow project grammar."""
    patterns = {
        r"\banalyz(?:e|ed|es|ing)\b": "analyse",
        r"\bauthoriz(?:e|ed|es|ing|ation)\b": "authorise",
        r"\bbehavior(?:s)?\b": "behaviour",
        r"\bfinaliz(?:e|ed|es|ing|ation)\b": "finalise",
        r"\binitializ(?:e|ed|es|ing|ation)\b": "initialise",
        r"\bnormaliz(?:e|ed|es|ing|ation)\b": "normalise",
        r"\borganization(?:s)?\b": "organisation",
        r"\brecogniz(?:e|ed|es|ing)\b": "recognise",
    }
    for path in sorted(ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        assert not any(token.type == tokenize.OP and token.string == ";" for token in tokens), path.relative_to(ROOT)
        for line_number, line in enumerate(text.splitlines(), start=1):
            assert not re.match(r"^\s*import\s+[^#]*,", line), (
                f"direct imports must be one per line: {path.relative_to(ROOT)}:{line_number}"
            )
            assert not re.search(r"^\s*(?:async\s+)?def\s+\w+\([^\n]*\)->", line), (
                f"return annotation spacing is compressed: {path.relative_to(ROOT)}:{line_number}"
            )
            assert "\t" not in line, (
                f"tab indentation is not human-editable: {path.relative_to(ROOT)}:{line_number}"
            )
        assert not text or text.endswith("\n"), f"final newline missing: {path.relative_to(ROOT)}"
        fragments = [ast.get_docstring(tree) or ""]
        fragments.extend(ast.get_docstring(node) or "" for node in _python_nodes(tree))
        fragments.extend(token.string.lstrip("# ") for token in tokens if token.type == tokenize.COMMENT)
        prose = re.sub(r"`[^`]*`", "", "\n".join(fragments))
        for pattern, preferred in patterns.items():
            assert not re.search(pattern, prose, flags=re.I), (
                f"{path.relative_to(ROOT)} uses US prose matching {pattern}; prefer {preferred}"
            )


def test_naming_separators_follow_documented_boundaries() -> None:
    """Verify that filenames, Skill directories, options, and placeholders use canonical separators."""
    python_name = re.compile(r"(?:__init__|[a-z][a-z0-9_]*)\.py$")
    skill_name = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*$")
    doc_name = re.compile(r"[A-Z0-9]+(?:-[A-Z0-9]+)*\.md$")
    for path in ROOT.rglob("*.py"):
        assert python_name.fullmatch(path.name), path.relative_to(ROOT)
    for path in (ROOT / "skills").iterdir():
        if path.is_dir():
            assert skill_name.fullmatch(path.name), path.relative_to(ROOT)
    for path in (ROOT / "docs").glob("*.md"):
        assert doc_name.fullmatch(path.name), path.relative_to(ROOT)

    current = [ROOT / "README.md", ROOT / "HELP.md", ROOT / "docs" / "ARCHITECTURE.md"]
    current.extend(sorted((ROOT / "docs").glob("*.md")))
    current.extend(
        path
        for path in sorted((ROOT / "skills").rglob("*.md"))
        if "/references/ORIGINAL-" not in f"/{path.relative_to(ROOT).as_posix()}"
    )
    for path in current:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"--[a-z0-9-]*_[a-z0-9_-]*", text), path.relative_to(ROOT)
        assert not re.search(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-ID\b", text), path.relative_to(ROOT)


def test_python_maintenance_guidance_is_linked_and_complete() -> None:
    """Verify that human-editing guidance is reachable from every main documentation index."""
    maintenance = (ROOT / "docs" / "PYTHON-MAINTENANCE.md").read_text(encoding="utf-8")
    for phrase in (
        "Every Python module",
        "Every class, function, method, nested function, and test procedure",
        "snake_case",
        "reason and invariant",
        "__pycache__",
    ):
        assert phrase in maintenance
    for relative in ("README.md", "HELP.md", "docs/PROJECT-TREE.md", "docs/GOOD-PRACTICE.md"):
        assert "PYTHON-MAINTENANCE.md" in (ROOT / relative).read_text(encoding="utf-8"), relative


def test_runtime_roots_are_distribution_clean() -> None:
    """Verify that generated logs, bytecode, coverage, and test caches are absent."""
    forbidden_dirs = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov"}
    forbidden_files = {".coverage", "natural-language-requests.jsonl"}
    for path in ROOT.rglob("*"):
        if path.is_dir():
            assert path.name not in forbidden_dirs, path.relative_to(ROOT)
        elif path.is_file():
            assert path.name not in forbidden_files, path.relative_to(ROOT)
            assert path.suffix not in {".pyc", ".pyo", ".tmp", ".bak"}, path.relative_to(ROOT)
    for runtime in (ROOT / "cache", ROOT / "workspace-data"):
        payloads = [
            path for path in runtime.rglob("*")
            if path.is_file() and path.name not in {".gitkeep", "README.md"}
        ]
        assert not payloads, [path.relative_to(ROOT) for path in payloads]


def test_runtime_operator_strings_follow_project_spelling() -> None:
    """Verify that operator-facing Python strings use project spelling or exact governed literals."""
    patterns = {
        r"\banalyz(?:e|ed|es|ing)\b": "analyse",
        r"\bauthoriz(?:e|ed|es|ing|ation)\b": "authorise",
        r"\bbehavior(?:s)?\b": "behaviour",
        r"\bfinaliz(?:e|ed|es|ing|ation)\b": "finalise",
        r"\binitializ(?:e|ed|es|ing|ation)\b": "initialise",
        r"\bnormaliz(?:e|ed|es|ing|ation)\b": "normalise",
        r"\borganization(?:s)?\b": "organisation",
        r"\brecogniz(?:e|ed|es|ing)\b": "recognise",
    }
    exemptions = {
        "FINALIZED",
        "analyze challenges",
        "finalize task",
        "finalize",
        "initialization-report.json",
        "initialization-report.md",
    "initialize",
    "initialize workspace",
    "initialize.lock",
    "sage workspace initialize",
    "workspace initialize",
    "workspace.initialize",
        "normalization",
        "normalized-findings.json",
    }
    for source_root in (ROOT / "core", ROOT / "scripts"):
        for path in sorted(source_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                candidate = re.sub(r"`[^`]*`", "", node.value)
                for exemption in exemptions:
                    candidate = candidate.replace(exemption, "")
                for pattern, preferred in patterns.items():
                    assert not re.search(pattern, candidate, flags=re.I), (
                        f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', 1)} uses "
                        f"US spelling; prefer {preferred}"
                    )


def test_hardening_uses_canonical_maintenance_script_interfaces() -> None:
    """Verify that the hardening runner does not pass undocumented script arguments."""
    text = (ROOT / "scripts" / "hardening.py").read_text(encoding="utf-8")
    assert '[sys.executable, "scripts/validate_package.py"]' in text
    assert '[sys.executable, "scripts/validate_package.py", str(target)]' not in text
    assert '[sys.executable, "scripts/deep_audit.py", str(target), "--mode", "source"]' in text


def test_human_output_and_challenge_materiality_are_documented() -> None:
    """Verify independent language channels and concise material reporting are current contracts."""
    guide = (ROOT / "docs" / "HUMAN-OUTPUT-AND-LOGGING.md").read_text(encoding="utf-8")
    ecosystem = yaml.safe_load((ROOT / "ecosystem.yml").read_text(encoding="utf-8"))
    assert "logs_and_reports" in guide
    assert "translation_challenges" in guide
    assert "minimum_individual_urgency" in guide
    assert "operational.jsonl" in guide and "operational.log" in guide
    assert "aggregate" in guide.casefold() and "consolidat" in guide.casefold()
    assert ecosystem["human_output"]["logs_and_reports"]["primary_language"] == "en"
    assert ecosystem["human_output"]["translation_challenges"]["primary_language"] == "id"


def test_current_bic_guidance_has_no_human_progression_gate() -> None:
    """Verify current BIC surfaces treat human review and critical decisions as optional provenance."""
    paths = [
        ROOT / "bic",
        ROOT / "workflows" / "bic" / "README.md",
        ROOT / "docs" / "BIC-CHEAT-SHEET.md",
        ROOT / "docs" / "FULL-PROCESS-FLOW.md",
        ROOT / "skills" / "bic-inspect" / "SKILL.md",
        ROOT / "skills" / "bic-rewrite" / "SKILL.md",
        ROOT / "skills" / "bic-self-check" / "SKILL.md",
    ]
    forbidden = (
        "mandatory human gate",
        "human review receipt authorises progression",
        "operator decision before self-check",
        "requires one governed operator choice",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8").casefold()
        for phrase in forbidden:
            assert phrase not in text, path.relative_to(ROOT)


def test_bic_current_surfaces_describe_conditional_ol_routing() -> None:
    """Verify BIC documentation and Skills do not describe OL as an ordinary read."""
    rewrite = (ROOT / "skills" / "bic-rewrite" / "SKILL.md").read_text(encoding="utf-8")
    inspect = (ROOT / "skills" / "bic-inspect" / "SKILL.md").read_text(encoding="utf-8")
    flow = (ROOT / "docs" / "FULL-PROCESS-FLOW.md").read_text(encoding="utf-8")
    assert "conditional OL" in rewrite
    assert "Routine INSPECT does not route OL Scripture" in flow
    assert "routed original-language packet" not in inspect



def test_first_time_setup_has_one_canonical_surface_flow() -> None:
    """Verify guided launcher setup replaces documentation-driven onboarding."""
    assert not (ROOT / "START-HERE.md").exists()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    help_index = (ROOT / "HELP.md").read_text(encoding="utf-8")
    assert "Run SAGE" in readme and "First use does not require a Start Here document" in readme
    assert "System / Configuration" in help_index
    for platform in ("macos-linux", "windows"):
        cheat = (ROOT / "docs" / platform / "CHEAT-SHEET.md").read_text(encoding="utf-8")
        recovery = (ROOT / "docs" / platform / "RECOVERY.md").read_text(encoding="utf-8")
        errors_doc = (ROOT / "docs" / platform / "ERRORS.md").read_text(encoding="utf-8")
        assert "Codex CLI" in cheat and "operator confirmation" in cheat
        assert "setup-state.json" in recovery and "operator-cues.jsonl" in recovery
        assert "CODEX_CLI_NOT_FOUND" in errors_doc
    opening = yaml.safe_load((ROOT / "ecosystem.yml").read_text(encoding="utf-8"))["setup_guidance"]
    assert opening["canonical_surface"] == "sage launcher guided setup"
    assert opening["normal_launch"] == "./sage"
    assert opening["windows_launch"] == "sage.cmd"
    assert opening["provider_surface"] == "SEALED_GOVERNED_TASK_ONLY"

def test_provider_neutral_skills_keep_setup_and_task_surfaces_separate() -> None:
    """Verify setup/controller directions are not routed into analytical model Skills."""
    for path in sorted(SKILLS.glob("*/SKILL.md")):
        rules = path.read_text(encoding="utf-8")
        assert "sealed SAGE governed task" in rules
        assert "FIRST-RUN SETUP" not in rules
        assert "Natural-language command mapping" not in rules
        assert "Cline" not in rules
