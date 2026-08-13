#!/usr/bin/env python3
"""Build a deterministic, audited SAGE source package from a populated workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from sage_core.atomic import atomic_write_text
from sage_core.validation import validate_package

SOURCE_TOP_FILES = {
    ".gitignore",
    "HELP.md",
    "README.md",
    "VERSION",
    "bic",
    "bic.cmd",
    "ecosystem.yml",
    "pytest.ini",
    "requirements-dev.txt",
    "requirements.txt",
    "sage",
    "sage.cmd",
    "saw",
    "saw.cmd",
}
SOURCE_DIRECTORIES = {
    "core",
    "docs",
    "meta",
    "profiles",
    "scripts",
    "skills",
    "tests",
    "workflows",
}
WORKSPACE_ONLY_TOP = {
    ".venv",
    "ADDITIONAL-RESOURCE-DATA-NEEDED.md",
    "RESOURCE-TESTING.md",
    "RESOURCE-VALIDATION-REPORT.md",
    "ecosystem.resource-test.yml",
    "cache",
    "state",
    "workspace-data",
    ".pytest_cache",
    ".git",
}
RESOURCE_SOURCE_FILES = {
    "resources/scripture/README.md",
    "resources/scripture/eng.vrs",
    "resources/scripture/org.vrs",
    "resources/scripture/original-language/README.md",
    "resources/scripture/original-language/grk/README.md",
    "resources/scripture/original-language/heb/README.md",
    "resources/rwc/README.md",
    "resources/rwc/authority/SOURCES.yml",
}
JOB_SOURCE_FILES = {
    "jobs/README.md",
    "jobs/bic/README.md",
    "jobs/saw/README.md",
}
WORKSPACE_SEED_FILES = {
    "workspace-data/scripture-projects/README.md",
}
FORBIDDEN_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".mypy_cache",
    ".ruff_cache",
    "htmlcov",
}
FORBIDDEN_NAMES = {".coverage", ".DS_Store", "Thumbs.db", "desktop.ini"}
ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar"}
FIXED_TIME = (2026, 1, 1, 0, 0, 0)
PACKAGE_NAME = f"SAGE-v{(ROOT / 'VERSION').read_text(encoding='utf-8').strip()}-Standalone-CLI-Source"


def _should_skip(path: Path, root: Path) -> bool:
    """Return whether a source path is an ephemeral or forbidden release artefact."""
    relative = path.relative_to(root)
    return (
        path.name in FORBIDDEN_NAMES
        or any(part in FORBIDDEN_PARTS for part in relative.parts)
        or path.suffix.lower() in {".pyc", ".pyo"}
    )


def _copy_source_tree(root: Path, stage: Path) -> list[str]:
    """Copy only governed source files into the clean release staging tree."""
    unknown: list[str] = []
    for item in sorted(root.iterdir(), key=lambda value: value.name):
        name = item.name
        if name in WORKSPACE_ONLY_TOP or name in {"jobs", "resources"}:
            continue
        if item.is_file() and name in SOURCE_TOP_FILES:
            shutil.copy2(item, stage / name)
            continue
        if item.is_dir() and name in SOURCE_DIRECTORIES:
            shutil.copytree(
                item,
                stage / name,
                ignore=lambda directory, names: [
                    child
                    for child in names
                    if child in FORBIDDEN_NAMES or child in FORBIDDEN_PARTS
                ],
            )
            continue
        unknown.append(name)
    for relative in sorted(RESOURCE_SOURCE_FILES | JOB_SOURCE_FILES | WORKSPACE_SEED_FILES):
        source = root / relative
        if not source.is_file():
            unknown.append(relative)
            continue
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for path in list(stage.rglob("*")):
        if path.is_file() and _should_skip(path, stage):
            path.unlink()
    return unknown




def _source_tree_sha256(root: Path) -> str:
    """Hash the governed source tree by relative path and bytes, excluding runtime artefacts."""
    digest = hashlib.sha256()
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or _should_skip(path, root):
            continue
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in WORKSPACE_ONLY_TOP:
            continue
        files.append(path)
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _run_hardening_gate(stage: Path) -> tuple[bool, dict[str, object] | str]:
    """Run complete isolated hardening and bind its PASS result to this exact source hash."""
    expected_hash = _source_tree_sha256(stage)
    with tempfile.TemporaryDirectory(prefix="sage-release-hardening-report-") as td:
        report_path = Path(td) / "hardening-report.json"
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["SAGE_DISABLE_OPERATIONAL_LOG"] = "1"
        result = subprocess.run(
            [sys.executable, str(stage / "scripts" / "hardening.py"), "--output", str(report_path)],
            cwd=stage,
            env=env,
            text=True,
            capture_output=True,
            timeout=1200,
            check=False,
        )
        if result.returncode != 0 or not report_path.is_file():
            return False, (result.stdout + result.stderr).strip() or "Hardening gate failed without a report."
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return False, f"Hardening report is invalid JSON: {exc}"
    if report.get("status") != "PASS":
        return False, report
    if report.get("source_tree_sha256") != expected_hash:
        return False, {
            "reason": "HARDENING_SOURCE_HASH_MISMATCH",
            "expected": expected_hash,
            "reported": report.get("source_tree_sha256"),
        }
    return True, report


def _audit_stage(stage: Path) -> tuple[bool, str]:
    """Run package validation and deep audit against the exact staged source tree."""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["SAGE_DISABLE_OPERATIONAL_LOG"] = "1"
    result = subprocess.run(
        [sys.executable, str(stage / "scripts" / "deep_audit.py"), str(stage), "--mode", "source"],
        cwd=stage,
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        return False, output
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False, output or "Deep audit did not return JSON."
    return report.get("status") == "PASS", result.stdout.strip()


def _write_member(archive: zipfile.ZipFile, path: Path, stage: Path) -> None:
    """Write one deterministic ZIP member with fixed timestamp and governed permissions."""
    relative = path.relative_to(stage).as_posix()
    info = zipfile.ZipInfo(f"{PACKAGE_NAME}/{relative}", FIXED_TIME)
    mode = path.stat().st_mode
    permissions = 0o755 if mode & stat.S_IXUSR else 0o644
    info.external_attr = permissions << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, path.read_bytes())


def main() -> int:
    """Run the command-line entry point and return its process status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Output ZIP filename.")
    parser.add_argument("--root", default=str(ROOT), help="Populated or clean SAGE workspace root.")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="sage-release-build-") as temporary_directory:
        stage = Path(temporary_directory) / PACKAGE_NAME
        stage.mkdir(parents=True)
        unknown = _copy_source_tree(root, stage)
        if unknown:
            print("ERROR: Unclassified source-root entries:", file=sys.stderr)
            for item in sorted(set(unknown)):
                print(f"- {item}", file=sys.stderr)
            return 2

        validation = validate_package(stage)
        if validation["status"] != "READY":
            for error in validation["errors"]:
                print(f"ERROR: {error}", file=sys.stderr)
            for warning in validation["warnings"]:
                print(f"ERROR: package warning: {warning}", file=sys.stderr)
            return 2

        hardening_report: dict[str, object] | None = None
        # Production release builds require a complete hardening PASS bound to the exact staged source hash.
        # These switches are test/internal-harness controls only, preventing recursive release builds inside hardening.
        if (
            os.environ.get("SAGE_HARDENING_ACTIVE") != "1"
            and os.environ.get("SAGE_TEST_SKIP_BUILD_HARDENING") != "1"
        ):
            hardening_ok, hardening_result = _run_hardening_gate(stage)
            if not hardening_ok:
                print("ERROR: Exact-source hardening gate failed.", file=sys.stderr)
                if isinstance(hardening_result, str):
                    print(hardening_result, file=sys.stderr)
                else:
                    print(json.dumps(hardening_result, ensure_ascii=False, indent=2, sort_keys=True), file=sys.stderr)
                return 2
            hardening_report = hardening_result if isinstance(hardening_result, dict) else None

        # Normal builds always run the source-stage audit. The test-only environment
        # switch isolates ZIP-byte determinism from the separately tested audit gate.
        if os.environ.get("SAGE_TEST_SKIP_BUILD_AUDIT") != "1":
            audit_ok, audit_output = _audit_stage(stage)
            if not audit_ok:
                print("ERROR: Source-stage deep audit failed.", file=sys.stderr)
                print(audit_output, file=sys.stderr)
                return 2

        files = sorted(
            (path for path in stage.rglob("*") if path.is_file()),
            key=lambda item: item.relative_to(stage).as_posix(),
        )
        if any(path.suffix.lower() in ARCHIVE_SUFFIXES for path in files):
            print("ERROR: Nested archive reached source staging.", file=sys.stderr)
            return 2

        temporary = output.with_name(f".{output.name}.tmp")
        if temporary.exists():
            temporary.unlink()
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in files:
                    _write_member(archive, path, stage)
            with zipfile.ZipFile(temporary) as archive:
                corrupt_member = archive.testzip()
            if corrupt_member is not None:
                print(f"ERROR: Archive integrity failed at {corrupt_member}", file=sys.stderr)
                return 2
            os.replace(temporary, output)
        finally:
            if temporary.exists():
                temporary.unlink()

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum = output.with_suffix(output.suffix + ".sha256")
    atomic_write_text(checksum, f"{digest}  {output.name}\n")
    if hardening_report is not None:
        gate_receipt = {
            "schema_version": "1.0",
            "status": "PASS",
            "source_tree_sha256": hardening_report.get("source_tree_sha256"),
            "tests_passed": hardening_report.get("tests_passed"),
            "test_files_discovered": hardening_report.get("test_files_discovered"),
            "test_files_scheduled": hardening_report.get("test_files_scheduled"),
            "package_sha256": digest,
            "package": output.name,
        }
        atomic_write_text(
            output.with_suffix(output.suffix + ".hardening.json"),
            json.dumps(gate_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
    print(f"Built: {output}")
    print(f"SHA-256: {digest}")
    print(f"Files: {len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
