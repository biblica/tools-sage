#!/usr/bin/env python3
"""Build a deterministic, audited SAGE source package from a populated workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True

APP_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_ROOT = APP_ROOT.parent
sys.path.insert(0, str(APP_ROOT / "system" / "src"))

from sage.atomic import atomic_write_text
from sage.validation import validate_package

SOURCE_TOP_FILES = {
    ".gitattributes",
    ".gitignore",
    "README.md",
    "sage",
    "sage.cmd",
}
SOURCE_DIRECTORIES = {
    ".github",
    "app",
}
WORKSPACE_ONLY_TOP = {
    ".venv",
    "ADDITIONAL-RESOURCE-DATA-NEEDED.md",
    "RESOURCE-TESTING.md",
    "RESOURCE-VALIDATION-REPORT.md",
    "ecosystem.resource-test.yml",
    "cache",
    "state",
    "workspace_data",
    "jobs",
    "reports",
    "localdata",
    ".pytest_cache",
    ".git",
}
RESOURCE_SOURCE_FILES = {
    "app/system/resources/scripture/README.md",
    "app/system/resources/scripture/eng.vrs",
    "app/system/resources/scripture/org.vrs",
    "app/system/resources/scripture/lxx.vrs",
    "app/system/resources/scripture/vul.vrs",
    "app/system/resources/scripture/rsc.vrs",
    "app/system/resources/scripture/rso.vrs",
    "app/system/resources/scripture/standard-vrs-provenance.json",
    "app/system/resources/scripture/standard-vrs.LICENSE.txt",
    "app/system/resources/scripture/original-language/README.md",
    "app/system/resources/scripture/original-language/grk/README.md",
    "app/system/resources/scripture/original-language/heb/README.md",
    "app/system/resources/rwc/README.md",
    "app/system/resources/rwc/authority/sources.json",
}
BUNDLED_OL_DIRECTORIES = {
    "app/system/resources/scripture/original-language/grk",
    "app/system/resources/scripture/original-language/heb",
}
BUNDLED_OL_FILENAMES = {"README.md", "Settings.xml", "BookNames.xml"}
POSIX_EXECUTABLE_MEMBERS = {
    "sage",
    "app/sage-python",
    "app/system/bin/sage",
    "app/system/bin/bic",
    "app/system/bin/saw",
    "app/system/tools/clone_and_install.sh",
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
PACKAGE_NAME = f"SAGE-v{(APP_ROOT / 'VERSION').read_text(encoding='utf-8').strip()}-Full-Distribution"


def _should_skip(path: Path, root: Path) -> bool:
    """Return whether a source path is an ephemeral or forbidden release artifact."""
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
        if name == "localdata":
            readme = item / "README.md"
            if not readme.is_file():
                unknown.append("localdata/README.md")
            else:
                destination = stage / "localdata" / "README.md"
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(readme, destination)
            continue
        if name in WORKSPACE_ONLY_TOP or name in FORBIDDEN_NAMES:
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
    for relative in sorted(RESOURCE_SOURCE_FILES):
        source = root / relative
        if not source.is_file():
            unknown.append(relative)
            continue
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for relative in sorted(BUNDLED_OL_DIRECTORIES):
        source_directory = root / relative
        if not source_directory.is_dir():
            unknown.append(relative)
            continue
        for source in sorted(source_directory.iterdir(), key=lambda value: value.name):
            if not source.is_file() or (
                source.name not in BUNDLED_OL_FILENAMES and source.suffix.lower() != ".sfm"
            ):
                continue
            destination = stage / relative / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    for path in list(stage.rglob("*")):
        if path.is_file() and _should_skip(path, stage):
            path.unlink()
    return unknown




def _source_tree_sha256(root: Path) -> str:
    """Hash the governed source tree by relative path and bytes, excluding runtime artifacts."""
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


def _run_hardening_gate(app_stage: Path) -> tuple[bool, dict[str, object] | str]:
    """Run deterministic hardening shards and the formal combine gate on the staged app."""
    expected_hash = _source_tree_sha256(app_stage)
    raw_shards = os.environ.get("SAGE_HARDENING_SHARDS", "4").strip()
    try:
        shard_count = max(1, min(16, int(raw_shards)))
    except ValueError:
        shard_count = 4
    with tempfile.TemporaryDirectory(prefix="sage-release-hardening-report-") as td:
        receipt_root = Path(td)
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["SAGE_DISABLE_OPERATIONAL_LOG"] = "1"
        shard_paths: list[Path] = []
        for shard_index in range(shard_count):
            shard_path = receipt_root / f"hardening-shard-{shard_index:02d}-of-{shard_count:02d}.json"
            shard_paths.append(shard_path)
            result = subprocess.run(
                [
                    sys.executable,
                    str(app_stage / "system" / "tools" / "hardening.py"),
                    "--shard-count", str(shard_count),
                    "--shard-index", str(shard_index),
                    "--output", str(shard_path),
                ],
                cwd=app_stage,
                env=env,
                text=True,
                capture_output=True,
                timeout=1200,
                check=False,
            )
            if result.returncode != 0 or not shard_path.is_file():
                return False, (result.stdout + result.stderr).strip() or f"Hardening shard {shard_index} failed without a report."
        combined_path = receipt_root / "hardening-combined.json"
        combine = subprocess.run(
            [
                sys.executable,
                str(app_stage / "system" / "tools" / "hardening.py"),
                "--combine", *[str(path) for path in shard_paths],
                "--expected-source-sha256", expected_hash,
                "--output", str(combined_path),
            ],
            cwd=app_stage,
            env=env,
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
        if combine.returncode != 0 or not combined_path.is_file():
            return False, (combine.stdout + combine.stderr).strip() or "Formal hardening combine gate failed without a report."
        try:
            report = json.loads(combined_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return False, f"Combined hardening report is invalid JSON: {exc}"
    if report.get("status") != "PASS" or report.get("formal_combine") != "PASS":
        return False, report
    if report.get("source_tree_sha256") != expected_hash:
        return False, {
            "reason": "HARDENING_SOURCE_HASH_MISMATCH",
            "expected": expected_hash,
            "reported": report.get("source_tree_sha256"),
        }
    if report.get("test_modules_scheduled_exactly_once") is not True:
        return False, {"reason": "HARDENING_TEST_INVENTORY_INCOMPLETE", "report": report}
    if report.get("governed_source_unchanged") is not True:
        return False, {"reason": "HARDENING_SOURCE_MUTATED", "report": report}
    return True, report


def _validate_hardening_receipt(path: Path, *, expected_hash: str) -> tuple[bool, dict[str, object] | str]:
    """Validate one previously completed formal hardening receipt against the exact staged source hash."""
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"Hardening receipt could not be read: {exc}"
    if not isinstance(report, dict):
        return False, "Hardening receipt root must be a JSON object."
    required = {
        "status": "PASS",
        "formal_combine": "PASS",
        "source_tree_sha256": expected_hash,
        "governed_source_unchanged": True,
        "test_modules_scheduled_exactly_once": True,
        "schema_validation": "PASS",
        "package_validation": "PASS",
        "deep_audit": "PASS",
    }
    failures = [
        f"{key}={report.get(key)!r} expected {value!r}"
        for key, value in required.items()
        if report.get(key) != value
    ]
    if int(report.get("tests_failed") or 0) != 0:
        failures.append(f"tests_failed={report.get('tests_failed')!r} expected 0")
    if report.get("errors"):
        failures.append("formal hardening receipt contains errors")
    if report.get("warnings"):
        failures.append("formal hardening receipt contains warnings")
    discovered = int(report.get("test_files_discovered") or 0)
    scheduled = int(report.get("test_files_scheduled") or 0)
    if discovered < 1 or scheduled != discovered:
        failures.append(f"test module coverage mismatch: discovered={discovered} scheduled={scheduled}")
    test_cases = int(report.get("test_cases_discovered") or 0)
    outcomes = int(report.get("tests_passed") or 0) + int(report.get("tests_skipped") or 0)
    if test_cases < 1 or outcomes != test_cases:
        failures.append(f"test outcome coverage mismatch: collected={test_cases} outcomes={outcomes}")
    if failures:
        return False, {"reason": "HARDENING_RECEIPT_INVALID", "failures": failures, "report": report}
    return True, report


def _audit_stage(app_stage: Path) -> tuple[bool, str]:
    """Run package validation and deep audit against the exact staged app tree."""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["SAGE_DISABLE_OPERATIONAL_LOG"] = "1"
    result = subprocess.run(
        [sys.executable, str(app_stage / "system" / "tools" / "deep_audit.py"), str(app_stage), "--mode", "source"],
        cwd=app_stage,
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


def _zip_permissions(relative: str) -> int:
    """Return deterministic POSIX permissions independent of the build host filesystem."""
    return 0o755 if relative in POSIX_EXECUTABLE_MEMBERS else 0o644


def _write_member(archive: zipfile.ZipFile, path: Path, stage: Path) -> None:
    """Write one deterministic ZIP member with fixed timestamp and governed permissions."""
    relative = path.relative_to(stage).as_posix()
    info = zipfile.ZipInfo(f"{PACKAGE_NAME}/{relative}", FIXED_TIME)
    permissions = _zip_permissions(relative)
    # Force Unix metadata even when the release builder itself runs on Windows.
    # macOS/Linux extractors can then restore executable launcher bits reliably.
    info.create_system = 3
    info.external_attr = (0o100000 | permissions) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, path.read_bytes())


def main() -> int:
    """Run the command-line entry point and return its process status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Output ZIP filename.")
    parser.add_argument("--root", default=str(BUNDLE_ROOT), help="Portable SAGE bundle root.")
    parser.add_argument(
        "--hardening-receipt",
        help="Existing formal-combine hardening receipt bound to the exact governed source hash.",
    )
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

        app_stage = stage / "app"
        validation = validate_package(app_stage)
        if validation["status"] != "READY":
            for error in validation["errors"]:
                print(f"ERROR: {error}", file=sys.stderr)
            for warning in validation["warnings"]:
                print(f"ERROR: package warning: {warning}", file=sys.stderr)
            return 2

        hardening_report: dict[str, object] | None = None
        # Production release builds require a complete hardening PASS bound to the exact staged source hash.
        # A supplied formal-combine receipt avoids rerunning qualification after it has already passed on this hash.
        # Test/internal switches remain limited to recursive test harnesses and are never production evidence.
        if (
            os.environ.get("SAGE_HARDENING_ACTIVE") != "1"
            and os.environ.get("SAGE_TEST_SKIP_BUILD_HARDENING") != "1"
        ):
            if args.hardening_receipt:
                hardening_ok, hardening_result = _validate_hardening_receipt(
                    Path(args.hardening_receipt).resolve(),
                    expected_hash=_source_tree_sha256(app_stage),
                )
            else:
                hardening_ok, hardening_result = _run_hardening_gate(app_stage)
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
            audit_ok, audit_output = _audit_stage(app_stage)
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
            "formal_combine": hardening_report.get("formal_combine"),
            "shard_count": hardening_report.get("shard_count"),
            "tests_passed": hardening_report.get("tests_passed"),
            "tests_skipped": hardening_report.get("tests_skipped"),
            "test_cases_discovered": hardening_report.get("test_cases_discovered"),
            "test_files_discovered": hardening_report.get("test_files_discovered"),
            "test_files_scheduled": hardening_report.get("test_files_scheduled"),
            "test_modules_scheduled_exactly_once": hardening_report.get("test_modules_scheduled_exactly_once"),
            "schema_validation": hardening_report.get("schema_validation"),
            "package_validation": hardening_report.get("package_validation"),
            "deep_audit": hardening_report.get("deep_audit"),
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
