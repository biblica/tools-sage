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
import unicodedata
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
LOCAL_ENVIRONMENT_DIRS = {".git", ".venv"}
WINDOWS_RESERVED_BASENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
WINDOWS_ILLEGAL_COMPONENT_CHARS = set('<>:"\\|?*')
WINDOWS_RELATIVE_PATH_BUDGET = 180
POSIX_EXECUTABLE_MEMBERS = {
    "sage-python",
    "system/bin/sage",
    "system/bin/bic",
    "system/bin/saw",
    "system/tools/clone_and_install.sh",
}
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
BUNDLED_OL_ROOTS = {
    "system/resources/scripture/original-language/grk",
    "system/resources/scripture/original-language/heb",
}
TEXT_SUFFIXES = {".md", ".txt", ".yml", ".yaml", ".json", ".py", ".sh", ".ps1", ".cmd"}
CURRENT_DOCS = {"README.md", "docs/OPERATOR-GUIDE.md"}
CURRENT_ANALYSIS_IDENTITY_FILES = {
    "system/config/DEVELOPMENT-STATUS.md",
    "system/config/NEXT-DEVELOPMENT-WORK.md",
    "system/config/localization/README.md",
    "system/config/project-management/RELEASE-CLEANUP.md",
    "system/config/project-management/TODO.md",
}
CURRENT_ANALYSIS_SKILLS = {"bic-inspect", "bic-rewrite", "bic-self-check", "rtc", "stc"}
RETIRED_ANALYSIS_IDENTITY_RE = re.compile(r"\bSAW(?:_|\b)")
US_SPELLING = {
    r"\banalyse\b": "analyze",
    r"\banalysed\b": "analyzed",
    r"\banalyses\b": "analyzes",
    r"\banalysing\b": "analyzing",
    r"\bauthorisation\b": "authorization",
    r"\bauthorise\b": "authorize",
    r"\bauthorised\b": "authorized",
    r"\bauthorises\b": "authorizes",
    r"\bauthorising\b": "authorizing",
    r"\bbehaviour\b": "behavior",
    r"\bbehaviours\b": "behaviors",
    r"\bcapitalisation\b": "capitalization",
    r"\bcapitalise\b": "capitalize",
    r"\bcapitalised\b": "capitalized",
    r"\bfinalisation\b": "finalization",
    r"\bfinalise\b": "finalize",
    r"\bfinalised\b": "finalized",
    r"\bfinalises\b": "finalizes",
    r"\bfinalising\b": "finalizing",
    r"\binitialisation\b": "initialization",
    r"\binitialise\b": "initialize",
    r"\binitialised\b": "initialized",
    r"\binitialises\b": "initializes",
    r"\binitialising\b": "initializing",
    r"\bnormalisation\b": "normalization",
    r"\bnormalise\b": "normalize",
    r"\bnormalised\b": "normalized",
    r"\bnormalises\b": "normalizes",
    r"\bnormalising\b": "normalizing",
    r"\borganisation\b": "organization",
    r"\borganisations\b": "organizations",
    r"\borganise\b": "organize",
    r"\borganised\b": "organized",
    r"\borganises\b": "organizes",
    r"\borganising\b": "organizing",
    r"\brecognise\b": "recognize",
    r"\brecognised\b": "recognized",
    r"\brecognises\b": "recognizes",
    r"\brecognising\b": "recognizing",
    r"\bjudgement\b": "judgment",
    r"\blicence\b": "license",
    r"\blicenced\b": "licensed",
    r"\blicencing\b": "licensing",
    r"\bartefact\b": "artifact",
    r"\bartefacts\b": "artifacts",
    r"\bcatalogue\b": "catalog",
    r"\bcatalogued\b": "cataloged",
    r"\bcataloguing\b": "cataloging",
    r"\blocalisation\b": "localization",
    r"\blocalise\b": "localize",
    r"\blocalised\b": "localized",
    r"\blocalises\b": "localizes",
    r"\blocalising\b": "localizing",
    r"\bserialise\b": "serialize",
    r"\bserialised\b": "serialized",
    r"\bserialises\b": "serializes",
    r"\bserialising\b": "serializing",
    r"\bdecontextualise\b": "decontextualize",
    r"\bdecontextualised\b": "decontextualized",
    r"\bdecontextualises\b": "decontextualizes",
    r"\bdecontextualising\b": "decontextualizing",
    r"\bjournalled\b": "journaled",
    r"\bjournalling\b": "journaling",
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
    r"\banalys(?:e|ed|es|ing)\b": "analyze",
    r"\bauthoris(?:e|ed|es|ing|ation)\b": "authorize/authorization",
    r"\bbehaviour(?:s)?\b": "behavior",
    r"\bcapitalis(?:e|ed|es|ing|ation)\b": "capitalize/capitalization",
    r"\bfinalis(?:e|ed|es|ing|ation)\b": "finalize/finalization",
    r"\binitialis(?:e|ed|es|ing|ation)\b": "initialize/initialization",
    r"\bnormalis(?:e|ed|es|ing|ation)\b": "normalize/normalization",
    r"\borganis(?:e|ed|es|ing|ation|ations)\b": "organize/organization",
    r"\brecognis(?:e|ed|es|ing)\b": "recognize",
    r"\bjudgement\b": "judgment",
    r"\blicen(?:ce|ced|cing)\b": "license/licensed/licensing",
    r"\bartefacts?\b": "artifact/artifacts",
    r"\bcatalogu(?:e|ed|es|ing)\b": "catalog",
    r"\blocalis(?:e|ed|es|ing|ation)\b": "localize/localization",
    r"\bserialis(?:e|ed|es|ing|ation|able)\b": "serialize/serialization",
    r"\bdecontextualis(?:e|ed|es|ing|ation)\b": "decontextualize",
    r"\bjournalled\b": "journaled",
    r"\bjournalling\b": "journaling",
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
SAGE_CONFIG_FILENAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*(?:\.schema)?\.(?:yml|json)$")
SYSTEM_DOC_FILENAME_RE = re.compile(r"[A-Z0-9]+(?:-[A-Z0-9]+)*\.md$")
CLI_UNDERSCORE_RE = re.compile(r"--[a-z0-9-]*_[a-z0-9_-]*")
HYPHENATED_ID_PLACEHOLDER_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-ID\b")
PROHIBITED_TARGET_TEXT_VERB_RE = re.compile(
    r"\b(?:translate|translated|translates|translating)\b", re.IGNORECASE
)
PRIVATE_INPUT_ALIAS_START = "# BEGIN PRIVATE OPERATOR INPUT ALIASES"
PRIVATE_INPUT_ALIAS_END = "# END PRIVATE OPERATOR INPUT ALIASES"
VOCABULARY_IMPLEMENTATION_EXEMPTIONS = {
    "system/src/sage/vocabulary.py",
    "system/tools/deep_audit.py",
        "system/tools/bootstrap_runtime.py",
}


ROUTED_CONTRACT_FORBIDDEN = {
    "system/tools/bic.py": "obsolete BIC script command",
    "./saw run": "obsolete SAW controller command",
    "system/config/saw.yml": "obsolete SAW metadata path",
    "output/audit/current-stage-prompt.md": "obsolete SAW prompt path",
    "workflow-system/": "obsolete BIC workflow-system path",
    "operator-files/": "obsolete BIC operator-files path",
    "project-system/resources/project-grammar.yml": "obsolete project-grammar path",
    "docs/internal/": "obsolete internal documentation path",
}



def strip_inline_code(text: str) -> str:
    """Remove backtick-delimited literals before prose-only language checks."""
    return re.sub(r"`[^`]*`", "", text)


def _remove_private_input_aliases(text: str, rel: str, errors: list[str]) -> str:
    """Remove the one governed private input-lexicon block before emitted-vocabulary checks."""
    if rel != "system/src/sage/natural_language.py":
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
        or "tests" in parts
        or (parts and parts[0] in {"projects", "cache", "workspace_data"})
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


def check_retired_analysis_identity(path: Path, rel: str, errors: list[str]) -> None:
    """Reject the retired umbrella identity from current operating and Skill material."""
    parts = Path(rel).parts
    current_skill = (
        len(parts) >= 4
        and parts[:2] == ("system", "skills")
        and parts[2] in CURRENT_ANALYSIS_SKILLS
        and not path.name.startswith(("ORIGINAL-", "LEGACY-"))
    )
    if rel not in CURRENT_ANALYSIS_IDENTITY_FILES and not current_skill:
        return
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    if RETIRED_ANALYSIS_IDENTITY_RE.search(rel) or RETIRED_ANALYSIS_IDENTITY_RE.search(text):
        errors.append(f"Retired SAW identity in current operating material: {rel}")


def check_bic_protected_rewrite_contract(root: Path, errors: list[str]) -> None:
    """Verify the pinned BIC 4 protected contract and every routed active mirror."""
    pin_path = root / "system" / "config" / "bic-protected-rewrite-pin.json"
    if not pin_path.is_file():
        errors.append("Missing pinned BIC protected rewrite contract metadata")
        return
    try:
        raw = json.loads(pin_path.read_text(encoding="utf-8"))
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
    pin_path = root / "system" / "config" / "bic-protected-verb-selection-pin.json"
    if not pin_path.is_file():
        errors.append("Missing pinned BIC protected verb-selection contract metadata")
        return
    try:
        raw = json.loads(pin_path.read_text(encoding="utf-8"))
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

    if rel.startswith(("system/src/", "system/tools/")):
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
    """Enforce governed naming plus Windows-compatible path-component rules."""
    relative = path.relative_to(root)
    for component in relative.parts:
        if component.endswith((" ", ".")):
            errors.append(f"Windows-invalid trailing space/dot in path component: {rel}")
        if any(char in WINDOWS_ILLEGAL_COMPONENT_CHARS or ord(char) < 32 for char in component):
            errors.append(f"Windows-invalid character in path component: {rel}")
        if component.split(".", 1)[0].upper() in WINDOWS_RESERVED_BASENAMES:
            errors.append(f"Windows-reserved device name in path component: {rel}")
        if len(component) > 255:
            errors.append(f"Path component exceeds 255 characters: {rel}")
    if len(rel) > WINDOWS_RELATIVE_PATH_BUDGET:
        errors.append(
            f"Relative path exceeds Windows portability budget {WINDOWS_RELATIVE_PATH_BUDGET}: {rel}"
        )
    if path.is_file() and path.suffix == ".py" and not PYTHON_FILENAME_RE.fullmatch(path.name):
        errors.append(f"Python filename is not snake_case: {rel}")
    if path.is_dir() and path.parent == root / "system" / "skills":
        if not SKILL_DIRECTORY_RE.fullmatch(path.name):
            errors.append(f"Skill directory is not kebab-case: {rel}")
    if path.is_file() and path.parent == root / "docs" and path.suffix == ".md":
        if not DOC_FILENAME_RE.fullmatch(path.name):
            errors.append(f"Current documentation filename is not uppercase kebab-case: {rel}")
    if path.is_file() and path.suffix.lower() in {".yml", ".json"}:
        try:
            path.relative_to(root / "system" / "config")
        except ValueError:
            pass
        else:
            if not SAGE_CONFIG_FILENAME_RE.fullmatch(path.name):
                errors.append(f"SAGE config filename is not lowercase kebab-case: {rel}")
    if path.is_file() and path.parent == root / "system" / "tools" and path.suffix == ".md":
        if not SYSTEM_DOC_FILENAME_RE.fullmatch(path.name):
            errors.append(f"System tool document filename is not uppercase kebab-case: {rel}")
    if path.is_file() and "/references/" in f"/{rel}" and path.suffix == ".md":
        if not SYSTEM_DOC_FILENAME_RE.fullmatch(path.name):
            errors.append(f"Skill reference filename is not uppercase kebab-case: {rel}")


def check_current_text_naming(path: Path, root: Path, rel: str, errors: list[str]) -> None:
    """Reject mixed CLI-option and placeholder separators in current operating prose."""
    is_current_doc = path.parent == root / "docs" or rel in {"README.md", "docs/OPERATOR-GUIDE.md"}
    is_current_skill = rel.startswith("system/skills/") and "/references/ORIGINAL-" not in f"/{rel}"
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
    paths = sorted((root / "system" / "skills").glob("*/SKILL.md"))
    if len(paths) != 9:
        errors.append(f"Expected 9 governed analytical Skill files, found {len(paths)}")
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
                and not item.name.startswith("LEGACY-")
                and item.name != "RUN-RTC.md"
            )
        routed_text = "\n".join(item.read_text(encoding="utf-8") for item in candidates)
        for token, label in {**ROUTED_CONTRACT_FORBIDDEN, **forbidden_context}.items():
            if token in routed_text:
                errors.append(f"{label} remains in routed Skill material: {rel}")
    counts["all_skills"] = len(paths)


def check_documentation_contracts(root: Path, errors: list[str]) -> None:
    """Validate required help files, current release labels, placeholders, and command forms."""
    required = {
        "docs/OPERATOR-GUIDE.md",
        "docs/INDEX.md",
        "docs/advanced/architecture/FILE-NAMING-AND-SERIALIZATION.md",
        "docs/BIC-CHEAT-SHEET.md",
        "docs/GOOD-PRACTICE.md",
        "docs/advanced/architecture/HUMAN-OUTPUT-AND-LOGGING.md",
        "docs/advanced/workflows/NATURAL-LANGUAGE-COMMAND-ROUTING.md",
        "docs/advanced/architecture/SAGE-SYSTEM-GRAMMAR.md",
        "docs/advanced/maintenance/PURPOSE-FUNCTION-DRIFT-REPORT.md",
        "docs/advanced/architecture/PROJECT-TREE.md",
        "docs/advanced/maintenance/PYTHON-MAINTENANCE.md",
        "docs/macos-linux/CHEAT-SHEET.md",
        "docs/windows/CHEAT-SHEET.md",
        "docs/macos-linux/RECOVERY.md",
        "docs/windows/RECOVERY.md",
        "docs/macos-linux/ERRORS.md",
        "docs/windows/ERRORS.md",
        "docs/RTC-STC-CHEAT-SHEET.md",
    }
    for rel in sorted(required):
        if not (root / rel).is_file():
            errors.append(f"Missing current help document: {rel}")
    current_paths = [root / "README.md", *sorted((root / "docs").rglob("*.md"))]
    for path in current_paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if "{{" in text or "FINAL_COUNT_PENDING" in text:
            errors.append(f"Unresolved documentation placeholder: {path.relative_to(root).as_posix()}")
    version = (root / "VERSION").read_text(encoding="utf-8").strip() if (root / "VERSION").is_file() else ""
    current_operating = [
        root / "README.md",
        root / "docs/OPERATOR-GUIDE.md",
        root / "system" / "bin" / "bic",
        root / "docs" / "macos-linux" / "CHEAT-SHEET.md",
        root / "docs" / "windows" / "CHEAT-SHEET.md",
        root / "docs" / "KNOWN-LIMITATIONS.md",
        root / "docs" / "BIC-CHEAT-SHEET.md",
        root / "docs" / "advanced" / "workflows" / "FULL-PROCESS-FLOW.md",
        root / "system" / "config" / "workflows" / "bic" / "README.md",
    ]
    current_operating.extend(sorted((root / "system" / "skills").glob("*/SKILL.md")))
    for path in current_operating:
        if not path.is_file():
            continue
        current_text = path.read_text(encoding="utf-8")
        if "GRAMMAR-REVIEW-ID" in current_text or "GRAMMAR-DECISION-ID" in current_text:
            errors.append(f"Hyphenated placeholder conflicts with SAGE system grammar: {path.relative_to(root).as_posix()}")
        lower = current_text.casefold()
        for phrase in (
            "mandatory human gate",
            "human review receipt authorizes progression",
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
        for phrase in (
            "Recovery and diagnostics",
            "SAGE Maintenance",
            "operator-cues.jsonl",
            "--help",
        ):
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
    if "/references/ORIGINAL-" in f"/{rel}" or ("/system/skills/" in f"/{rel}" and "/references/" in f"/{rel}" and text.startswith("<!-- saw-root-sha256:")):
        return
    prose = strip_markdown_code(text)
    for pattern, preferred in US_SPELLING.items():
        if re.search(pattern, prose, flags=re.I):
            warnings.append(f"U.S. spelling review: {rel} contains {pattern}; prefer {preferred}")


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
    env["PYTHONPATH"] = str(root / "system" / "src")
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
    path = root / "system" / "config" / "skills.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        items = document["skills"]
    except Exception as exc:  # noqa: BLE001 - audit must report all parse errors
        errors.append(f"Invalid Skill registry: {exc}")
        return
    expected = {
        ("bic", "inspect"),
        ("bic", "rewrite"),
        ("bic", "self_check"),
        ("rtc", "rtc"),
        ("stc", "stc"),
        ("saw", "rtc"),
        ("saw", "stc"),
        ("saw", "focused"),
        ("saw", "ol"),
    }
    if not isinstance(items, dict):
        errors.append("Skill registry skills must be a mapping keyed by Skill ID")
        return
    operations: set[tuple[str, str]] = set()
    for skill_id, item in items.items():
        try:
            operation = (str(item["workflow"]), str(item["operation"]))
            operations.add(operation)
            adapted = root / str(item["file"])
            original = root / str(item["original_file"])
            if not adapted.is_file():
                errors.append(f"Missing adapted Skill: {item['file']}")
            elif sha256_file(adapted) != str(item["adapted_sha256"]):
                errors.append(f"Adapted Skill hash mismatch: {skill_id}")
            if not original.is_file():
                errors.append(f"Missing original Skill/prompt source: {item['original_file']}")
            elif sha256_file(original) != str(item["original_sha256"]):
                errors.append(f"Original Skill/prompt hash mismatch: {skill_id}")
            if str(item.get("qualification_status", "")).upper() != "VALIDATED":
                errors.append(f"Skill qualification is not VALIDATED: {skill_id}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Invalid Skill registry row {skill_id}: {exc}")
    if operations != expected:
        errors.append(f"Skill operation set mismatch: {sorted(operations)}")
    counts["registered_skills"] = len(items)


def check_qualification_baselines(root: Path, errors: list[str]) -> None:
    """Validate the governed external qualification-baseline registry."""
    path = root / "system" / "config" / "qualification-baselines.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        baselines = document["baselines"]
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Invalid qualification baseline registry: {exc}")
        return
    if not isinstance(baselines, dict) or not baselines:
        errors.append("Qualification baseline registry must contain a non-empty baselines mapping")
        return
    for baseline_id, record in baselines.items():
        if not isinstance(baseline_id, str) or not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", baseline_id):
            errors.append(f"Invalid qualification baseline ID: {baseline_id!r}")
            continue
        if not isinstance(record, dict):
            errors.append(f"Qualification baseline record is not a mapping: {baseline_id}")
            continue
        filename = record.get("file")
        digest = str(record.get("sha256", "")).lower()
        if not isinstance(filename, str) or not filename.strip():
            errors.append(f"Qualification baseline file is missing: {baseline_id}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            errors.append(f"Qualification baseline SHA-256 is invalid: {baseline_id}")


def check_commands(root: Path, errors: list[str]) -> None:
    """Exercise launchers once and inspect the public parser grammar without changing state."""
    # Bootstrap/launcher behavior is covered by dedicated tests. Source audits exercise the
    # packaged application grammar directly so a clean staged tree never needs to create .venv.
    root_help = run_command(
        [sys.executable, "-m", "sage.cli", "--help"],
        root,
        "python -m sage.cli --help",
        errors,
    )
    if "==SUPPRESS==" in root_help:
        errors.append("Root help exposes suppressed legacy command placeholders")
    for option in ("--quiet", "--verbose", "--debug"):
        if option not in root_help:
            errors.append(f"Root help omits operational log option {option}")

    core_path = str(root / "system" / "src")
    inserted = False
    if core_path not in sys.path:
        sys.path.insert(0, core_path)
        inserted = True
    try:
        from sage.cli import build_parser  # noqa: PLC0415 - audit imports the packaged parser

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
            command = ["cmd.exe", "/d", "/c", str(root / "system" / "bin" / f"{launcher}.cmd"), "--help"]
            label = f"{launcher}.cmd --help"
        else:
            command = [str(root / "system" / "bin" / launcher), "--help"]
            label = f"{launcher} --help"
        output = run_command(command, root, label, errors)
        if "execution is not yet available" in output.lower():
            errors.append(f"{launcher} help contains obsolete execution warning")
    if "workflow bic status" in (root / "system" / "bin" / "bic").read_text(encoding="utf-8"):
        errors.append("bic launcher uses non-canonical command ordering")
    if "workflow saw status" in (root / "system" / "bin" / "saw").read_text(encoding="utf-8"):
        errors.append("saw launcher uses non-canonical command ordering")



def iter_audit_paths(root: Path, mode: str):
    """Yield governed source paths without parsing large derived runtime caches."""
    for directory, dirnames, filenames in os.walk(root):
        directory_path = Path(directory)
        relative_directory = directory_path.relative_to(root)
        if relative_directory == Path("."):
            dirnames[:] = [name for name in dirnames if name not in LOCAL_ENVIRONMENT_DIRS]
        if mode == "workspace" and relative_directory.parts and relative_directory.parts[0] in {"cache", "workspace_data"}:
            dirnames[:] = []
            continue
        dirnames[:] = sorted(dirnames)
        for name in sorted(dirnames):
            yield directory_path / name
        for name in sorted(filenames):
            yield directory_path / name


def _is_future_prerelease_target(token: str, current: str, line: str) -> bool:
    """Allow later prerelease labels only in an explicit planning/deferral line."""
    pattern = re.compile(
        r"(?i)^(\d+)\.(\d+)(?:-?(?:alpha|beta|dev)\d*(?:\.\d+)?|-?rc\d+(?:\.\d+)?)$"
    )
    candidate = pattern.fullmatch(token)
    active = pattern.fullmatch(current)
    if candidate is None or active is None:
        return False
    candidate_lineage = (int(candidate.group(1)), int(candidate.group(2)))
    active_lineage = (int(active.group(1)), int(active.group(2)))
    planning = line.casefold()
    markers = ("defer", "resume", "resumption", "paused until", "planned for", "future")
    return candidate_lineage > active_lineage and any(marker in planning for marker in markers)


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
    current_pre_release = version.casefold()
    current_rc_match = re.search(r"(?i)rc\d+(?:\.\d+)?", version)
    current_rc_token = current_rc_match.group(0).casefold() if current_rc_match else None
    pre_release_text_re = re.compile(
        r"(?i)\b(?:\d+\.\d+(?:-?(?:alpha|beta|dev)(?:\d+(?:\.\d+)?)?|-?rc\d+(?:\.\d+)?)|rc\d+(?:\.\d+)?)\b"
    )
    historical_text_exemptions = {
        "docs/advanced/maintenance/HARDENING-AND-CONTEXT-REFINEMENT.md",
        "docs/advanced/release/IMPLEMENTATION-REPORT.md",
        "docs/advanced/release/ADMINISTRATIVE-AI-ROUTING-DESIGN.md",
        "docs/advanced/release/PROVISIONAL-MEDIUM-SKILL-ROUTING-DESIGN.md",
        "docs/advanced/release/PROVISIONAL-MEDIUM-SKILL-ROUTING-IMPLEMENTATION-PLAN.md",
        "docs/advanced/release/SAW-REVIEW-PORTIONS-AND-OL-REFERRAL-DESIGN.md",
        "docs/advanced/release/SAW-REVIEW-PORTIONS-AND-OL-REFERRAL-IMPLEMENTATION-PLAN.md",
        "docs/advanced/release/SKILL-ROUTING-IMPLEMENTATION-PLAN.md",
        "docs/advanced/maintenance/MACOS-LINUX-PATH-EXECUTION-REPORT.md",
        "docs/advanced/maintenance/WINDOWS-CODEX-EXECUTION-AUDIT.md",
        "system/config/project-management/IMPLEMENTED-UPDATES.md",
        "system/config/project-management/MILESTONES.md",
        "system/config/project-management/VERSIONING-POLICY.md",
        "docs/advanced/release/RELEASE-NOTES.md",
        "docs/advanced/release/TEST-AND-VALIDATION-REPORT.md",
        "system/config/CHANGELOG.md",
        "system/config/bic-protected-rewrite-pin.json",
        "system/config/bic-protected-verb-selection-pin.json",
        "system/config/skills.json",
        "system/src/sage/usj.py",
    }
    windows_case_paths: dict[str, str] = {}
    macos_normalized_paths: dict[str, str] = {}

    for path in iter_audit_paths(root, mode):
        rel = path.relative_to(root).as_posix()
        folded_path = rel.casefold()
        prior_path = windows_case_paths.get(folded_path)
        if prior_path is not None and prior_path != rel:
            errors.append(f"Windows case-insensitive path collision: {prior_path} / {rel}")
        windows_case_paths[folded_path] = rel
        macos_key = unicodedata.normalize("NFD", rel).casefold()
        prior_macos_path = macos_normalized_paths.get(macos_key)
        if prior_macos_path is not None and prior_macos_path != rel:
            errors.append(f"macOS normalized/case-insensitive path collision: {prior_macos_path} / {rel}")
        macos_normalized_paths[macos_key] = rel
        check_path_naming(root, path, rel, errors)
        if path.is_dir():
            if path.name in FORBIDDEN_DIRS:
                errors.append(f"Forbidden artifact directory: {rel}")
            continue
        counts["files"] += 1
        if os.name != "nt" and os.access(path, os.X_OK) and rel not in POSIX_EXECUTABLE_MEMBERS:
            errors.append(f"Unexpected executable bit on non-launcher file: {rel}")
        if (
            path.name in FORBIDDEN_NAMES
            or path.name.startswith("._")
            or path.suffix.lower() in FORBIDDEN_SUFFIXES
        ):
            errors.append(f"Forbidden artifact file: {rel}")
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"sage", "sage-python", "bic", "saw"}:
            check_target_text_vocabulary(path, rel, errors)
            check_retired_analysis_identity(path, rel, errors)
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                errors.append(f"Non-UTF-8 text file: {rel}: {exc}")
                continue
            if "\x00" in text:
                errors.append(f"NUL byte in text file: {rel}")
            if (
                rel not in historical_text_exemptions
                and not rel.startswith("system/tests/")
                and "/references/ORIGINAL-" not in f"/{rel}"
            ):
                stale_tokens: set[str] = set()
                for match in pre_release_text_re.finditer(text):
                    token = match.group(0)
                    if token.casefold() in {current_pre_release, current_rc_token}:
                        continue
                    line_start = text.rfind("\n", 0, match.start()) + 1
                    line_end = text.find("\n", match.end())
                    line = text[line_start:] if line_end < 0 else text[line_start:line_end]
                    historical_branch_lineage = (
                        rel == "docs/advanced/release/HANDOVER.md"
                        and "historical" in line.casefold()
                        and "non-release" in line.casefold()
                        and "alpha/" in line.casefold()
                        and version in line
                    )
                    if historical_branch_lineage:
                        continue
                    if _is_future_prerelease_target(token, version, line):
                        continue
                    stale_tokens.add(token)
                if stale_tokens:
                    errors.append(
                        f"Previous pre-release reference in current source text: {rel}: "
                        + ", ".join(sorted(stale_tokens, key=str.casefold))
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
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {"sage", "sage-python", "bic", "saw"}:
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
                        errors.append(f"ZIP contains macOS artifact: {rel}:{name}")
        if path.name in {"sage", "sage-python", "bic", "saw"}:
            # Windows uses the paired .cmd launchers and must not require a POSIX shell
            # merely to audit a cross-platform source package. macOS/Linux validate the
            # POSIX entry points with the platform-provided sh implementation.
            if os.name != "nt":
                run_command(["sh", "-n", str(path)], root, f"sh -n {rel}", errors)
                if not os.access(path, os.X_OK):
                    errors.append(f"POSIX launcher is not executable: {rel}")

    required = [
        "VERSION",
        "docs/OPERATOR-GUIDE.md",
        "README.md",
        "system/pyproject.toml",
        "system/bin/sage",
        "system/bin/sage.cmd",
        "system/bin/bic",
        "system/bin/bic.cmd",
        "system/bin/saw",
        "system/bin/saw.cmd",
        "docs/INDEX.md",
        "docs/advanced/architecture/FILE-NAMING-AND-SERIALIZATION.md",
        "ecosystem.yml",
        "system/config/sage-standard.json",
        "system/config/python-runtime.json",
        "system/config/skills.json",
        "system/config/qualification-baselines.json",
        "system/config/bic-protected-rewrite-pin.json",
        "system/config/bic-protected-verb-selection-pin.json",
        "system/config/contracts/bic-verb-selection-policy.yml",
        "system/src/sage/semantic/__init__.py",
        "system/src/sage/semantic/authority_registry.py",
        "system/src/sage/semantic/store.py",
        "system/src/sage/semantic/policy.py",
        "system/src/sage/semantic/freshness.py",
        "system/src/sage/semantic/semdom.py",
        "system/src/sage/semantic/importers.py",
        "system/src/sage/semantic/indexes.py",
        "system/src/sage/semantic/evidence.py",
        "system/src/sage/semantic/diagnostics.py",
        "system/src/sage/semantic/lift.py",
        "system/src/sage/semantic_cli.py",
        "system/config/schemas/semantic-import-manifest.schema.yml",
        "system/config/schemas/semantic-index-contract.schema.yml",
        "system/config/schemas/semantic-export-manifest.schema.yml",
        "system/resources/rwc/README.md",
        "system/resources/rwc/authority/sources.json",
        "system/tools/deep_audit.py",
        "system/tools/bootstrap_runtime.py",
        "system/tools/bootstrap_python.sh",
        "system/tools/bootstrap_python.ps1",
        "system/config/schemas/act-task.schema.yml",
        "system/config/schemas/act-control.schema.yml",
        "system/config/schemas/bic-grammar-assessment.schema.yml",
        "system/config/schemas/saw-findings.schema.yml",
        "system/src/sage/human_output.py",
    ]
    for rel in required:
        if not (root / rel).is_file():
            errors.append(f"Missing required file: {rel}")

    check_bic_protected_rewrite_contract(root, errors)
    check_bic_protected_verb_selection_contract(root, errors)
    check_skill_registry(root, errors, counts)
    check_qualification_baselines(root, errors)
    check_all_skills(root, errors, counts)
    check_documentation_contracts(root, errors)
    check_commands(root, errors)

    if mode == "source":
        validation_command = [
            sys.executable,
            "-m",
            "sage.cli",
            "--no-prompt",
            "workspace",
            "validate",
            "--package",
        ]
        validation_label = "python -m sage.cli workspace validate --package"
        accepted_validation_markers = ("Status: READY",)
    else:
        settings = root / "ecosystem.resource-test.yml"
        validation_command = [sys.executable, "-m", "sage.cli"]
        if settings.is_file():
            validation_command.extend(["--settings", str(settings)])
        validation_command.extend(["--no-prompt", "workspace", "validate"])
        validation_label = "python -m sage.cli workspace validate (non-interactive)"
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
        unexpected_scripture = [
            relative
            for relative in scripture
            if str(Path(relative).parent).replace("\\", "/") not in BUNDLED_OL_ROOTS
            or Path(relative).suffix.lower() != ".sfm"
        ]
        if unexpected_scripture:
            errors.append(
                "Clean source contains Scripture outside governed bundled OL resources: "
                + ", ".join(unexpected_scripture[:10])
            )
        if scripture:
            sys.path.insert(0, str(root / "system" / "src"))
            try:
                from sage.original_language_resources import validate_original_language_resources
                from sage.usj import compile_usfm_file, parse_usj_units

                ol_status = validate_original_language_resources(root)
                if ol_status.get("status") != "READY":
                    errors.append(
                        "Bundled original-language distribution resources are not complete and READY"
                    )
                for relative in scripture:
                    if relative in unexpected_scripture:
                        continue
                    usj = compile_usfm_file(root / relative)
                    parser_errors = list(usj.get("sage", {}).get("errors", []))
                    if parser_errors:
                        errors.append(
                            f"Bundled OL resource does not compile cleanly to USJ: {relative}: "
                            + ", ".join(parser_errors[:5])
                        )
                    if not parse_usj_units(usj):
                        errors.append(f"Bundled OL resource has no USJ verse units: {relative}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Bundled OL USJ validation failed: {exc}")
        archives = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*.zip")
            if path.is_file()
        ]
        if archives:
            errors.append(f"Clean source contains nested archives: {', '.join(archives[:10])}")
        forbidden_core_roots = [
            name for name in (".venv", "cache", "state", "workspace_data", "jobs", "reports", "localdata")
            if (root / name).exists()
        ]
        if forbidden_core_roots:
            errors.append(
                "Clean source contains local/runtime roots: " + ", ".join(sorted(forbidden_core_roots))
            )
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
        f"- Registered Skills: {result['counts']['registered_skills']}",
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
