"""Human-facing command grammar and launcher consistency tests."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from sage.cli import build_parser
from sage.storage import storage_layout


def run(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one isolated command and capture its deterministic result."""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["SAGE_DISABLE_OPERATIONAL_LOG"] = "1"
    return subprocess.run(
        [str(path), *args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )


def run_sage(package_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run application CLI grammar under the test interpreter; launcher bootstrap is tested separately."""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["SAGE_DISABLE_OPERATIONAL_LOG"] = "1"
    env["PYTHONPATH"] = str(package_root / "system" / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "sage.cli", *args],
        cwd=package_root,
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )


def parser_at(*names: str) -> argparse.ArgumentParser:
    """Return one nested public parser from the canonical command grammar."""
    parser: argparse.ArgumentParser = build_parser()
    for name in names:
        subparsers = next(
            action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
        )
        parser = subparsers.choices[name]
    return parser

def test_root_help_exposes_only_canonical_domains(package_root: Path) -> None:
    """Verify that root help exposes only canonical domains."""
    result = run_sage(package_root, "--help")
    assert result.returncode == 0
    for domain in ("status", "setup", "menu", "guide", "help", "workspace", "project", "model", "task", "evaluation", "transaction", "generation", "workflow"):
        assert domain in result.stdout
    first_line = result.stdout.splitlines()[0]
    for legacy in (" init ", " validate ", " projects ", " act "):
        assert legacy not in first_line
    assert "sage <domain> <action>" in result.stdout
    assert "sage status" in result.stdout and "sage setup" in result.stdout



def test_status_is_fast_local_by_default(package_root: Path) -> None:
    """Verify top-level status avoids provider probing and persistent logging unless explicitly requested."""
    log_path = storage_layout(package_root, create=True).logs_root / "operational.jsonl"
    before = log_path.read_bytes() if log_path.is_file() else None
    result = run_sage(package_root, "status")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "Live provider check: ./system/bin/sage status --live" in result.stdout
    help_result = run_sage(package_root, "status", "--help")
    assert help_result.returncode == 0
    assert "--live" in help_result.stdout
    after = log_path.read_bytes() if log_path.is_file() else None
    assert after == before

def test_domain_help_is_available(package_root: Path) -> None:
    """Verify every public domain is registered and renders help from the canonical parser."""
    del package_root  # Parser grammar is the authority after the root launcher smoke above.
    parser = build_parser()
    root_subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    for domain in ("setup", "menu", "workspace", "project", "model", "task", "evaluation", "transaction", "generation", "workflow"):
        domain_parser = root_subparsers.choices[domain]
        assert "usage:" in domain_parser.format_help()


def test_workflow_launchers_use_canonical_task_commands(package_root: Path) -> None:
    """Verify that workflow launchers use canonical task commands."""
    bic = run(package_root / "system" / "bin" / "bic", "--help")
    saw = run(package_root / "system" / "bin" / "saw", "--help")
    assert bic.returncode == saw.returncode == 0
    assert "task create" not in bic.stdout  # wrapper presents concise workflow verbs
    assert "inspect" in bic.stdout and "self-check" in bic.stdout
    assert "qa" in saw.stdout and "focused" in saw.stdout and "ol" in saw.stdout
    assert "--source" in bic.stdout and "--donor" in bic.stdout and "--target" in bic.stdout
    assert "--wip" in saw.stdout and "--reference" in saw.stdout


def test_launcher_files_use_consistent_platform_forms(package_root: Path) -> None:
    """Verify that launcher files use consistent platform forms."""
    for name in ("sage", "system/bin/sage", "system/bin/bic", "system/bin/saw"):
        assert os.access(package_root / name, os.X_OK)
    for name in ("sage.cmd", "system/bin/sage.cmd", "system/bin/bic.cmd", "system/bin/saw.cmd"):
        payload = (package_root / name).read_bytes()
        assert b"\r\n" in payload
        assert b"\n" not in payload.replace(b"\r\n", b"")
    attributes = (package_root / ".gitattributes").read_text(encoding="utf-8")
    assert "/sage text eol=lf" in attributes
    assert "*.cmd text eol=crlf" in attributes


def test_root_launchers_are_thin_forwarders(package_root: Path, tmp_path: Path) -> None:
    """Verify root startup delegates to the governed implementation launchers."""
    posix = (package_root / "sage").read_text(encoding="utf-8")
    windows = (package_root / "sage.cmd").read_text(encoding="utf-8")
    assert 'exec "$SAGE_ROOT/system/bin/sage" "$@"' in posix
    assert 'call "%~dp0system\\bin\\sage.cmd" %*' in windows

    isolated_root = tmp_path / "SAGE root with spaces"
    implementation = isolated_root / "system" / "bin" / "sage"
    implementation.parent.mkdir(parents=True)
    implementation.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
    implementation.chmod(0o755)
    root_launcher = isolated_root / "sage"
    root_launcher.write_text(posix, encoding="utf-8")
    root_launcher.chmod(0o755)
    result = run(root_launcher, "--help")
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout == "--help\n"


def test_guide_and_help_work_before_settings_resolution(package_root: Path) -> None:
    """Verify first-use guidance works before settings or workspace initialization."""
    log_path = storage_layout(package_root, create=True).logs_root / "operational.jsonl"
    before = log_path.read_bytes() if log_path.is_file() else None
    guide = run_sage(package_root, "--settings", "missing-settings.yml", "guide", "surfaces")
    help_alias = run_sage(package_root, "--settings", "missing-settings.yml", "help", "task")
    assert guide.returncode == 0, guide.stderr + guide.stdout
    assert help_alias.returncode == 0, help_alias.stderr + help_alias.stdout
    assert "SAGE controller" in guide.stdout
    assert "Codex CLI" in guide.stdout
    assert "ChatGPT sign-in" in guide.stdout
    assert "Use the BIC/SAW menus for normal work" in help_alias.stdout
    after = log_path.read_bytes() if log_path.is_file() else None
    assert after == before


def test_launchers_delegate_runtime_creation_to_bootstrap(package_root: Path) -> None:
    """Require launchers to create and repair the external managed runtime through bootstrap."""
    posix = (package_root / "system" / "bin" / "sage").read_text(encoding="utf-8")
    windows = (package_root / "system/bin/sage.cmd").read_text(encoding="utf-8")
    assert "bootstrap_runtime.py" in posix
    assert "bootstrap_runtime.py" in windows
    assert ".venv/bin/python" not in posix
    assert ".venv\\Scripts\\python.exe" not in windows
    assert "VENV_PYTHON" not in posix
    assert "VENV_PYTHON" not in windows



def test_bic_self_check_public_hyphenated_shortcut_is_accepted(package_root: Path) -> None:
    """Verify documented `self-check` is a real public command rather than only a suggestion for self_check."""
    result = run_sage(package_root, "shortcut", "--workflow", "bic", "self-check", "--", "--help")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "UNKNOWN_WORKFLOW_COMMAND" not in result.stdout + result.stderr
    assert "--operation" in result.stdout


def test_rwc_import_cannot_grant_approval_from_cli(package_root: Path) -> None:
    """Verify FLEx/Combine import surfaces do not expose a linguistic-status option."""
    del package_root
    for source in ("flex", "combine"):
        assert "--status" not in parser_at("rwc", "import", source).format_help()


def test_rwc_export_requires_explicit_evidence_view(package_root: Path) -> None:
    """Verify there is no implicit export-all view for generated FLEx/Combine packages."""
    help_text = parser_at("rwc", "export").format_help()
    for view in ("starter", "reviewed", "established", "approved"):
        assert view in help_text
    assert "--view" in help_text
    source = (package_root / "system" / "src" / "sage" / "semantic_cli.py").read_text(encoding="utf-8")
    assert 'export.add_argument("--view", required=True' in source


def test_rwc_operator_surface_exposes_initialize_lookup_and_review(package_root: Path) -> None:
    """Verify the forward-only RWC workflow has explicit initialize, lookup, and review surfaces."""
    del package_root
    rwc_parser = parser_at("rwc")
    subparsers = next(
        action for action in rwc_parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    for command in ("initialize", "lookup", "review", "index", "export"):
        assert command in subparsers.choices
    init_help = parser_at("rwc", "initialize").format_help()
    assert "--greek-project" in init_help and "--greek-language" in init_help
