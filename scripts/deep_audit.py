#!/usr/bin/env python3
"""Run deterministic source/workspace, syntax, command, documentation, and Skill audits."""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tokenize
import zipfile
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

import yaml

FORBIDDEN_DIRS = {
    "__pycache__",
    ".pytest_cache",
    "__MACOSX",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
}
FORBIDDEN_NAMES = {".coverage", ".DS_Store", "Thumbs.db", "desktop.ini"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".tmp", ".swp", ".swo", ".bak"}
FILE_KEYS = {
    "file",
    "canonical_file",
    "custom_file_default",
    "base_file",
    "custom_file",
    "source_archive",
    "manifest_file",
    "original_file",
}
FILE_LIST_KEYS = {"base_files"}
ALLOWED_SENTINELS = {"auto", "none"}
SCRIPTURE_SUFFIXES = {".sfm", ".usfm"}
TEXT_SUFFIXES = {".md", ".txt", ".yml", ".yaml", ".json", ".py", ".sh", ".cmd"}
CURRENT_DOCS = {"README.md", "HELP.md"}
BRITISH_SPELLING = {
    r"\banalyze\b": "analyse",
    r"\banalyzed\b": "analysed",
    r"\bauthorization\b": "authorisation",
    r"\bauthorized\b": "authorised",
    r"\bbehavior\b": "behaviour",
    r"\bbehaviors\b": "behaviours",
    r"\bcapitalization\b": "capitalisation",
    r"\bfinalization\b": "finalisation",
    r"\bfinalize\b": "finalise",
    r"\bfinalized\b": "finalised",
    r"\binitialization\b": "initialisation",
    r"\binitialized\b": "initialised",
    r"\bnormalization\b": "normalisation",
    r"\bnormalized\b": "normalised",
    r"\borganization\b": "organisation",
    r"\borganizations\b": "organisations",
    r"\brecognized\b": "recognised",
    r"\brecognizes\b": "recognises",
}
LOCAL_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
PYTHON_DOC_FORBIDDEN = {
    "support the surrounding governed operation": "generated placeholder wording",
    "surrounding governed operation": "generated placeholder wording",
    "return or update": "ambiguous generated wording",
    "todo": "unresolved maintenance note",
    "fixme": "unresolved maintenance note",
}
PYTHON_HUMAN_SPELLING = {
    r"\banalyz(?:e|ed|es|ing)\b": "analyse",
    r"\bauthoriz(?:e|ed|es|ing|ation)\b": "authorise/authorisation",
    r"\bbehavior(?:s)?\b": "behaviour",
    r"\bfinaliz(?:e|ed|es|ing|ation)\b": "finalise/finalisation",
    r"\binitializ(?:e|ed|es|ing|ation)\b": "initialise/initialisation",
    r"\bnormaliz(?:e|ed|es|ing|ation)\b": "normalise/normalisation",
    r"\borganization(?:s)?\b": "organisation",
    r"\brecogniz(?:e|ed|es|ing)\b": "recognise",
}
PYTHON_STRING_EXEMPTIONS = {
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
PYTHON_FILENAME_RE = re.compile(r"(?:__init__|[a-z][a-z0-9_]*)\.py$")
SKILL_DIRECTORY_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*$")
DOC_FILENAME_RE = re.compile(r"[A-Z0-9]+(?:-[A-Z0-9]+)*\.md$")
CLI_UNDERSCORE_RE = re.compile(r"--[a-z0-9-]*_[a-z0-9_-]*")
HYPHENATED_ID_PLACEHOLDER_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-ID\b")
PROHIBITED_TARGET_TEXT_VERB_RE = re.compile(
    r"\b(?:translate|translated|translates|translating)\b", re.IGNORECASE
)
PRIVATE_INPUT_ALIAS_START = "# BEGIN PRIVATE OPERATOR INPUT ALIASES"
PRIVATE_INPUT_ALIAS_END = "# END PRIVATE OPERATOR INPUT ALIASES"
VOCABULARY_IMPLEMENTATION_EXEMPTIONS = {
    "core/sage_core/vocabulary.py",
    "scripts/deep_audit.py",
        "scripts/bootstrap_runtime.py",
}


ROUTED_CONTRACT_FORBIDDEN = {
    "scripts/bic.py": "obsolete BIC script command",
    "./saw run": "obsolete SAW controller command",
    "meta/saw.yml": "obsolete SAW metadata path",
    "output/audit/current-stage-prompt.md": "obsolete SAW prompt path",
    "workflow-system/": "obsolete BIC workflow-system path",
    "operator-files/": "obsolete BIC operator-files path",
    "project-resources/project-grammar.yml": "obsolete project-grammar path",
    "docs/internal/": "obsolete internal documentation path",
}



def strip_inline_code(text: str) -> str:
    """Remove backtick-delimited literals before prose-only language checks."""
    return re.sub(r"`[^`]*`", "", text)


def _remove_private_input_aliases(text: str, rel: str, errors: list[str]) -> str:
    """Remove the one governed private input-lexicon block before emitted-vocabulary checks."""
    if rel != "core/sage_core/natural_language.py":
        return text
    start_count = text.count(PRIVATE_INPUT_ALIAS_START)
    end_count = text.count(PRIVATE_INPUT_ALIAS_END)
    if start_count != 1 or end_count != 1:
        errors.append("Private natural-language input alias block is missing or duplicated")
        return text
    start = text.index(PRIVATE_INPUT_ALIAS_START)
    end = text.index(PRIVATE_INPUT_ALIAS_END, start) + len(PRIVATE_INPUT_ALIAS_END)
    return text[:start] + text[end:]


def check_target_text_vocabulary(path: Path, rel: str, errors: list[str]) -> None:
    """Reject prohibited target-text action verbs from current emitted operational surfaces."""
    parts = Path(rel).parts
    if (
        rel in VOCABULARY_IMPLEMENTATION_EXEMPTIONS
        or (parts and parts[0] in {"projects", "tests", "cache", "workspace-data"})
        or any(part.startswith("historical-") for part in parts)
        or "/references/ORIGINAL-" in f"/{rel}"
    ):
        return
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    checked = _remove_private_input_aliases(text, rel, errors)
    matches = sorted({match.group(0) for match in PROHIBITED_TARGET_TEXT_VERB_RE.finditer(checked)})
    if matches:
        errors.append(
            f"Prohibited target-text action vocabulary in {rel}: {', '.join(matches)}"
        )


def check_bic_protected_rewrite_contract(root: Path, errors: list[str]) -> None:
    """Verify the pinned BIC 4 protected contract and every routed active mirror."""
    pin_path = root / "meta" / "bic-protected-rewrite-contract.yml"
    if not pin_path.is_file():
        errors.append("Missing pinned BIC protected rewrite contract metadata")
        return
    try:
        raw = yaml.safe_load(pin_path.read_text(encoding="utf-8"))
        contract = raw["contract"]
        expected = str(contract["sha256"]).lower()
        values = [contract["canonical_file"], *(contract.get("mirror_files") or [])]
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Invalid BIC protected rewrite contract metadata: {exc}")
        return
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        errors.append("Pinned BIC protected rewrite contract SHA-256 is invalid")
        return
    for value in values:
        contract_path = (root / str(value)).resolve()
        try:
            contract_path.relative_to(root.resolve())
        except ValueError:
            errors.append(f"BIC protected rewrite contract path escapes the workspace: {value}")
            continue
        if not contract_path.is_file():
            errors.append(f"BIC protected rewrite contract file is missing: {value}")
            continue
        actual = hashlib.sha256(contract_path.read_bytes()).hexdigest()
        if actual != expected:
            errors.append(
                f"BIC protected rewrite contract hash mismatch: {value}; "
                f"expected {expected}, received {actual}"
            )


def check_bic_protected_verb_selection_contract(root: Path, errors: list[str]) -> None:
    """Verify the pinned BIC verb-selection policy without pinning Python implementation files."""
    pin_path = root / "meta" / "bic-protected-verb-selection-contract.yml"
    if not pin_path.is_file():
        errors.append("Missing pinned BIC protected verb-selection contract metadata")
        return
    try:
        raw = yaml.safe_load(pin_path.read_text(encoding="utf-8"))
        contract = raw["contract"]
        expected = str(contract["sha256"]).lower()
        canonical = str(contract["canonical_file"])
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Invalid BIC protected verb-selection contract metadata: {exc}")
        return
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        errors.append("Pinned BIC protected verb-selection contract SHA-256 is invalid")
        return
    contract_path = (root / canonical).resolve()
    try:
        contract_path.relative_to(root.resolve())
    except ValueError:
        errors.append(f"BIC protected verb-selection contract path escapes the workspace: {canonical}")
        return
    if not contract_path.is_file():
        errors.append(f"BIC protected verb-selection contract file is missing: {canonical}")
        return
    actual = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    if actual != expected:
        errors.append(
            f"BIC protected verb-selection contract hash mismatch: {canonical}; "
            f"expected {expected}, received {actual}"
        )


def python_human_text(tree: ast.AST, tokens: list[tokenize.TokenInfo]) -> str:
    """Collect docstrings and comments intended to guide human maintainers."""
    fragments: list[str] = []
    module_doc = ast.get_docstring(tree)
    if module_doc:
        fragments.append(module_doc)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node)
            if doc:
                fragments.append(doc)
    fragments.extend(token.string.lstrip("# ") for token in tokens if token.type == tokenize.COMMENT)
    return "\n".join(fragments)


def check_python_maintainability(
    path: Path,
    rel: str,
    errors: list[str],
    counts: dict[str, int],
) -> None:
    """Require documented, editable Python procedures and reason-oriented comments."""
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as exc:
        errors.append(f"Invalid Python syntax {rel}:{exc.lineno}: {exc.msg}")
        return

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (IndentationError, tokenize.TokenError) as exc:
        errors.append(f"Cannot tokenise Python source {rel}: {exc}")
        return

    if not ast.get_docstring(tree):
        errors.append(f"Python module lacks a maintenance docstring: {rel}")

    meaningful_comment_lines = {
        token.start[0]
        for token in tokens
        if token.type == tokenize.COMMENT
        and not token.string.lstrip("# ").startswith(("noqa", "type:", "pragma:"))
    }
    procedure_count = 0
    documented_count = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        procedure_count += 1
        doc = ast.get_docstring(node)
        label = getattr(node, "name", "<anonymous>")
        if not doc:
            errors.append(f"Python procedure lacks a docstring: {rel}:{node.lineno} {label}")
            continue
        documented_count += 1
        lowered = doc.casefold()
        for phrase, reason in PYTHON_DOC_FORBIDDEN.items():
            if phrase in lowered:
                errors.append(
                    f"Python procedure has {reason}: {rel}:{node.lineno} {label}"
                )
        if doc.strip()[-1:] not in {".", "!", "?", "`"}:
            errors.append(f"Python docstring lacks terminal punctuation: {rel}:{node.lineno} {label}")
        end_line = getattr(node, "end_lineno", node.lineno)
        if end_line - node.lineno + 1 >= 120:
            has_internal_comment = any(node.lineno < line <= end_line for line in meaningful_comment_lines)
            if not has_internal_comment:
                errors.append(
                    f"Long Python procedure lacks an internal maintenance comment: "
                    f"{rel}:{node.lineno} {label}"
                )

    for token in tokens:
        if token.type == tokenize.OP and token.string == ";":
            errors.append(f"Python source uses semicolon-compressed statements: {rel}:{token.start[0]}")

    for line_number, line in enumerate(text.splitlines(), start=1):
        if re.match(r"^\s*import\s+[^#]*,", line):
            errors.append(
                f"Python source groups direct imports on one line: {rel}:{line_number}"
            )
        if re.search(r"^\s*(?:async\s+)?def\s+\w+\([^\n]*\)->", line):
            errors.append(
                f"Python function signature omits spacing before return annotation: "
                f"{rel}:{line_number}"
            )
        if "\t" in line:
            errors.append(f"Python source contains a tab indentation character: {rel}:{line_number}")
    if text and not text.endswith("\n"):
        errors.append(f"Python source lacks a final newline: {rel}")

    prose = strip_inline_code(python_human_text(tree, tokens))
    for pattern, preferred in PYTHON_HUMAN_SPELLING.items():
        match = re.search(pattern, prose, flags=re.I)
        if match:
            errors.append(
                f"Python human-facing prose uses {match.group(0)!r}: {rel}; prefer {preferred}"
            )

    if rel.startswith(("core/", "scripts/")):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            candidate = re.sub(r"`[^`]*`", "", node.value)
            for exemption in PYTHON_STRING_EXEMPTIONS:
                candidate = candidate.replace(exemption, "")
            for pattern, preferred in PYTHON_HUMAN_SPELLING.items():
                match = re.search(pattern, candidate, flags=re.I)
                if match:
                    errors.append(
                        f"Python operator-facing string uses {match.group(0)!r}: "
                        f"{rel}:{getattr(node, 'lineno', 1)}; prefer {preferred}"
                    )
                    break

    counts["python_procedures"] += procedure_count
    counts["python_documented_procedures"] += documented_count


def check_path_naming(root: Path, path: Path, rel: str, errors: list[str]) -> None:
    """Enforce documented underscore/hyphen boundaries without renaming governed literals."""
    if path.is_file() and path.suffix == ".py" and not PYTHON_FILENAME_RE.fullmatch(path.name):
        errors.append(f"Python filename is not snake_case: {rel}")
    if path.is_dir() and path.parent == root / "skills":
        if not SKILL_DIRECTORY_RE.fullmatch(path.name):
            errors.append(f"Skill directory is not kebab-case: {rel}")
    if path.is_file() and path.parent == root / "docs" and path.suffix == ".md":
        if not DOC_FILENAME_RE.fullmatch(path.name):
            errors.append(f"Current documentation filename is not uppercase kebab-case: {rel}")


def check_current_text_naming(path: Path, root: Path, rel: str, errors: list[str]) -> None:
    """Reject mixed CLI-option and placeholder separators in current operating prose."""
    is_current_doc = path.parent == root / "docs" or rel in {"README.md", "HELP.md"}
    is_current_skill = rel.startswith("skills/") and "/references/ORIGINAL-" not in f"/{rel}"
    if not (is_current_doc or is_current_skill):
        return
    text = path.read_text(encoding="utf-8")
    option = CLI_UNDERSCORE_RE.search(text)
    if option:
        errors.append(f"CLI option uses underscore instead of hyphen: {rel}: {option.group(0)}")
    placeholder = HYPHENATED_ID_PLACEHOLDER_RE.search(text)
    if placeholder:
        errors.append(
            f"Placeholder uses hyphens instead of underscores: {rel}: {placeholder.group(0)}"
        )

def parse_skill_frontmatter(path: Path) -> dict[str, Any]:
    """Parse Skill YAML frontmatter and require a mapping document."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) != 3:
        raise ValueError("unterminated YAML frontmatter")
    document = yaml.safe_load(parts[1])
    if not isinstance(document, dict):
        raise ValueError("frontmatter is not a mapping")
    return document


def check_all_skills(root: Path, errors: list[str], counts: dict[str, int]) -> None:
    """Validate every provider-neutral routed Skill and its active references."""
    paths = sorted((root / "skills").glob("*/SKILL.md"))
    if len(paths) != 6:
        errors.append(f"Expected 6 registered analytical Skill files, found {len(paths)}")
    forbidden_context = {
        "Cline": "provider-specific Cline instruction",
        "SWITCH TO ACT MODE": "obsolete mode-switch instruction",
        "## Guided Operator input": "controller-only guided-input section",
        "## Natural-language command mapping": "controller-only natural-language routing section",
    }
    for path in paths:
        rel = path.relative_to(root).as_posix()
        try:
            header = parse_skill_frontmatter(path)
        except Exception as exc:  # noqa: BLE001 - audit reports all malformed Skills
            errors.append(f"Invalid Skill frontmatter {rel}: {exc}")
            continue
        if str(header.get("name", "")) != path.parent.name:
            errors.append(f"Skill name/folder mismatch: {rel}")
        if set(header) != {"name", "description"}:
            errors.append(f"Skill frontmatter must contain only name and description: {rel}")
        if not str(header.get("description", "")).strip():
            errors.append(f"Skill description is empty: {rel}")
        agent_path = path.parent / "agents" / "openai.yaml"
        if not agent_path.is_file():
            errors.append(f"Skill UI metadata is missing: {agent_path.relative_to(root).as_posix()}")
        else:
            try:
                agent_doc = yaml.safe_load(agent_path.read_text(encoding="utf-8"))
                interface = agent_doc["interface"]
                if not str(interface.get("display_name", "")).strip():
                    raise ValueError("interface.display_name is empty")
                if not str(interface.get("short_description", "")).strip():
                    raise ValueError("interface.short_description is empty")
            except Exception as exc:  # noqa: BLE001 - audit reports malformed Skill metadata
                errors.append(f"Invalid Skill UI metadata {agent_path.relative_to(root).as_posix()}: {exc}")
        candidates = [path]
        reference_root = path.parent / "references"
        if reference_root.is_dir():
            candidates.extend(
                item
                for item in sorted(reference_root.iterdir())
                if item.is_file()
                and not item.name.startswith("ORIGINAL-")
                and item.name != "RUN-QA.md"
            )
        routed_text = "\n".join(item.read_text(encoding="utf-8") for item in candidates)
        for token, label in {**ROUTED_CONTRACT_FORBIDDEN, **forbidden_context}.items():
            if token in routed_text:
                errors.append(f"{label} remains in routed Skill material: {rel}")
    counts["all_skills"] = len(paths)


def check_documentation_contracts(root: Path, errors: list[str]) -> None:
    """Validate required help files, current release labels, placeholders, and command forms."""
    required = {
        "HELP.md",
        "docs/INDEX.md",
        "docs/BIC-CHEAT-SHEET.md",
        "docs/GOOD-PRACTICE.md",
        "docs/HUMAN-OUTPUT-AND-LOGGING.md",
        "docs/NATURAL-LANGUAGE-COMMAND-ROUTING.md",
        "docs/PROJECT-DOCUMENT-GRAMMAR.md",
        "docs/PROJECT-TREE.md",
        "docs/PYTHON-MAINTENANCE.md",
        "docs/macos-linux/CHEAT-SHEET.md",
        "docs/windows/CHEAT-SHEET.md",
        "docs/macos-linux/RECOVERY.md",
        "docs/windows/RECOVERY.md",
        "docs/macos-linux/ERRORS.md",
        "docs/windows/ERRORS.md",
        "docs/SAW-CHEAT-SHEET.md",
    }
    for rel in sorted(required):
        if not (root / rel).is_file():
            errors.append(f"Missing current help document: {rel}")
    current_paths = [root / "README.md", root / "HELP.md"] + sorted((root / "docs").glob("*.md"))
    for path in current_paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if "{{" in text or "FINAL_COUNT_PENDING" in text:
            errors.append(f"Unresolved documentation placeholder: {path.relative_to(root).as_posix()}")
    version = (root / "VERSION").read_text(encoding="utf-8").strip() if (root / "VERSION").is_file() else ""
    current_operating = [
        root / "README.md",
        root / "HELP.md",
        root / "bic",
        root / "docs" / "macos-linux" / "CHEAT-SHEET.md",
        root / "docs" / "windows" / "CHEAT-SHEET.md",
        root / "docs" / "KNOWN-LIMITATIONS.md",
        root / "docs" / "BIC-CHEAT-SHEET.md",
        root / "docs" / "FULL-PROCESS-FLOW.md",
        root / "workflows" / "bic" / "README.md",
    ]
    current_operating.extend(sorted((root / "skills").glob("*/SKILL.md")))
    for path in current_operating:
        if not path.is_file():
            continue
        current_text = path.read_text(encoding="utf-8")
        if "GRAMMAR-REVIEW-ID" in current_text or "GRAMMAR-DECISION-ID" in current_text:
            errors.append(f"Hyphenated placeholder conflicts with project grammar: {path.relative_to(root).as_posix()}")
        lower = current_text.casefold()
        for phrase in (
            "mandatory human gate",
            "human review receipt authorises progression",
            "operator decision before self-check",
            "requires one governed operator choice",
        ):
            if phrase in lower:
                errors.append(
                    f"Obsolete human progression gate in current material: "
                    f"{path.relative_to(root).as_posix()} ({phrase})"
                )

    try:
        settings = yaml.safe_load((root / "ecosystem.yml").read_text(encoding="utf-8"))
        human_output = settings["human_output"]
        logs = human_output["logs_and_reports"]
        challenges = human_output["translation_challenges"]
        if not logs.get("primary_language") or not challenges.get("primary_language"):
            errors.append("Human-output language channels require independent primary languages")
        if "minimum_individual_urgency" not in challenges:
            errors.append("Translation-challenge configuration omits the materiality threshold")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Invalid human-output configuration: {exc}")

    for platform in ("macos-linux", "windows"):
        cheat = root / "docs" / platform / "CHEAT-SHEET.md"
        recovery = root / "docs" / platform / "RECOVERY.md"
        errors_doc = root / "docs" / platform / "ERRORS.md"
        if not (cheat.is_file() and recovery.is_file() and errors_doc.is_file()):
            continue
        combined = "\n".join(path.read_text(encoding="utf-8") for path in (cheat, recovery, errors_doc))
        for phrase in ("Recovery & diagnostics", "operator-cues.jsonl", "--help"):
            if phrase not in combined:
                errors.append(f"Current {platform} cheat sheets omit required recovery cue: {phrase}")


def has_extension(value: str) -> bool:
    """Return whether a configured file reference includes a filename extension."""
    return bool(Path(value).suffix)


def sha256_file(path: Path) -> str:
    """Hash one file in bounded blocks for registry and provenance checks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def walk_yaml(value: Any, path: str, errors: list[str]) -> None:
    """Recursively inspect YAML values for malformed file references."""
    if isinstance(value, dict):
        for key, child in value.items():
            current = f"{path}.{key}" if path else str(key)
            if key in FILE_KEYS and isinstance(child, str) and child.lower() not in ALLOWED_SENTINELS:
                if not has_extension(child):
                    errors.append(f"File reference lacks extension: {current}={child!r}")
            if key in FILE_LIST_KEYS and isinstance(child, list):
                for index, item in enumerate(child):
                    if isinstance(item, str) and not has_extension(item):
                        errors.append(
                            f"File reference lacks extension: {current}[{index}]={item!r}"
                        )
            walk_yaml(child, current, errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk_yaml(child, f"{path}[{index}]", errors)


def strip_markdown_code(text: str) -> str:
    """Remove fenced and inline code before project-prose spelling checks."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`]*`", "", text)
    return text


def check_markdown(path: Path, root: Path, rel: str, errors: list[str], warnings: list[str]) -> None:
    """Check Markdown fences, local links, and current project spelling conventions."""
    text = path.read_text(encoding="utf-8")
    if text.count("```") % 2:
        errors.append(f"Unbalanced Markdown fence: {rel}")
    for target in LOCAL_LINK_RE.findall(text):
        target = target.strip().split("#", 1)[0]
        if not target or target.startswith(("http://", "https://", "mailto:", "sandbox:", "/")):
            continue
        candidate = (path.parent / target).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            errors.append(f"Markdown link escapes package: {rel} -> {target}")
            continue
        if not candidate.exists():
            errors.append(f"Broken local Markdown link: {rel} -> {target}")
    if "/references/ORIGINAL-" in f"/{rel}" or ("/skills/" in f"/{rel}" and "/references/" in f"/{rel}" and text.startswith("<!-- saw-root-sha256:")):
        return
    prose = strip_markdown_code(text)
    for pattern, preferred in BRITISH_SPELLING.items():
        if re.search(pattern, prose, flags=re.I):
            warnings.append(f"British spelling review: {rel} contains {pattern}; prefer {preferred}")


def run_command(
    command: list[str],
    root: Path,
    label: str,
    errors: list[str],
    *,
    timeout: int = 30,
    accepted_exit_codes: tuple[int, ...] = (0,),
) -> str:
    """Run one bounded audit command and record unexpected exit or timeout failures."""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(root / "core")
    # Audit probes must not create the operational logs they are checking for.
    env["SAGE_DISABLE_OPERATIONAL_LOG"] = "1"
    try:
        result = subprocess.run(
            command,
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        errors.append(f"Command audit failed for {label}: {exc}")
        return ""
    if result.returncode not in accepted_exit_codes:
        errors.append(
            f"Command audit failed for {label} (exit {result.returncode}): "
            f"{(result.stderr or result.stdout).strip()[:500]}"
        )
    return result.stdout + result.stderr


def check_skill_registry(root: Path, errors: list[str], counts: dict[str, int]) -> None:
    """Verify registered Skill paths and hashes against current and original sources."""
    path = root / "meta" / "skills.yml"
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        items = document["skills"]
    except Exception as exc:  # noqa: BLE001 - audit must report all parse errors
        errors.append(f"Invalid Skill registry: {exc}")
        return
    expected = {
        ("bic", "inspect"),
        ("bic", "rewrite"),
        ("bic", "self_check"),
        ("saw", "qa"),
        ("saw", "focused"),
        ("saw", "ol"),
    }
    operations: set[tuple[str, str]] = set()
    for index, item in enumerate(items):
        try:
            operation = (str(item["workflow"]), str(item["operation"]))
            operations.add(operation)
            adapted = root / str(item["file"])
            original = root / str(item["original_file"])
            if not adapted.is_file():
                errors.append(f"Missing adapted Skill: {item['file']}")
            elif sha256_file(adapted) != str(item["adapted_sha256"]):
                errors.append(f"Adapted Skill hash mismatch: {item['id']}")
            if not original.is_file():
                errors.append(f"Missing original Skill/prompt source: {item['original_file']}")
            elif sha256_file(original) != str(item["original_sha256"]):
                errors.append(f"Original Skill/prompt hash mismatch: {item['id']}")
            if str(item.get("qualification_status", "")).upper() != "VALIDATED":
                errors.append(f"Skill qualification is not VALIDATED: {item.get('id', index)}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Invalid Skill registry row {index}: {exc}")
    if operations != expected:
        errors.append(f"Skill operation set mismatch: {sorted(operations)}")
    counts["registered_skills"] = len(items)


def check_commands(root: Path, errors: list[str]) -> None:
    """Exercise launchers once and inspect the public parser grammar without changing state."""
    # Bootstrap/launcher behaviour is covered by dedicated tests. Source audits exercise the
    # packaged application grammar directly so a clean staged tree never needs to create .venv.
    root_help = run_command(
        [sys.executable, "-m", "sage_core.cli", "--help"],
        root,
        "python -m sage_core.cli --help",
        errors,
    )
    if "==SUPPRESS==" in root_help:
        errors.append("Root help exposes suppressed legacy command placeholders")
    for option in ("--quiet", "--verbose", "--debug"):
        if option not in root_help:
            errors.append(f"Root help omits operational log option {option}")

    core_path = str(root / "core")
    inserted = False
    if core_path not in sys.path:
        sys.path.insert(0, core_path)
        inserted = True
    try:
        from sage_core.cli import build_parser  # noqa: PLC0415 - audit imports the packaged parser

        parser = build_parser()
        root_subparsers = next(
            (action for action in parser._actions if isinstance(action, argparse._SubParsersAction)),
            None,
        )
        if root_subparsers is None:
            errors.append("Public CLI parser has no command subparsers")
            command_parsers: dict[str, argparse.ArgumentParser] = {}
        else:
            command_parsers = dict(root_subparsers.choices)

        domains = {
            "request": ("--execute", "--choice", "--advisory"),
            "workspace": ("validate", "initialize", "status", "doctor", "reset-state"),
            "project": ("init", "list"),
            "task": ("create", "execute", "submit", "aggregate", "continue"),
            "memory": ("review",),
            "evaluation": ("plan",),
            "transaction": ("list", "recover"),
            "generation": ("publish", "list", "verify"),
            "workflow": ("status", "plan"),
        }
        for domain, expected in domains.items():
            domain_parser = command_parsers.get(domain)
            if domain_parser is None:
                errors.append(f"Public CLI parser omits domain {domain}")
                continue
            domain_help = domain_parser.format_help()
            nested = next(
                (
                    action
                    for action in domain_parser._actions
                    if isinstance(action, argparse._SubParsersAction)
                ),
                None,
            )
            available_actions = set(nested.choices) if nested is not None else set()
            for expected_item in expected:
                if expected_item.startswith("--"):
                    if expected_item not in domain_help:
                        errors.append(f"Help for domain {domain} omits option {expected_item}")
                elif expected_item not in available_actions:
                    errors.append(f"Help for domain {domain} omits action {expected_item}")
    except Exception as exc:  # noqa: BLE001 - audit reports parser construction failures
        errors.append(f"Cannot inspect public CLI parser grammar: {exc}")
    finally:
        if inserted and sys.path and sys.path[0] == core_path:
            sys.path.pop(0)

    for launcher in ("bic", "saw"):
        if os.name == "nt":
            command = ["cmd.exe", "/d", "/c", str(root / f"{launcher}.cmd"), "--help"]
            label = f"{launcher}.cmd --help"
        else:
            command = [str(root / launcher), "--help"]
            label = f"{launcher} --help"
        output = run_command(command, root, label, errors)
        if "execution is not yet available" in output.lower():
            errors.append(f"{launcher} help contains obsolete execution warning")
    if "workflow bic status" in (root / "bic").read_text(encoding="utf-8"):
        errors.append("bic launcher uses non-canonical command ordering")
    if "workflow saw status" in (root / "saw").read_text(encoding="utf-8"):
        errors.append("saw launcher uses non-canonical command ordering")



def iter_audit_paths(root: Path, mode: str):
    """Yield governed source paths without parsing large derived runtime caches."""
    for directory, dirnames, filenames in os.walk(root):
        directory_path = Path(directory)
        relative_directory = directory_path.relative_to(root)
        if mode == "workspace" and relative_directory.parts and relative_directory.parts[0] in {"cache", "workspace-data"}:
            dirnames[:] = []
            continue
        dirnames[:] = sorted(dirnames)
        for name in sorted(dirnames):
            yield directory_path / name
        for name in sorted(filenames):
            yield directory_path / name


def audit(root: Path, mode: str) -> dict[str, Any]:
    """Run the complete source or populated-workspace audit and return structured evidence."""
    # Collect all independent findings before deciding PASS or FAIL so one defect cannot hide another.
    errors: list[str] = []
    warnings: list[str] = []
    counts = {
        "files": 0,
        "yaml": 0,
        "json": 0,
        "markdown": 0,
        "python": 0,
        "python_procedures": 0,
        "python_documented_procedures": 0,
        "archives": 0,
        "registered_skills": 0,
        "all_skills": 0,
    }
    version = (root / "VERSION").read_text(encoding="utf-8").strip() if (root / "VERSION").is_file() else ""
    current_rc_match = re.search(r"(?i)rc(?P<number>\d+)(?:\.\d+)?", version)
    current_rc_number = int(current_rc_match.group("number")) if current_rc_match else None
    prior_rc_text_re = (
        re.compile(r"(?i)\b(?:0\.01-)?rc(?P<number>\d+)(?:\.\d+)?\b")
        if current_rc_number is not None
        else None
    )
    historical_text_exemptions = {
        "meta/CHANGELOG.md",
        "meta/bic-protected-rewrite-contract.yml",
        "meta/bic-protected-verb-selection-contract.yml",
    }

    for path in iter_audit_paths(root, mode):
        rel = path.relative_to(root).as_posix()
        check_path_naming(root, path, rel, errors)
        if path.is_dir():
            if path.name in FORBIDDEN_DIRS:
                errors.append(f"Forbidden artefact directory: {rel}")
            continue
        counts["files"] += 1
        if (
            path.name in FORBIDDEN_NAMES
            or path.name.startswith("._")
            or path.suffix.lower() in FORBIDDEN_SUFFIXES
        ):
            errors.append(f"Forbidden artefact file: {rel}")
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"sage", "bic", "saw"}:
            check_target_text_vocabulary(path, rel, errors)
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                errors.append(f"Non-UTF-8 text file: {rel}: {exc}")
                continue
            if "\x00" in text:
                errors.append(f"NUL byte in text file: {rel}")
            if prior_rc_text_re is not None and rel not in historical_text_exemptions and "/references/ORIGINAL-" not in f"/{rel}":
                prior_tokens = {
                    match.group(0)
                    for match in prior_rc_text_re.finditer(text)
                    if int(match.group("number")) < current_rc_number
                }
                if prior_tokens:
                    errors.append(
                        f"Previous RC reference in current source text: {rel}: "
                        + ", ".join(sorted(prior_tokens, key=str.casefold))
                    )
        if path.suffix.lower() in {".yml", ".yaml"}:
            counts["yaml"] += 1
            text = path.read_text(encoding="utf-8")
            if "\t" in text:
                errors.append(f"Tab character in YAML: {rel}")
            try:
                document = yaml.safe_load(text)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Invalid YAML {rel}: {exc}")
            else:
                walk_yaml(document, rel, errors)
        elif path.suffix.lower() == ".json":
            counts["json"] += 1
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Invalid JSON {rel}: {exc}")
        elif path.suffix.lower() == ".py":
            counts["python"] += 1
            check_python_maintainability(path, rel, errors, counts)
        elif path.suffix.lower() == ".md":
            counts["markdown"] += 1
            check_markdown(path, root, rel, errors, warnings)
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"sage", "bic", "saw"}:
            check_current_text_naming(path, root, rel, errors)
        if path.suffix.lower() == ".cmd":
            raw = path.read_bytes()
            if b"\r\n" not in raw or raw.replace(b"\r\n", b"").find(b"\n") >= 0:
                errors.append(f"Windows launcher does not use consistent CRLF: {rel}")
        if path.suffix.lower() == ".zip":
            counts["archives"] += 1
            try:
                with zipfile.ZipFile(path) as archive:
                    bad = archive.testzip()
                    names = archive.namelist()
            except (OSError, zipfile.BadZipFile) as exc:
                errors.append(f"Invalid ZIP archive {rel}: {exc}")
            else:
                if bad:
                    errors.append(f"Corrupt ZIP member in {rel}: {bad}")
                for name in names:
                    parts = Path(name).parts
                    if "__MACOSX" in parts or Path(name).name.startswith("._"):
                        errors.append(f"ZIP contains macOS artefact: {rel}:{name}")
        if path.name in {"sage", "bic", "saw"}:
            # Windows uses the paired .cmd launchers and must not require a POSIX shell
            # merely to audit a cross-platform source package. macOS/Linux validate the
            # POSIX entry points with the platform-provided sh implementation.
            if os.name != "nt":
                run_command(["sh", "-n", str(path)], root, f"sh -n {rel}", errors)
                if not os.access(path, os.X_OK):
                    errors.append(f"POSIX launcher is not executable: {rel}")

    required = [
        "VERSION",
        "HELP.md",
        "README.md",
        "docs/INDEX.md",
        "ecosystem.yml",
        "meta/sage.yml",
        "meta/skills.yml",
        "meta/bic-protected-rewrite-contract.yml",
        "meta/bic-protected-verb-selection-contract.yml",
        "meta/contracts/BIC-VERB-SELECTION-POLICY.yml",
        "core/sage_core/semantic/__init__.py",
        "core/sage_core/semantic/store.py",
        "core/sage_core/semantic/policy.py",
        "core/sage_core/semantic/freshness.py",
        "core/sage_core/semantic/semdom.py",
        "core/sage_core/semantic/importers.py",
        "core/sage_core/semantic/indexes.py",
        "core/sage_core/semantic/evidence.py",
        "core/sage_core/semantic/diagnostics.py",
        "core/sage_core/semantic/lift.py",
        "core/sage_core/semantic_cli.py",
        "meta/schemas/semantic-import-manifest.schema.yml",
        "meta/schemas/semantic-index-contract.schema.yml",
        "meta/schemas/semantic-export-manifest.schema.yml",
        "resources/rwc/README.md",
        "resources/rwc/authority/SOURCES.yml",
        "scripts/deep_audit.py",
        "scripts/bootstrap_runtime.py",
        "meta/schemas/act-task.schema.yml",
        "meta/schemas/act-control.schema.yml",
        "meta/schemas/bic-grammar-assessment.schema.yml",
        "meta/schemas/saw-findings.schema.yml",
        "core/sage_core/human_output.py",
    ]
    for rel in required:
        if not (root / rel).is_file():
            errors.append(f"Missing required file: {rel}")

    check_bic_protected_rewrite_contract(root, errors)
    check_bic_protected_verb_selection_contract(root, errors)
    check_skill_registry(root, errors, counts)
    check_all_skills(root, errors, counts)
    check_documentation_contracts(root, errors)
    check_commands(root, errors)

    if mode == "source":
        validation_command = [
            sys.executable,
            "-m",
            "sage_core.cli",
            "--no-prompt",
            "workspace",
            "validate",
            "--package",
        ]
        validation_label = "python -m sage_core.cli workspace validate --package"
        accepted_validation_markers = ("Status: READY",)
    else:
        settings = root / "ecosystem.resource-test.yml"
        validation_command = [sys.executable, "-m", "sage_core.cli"]
        if settings.is_file():
            validation_command.extend(["--settings", str(settings)])
        validation_command.extend(["--no-prompt", "workspace", "validate"])
        validation_label = "python -m sage_core.cli workspace validate (non-interactive)"
        accepted_validation_markers = ("Status: READY", "Result: INPUT_REQUIRED")
    validation_output = run_command(
        validation_command,
        root,
        validation_label,
        errors,
        timeout=60,
        accepted_exit_codes=(0, 2) if mode != "source" else (0,),
    )
    if not any(marker in validation_output for marker in accepted_validation_markers):
        errors.append("Static workspace validation did not report READY or governed INPUT_REQUIRED")

    if mode == "source":
        scripture = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in SCRIPTURE_SUFFIXES
        ]
        if scripture:
            errors.append(f"Clean source contains Scripture payloads: {len(scripture)}")
        archives = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*.zip")
            if path.is_file()
        ]
        if archives:
            errors.append(f"Clean source contains nested archives: {', '.join(archives[:10])}")
        cache_root = root / "cache"
        if cache_root.exists():
            payloads = [p for p in cache_root.rglob("*") if p.is_file() and p.name != ".gitkeep"]
            if payloads:
                errors.append("Clean source contains runtime data under cache/")
        workspace_root = root / "workspace-data"
        if workspace_root.exists():
            allowed_seed = workspace_root / "scripture-projects" / "README.md"
            payloads = [
                p for p in workspace_root.rglob("*")
                if p.is_file() and p.name != ".gitkeep" and p.resolve() != allowed_seed.resolve()
            ]
            if payloads:
                errors.append("Clean source contains runtime data under workspace-data/")
    elif mode == "workspace":
        try:
            settings = yaml.safe_load((root / "ecosystem.yml").read_text(encoding="utf-8"))
            if not isinstance(settings, dict):
                errors.append("Workspace ecosystem.yml is not a mapping")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Cannot inspect workspace configuration: {exc}")

    return {
        "status": "PASS" if not errors and not warnings else "FAIL",
        "version": version,
        "mode": mode,
        "root": str(root),
        "counts": counts,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
    }


def render_markdown(result: dict[str, Any]) -> str:
    """Render the structured audit result as a concise human-readable report."""
    lines = [
        "# SAGE Deep Audit Report",
        "",
        f"- Status: **{result['status']}**",
        f"- Version: `{result['version']}`",
        f"- Mode: `{result['mode']}`",
        f"- Root: `{result['root']}`",
        f"- Files: {result['counts']['files']}",
        f"- YAML files: {result['counts']['yaml']}",
        f"- JSON files: {result['counts']['json']}",
        f"- Markdown files: {result['counts']['markdown']}",
        f"- Python files: {result['counts']['python']}",
        f"- Documented Python procedures: {result['counts']['python_documented_procedures']}/{result['counts']['python_procedures']}",
        f"- Registered analytical Skills: {result['counts']['registered_skills']}",
        "",
        "## Errors",
        "",
    ]
    lines.extend(f"- {item}" for item in result["errors"])
    if not result["errors"]:
        lines.append("None.")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {item}" for item in result["warnings"])
    if not result["warnings"]:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def main() -> int:
    """Run the command-line entry point and return its process status."""
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("--mode", choices=("source", "workspace"), required=True)
    parser.add_argument("--json-output")
    parser.add_argument("--markdown-output")
    args = parser.parse_args()
    result = audit(Path(args.root).resolve(), args.mode)
    if args.json_output:
        Path(args.json_output).write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.markdown_output:
        Path(args.markdown_output).write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
