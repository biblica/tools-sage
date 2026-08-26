"""macOS/Linux path, shell, and release metadata portability contracts."""

from __future__ import annotations

import os
import subprocess
import unicodedata
from pathlib import Path

import pytest


POSIX_EXECUTABLES = {
    "sage",
    "system/bin/sage",
    "system/bin/bic",
    "system/bin/saw",
    "system/tools/clone_and_install.sh",
}


def test_posix_source_has_only_governed_executable_files(package_root: Path) -> None:
    """On POSIX hosts, data/resources must not accidentally carry executable bits."""
    if os.name == "nt":
        pytest.skip("POSIX mode bits are not represented by the Windows source filesystem")
    actual = {
        path.relative_to(package_root).as_posix()
        for path in package_root.rglob("*")
        if path.is_file() and os.access(path, os.X_OK)
    }
    assert actual == POSIX_EXECUTABLES


def test_posix_shell_entrypoints_are_sh_syntax_clean(package_root: Path) -> None:
    """All shipped POSIX shell entrypoints parse with /bin/sh."""
    for relative in sorted(POSIX_EXECUTABLES):
        if not relative.endswith(".sh") and relative not in {"sage", "system/bin/sage", "system/bin/bic", "system/bin/saw"}:
            continue
        path = package_root / relative
        result = subprocess.run(["sh", "-n", str(path)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr


def test_root_launcher_preserves_spaces_and_arguments(package_root: Path, tmp_path: Path) -> None:
    """The root POSIX launcher resolves its own path and forwards arguments without word splitting."""
    root = tmp_path / "SAGE path with spaces"
    (root / "system" / "bin").mkdir(parents=True)
    (root / "sage").write_bytes((package_root / "sage").read_bytes())
    implementation = root / "system" / "bin" / "sage"
    implementation.write_text(
        "#!/bin/sh\nprintf '%s\n' \"$0\" \"$@\"\n",
        encoding="utf-8",
    )
    (root / "sage").chmod(0o755)
    implementation.chmod(0o755)
    result = subprocess.run(
        [str(root / "sage"), "alpha beta", "gamma"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == str(implementation)
    assert lines[1:] == ["alpha beta", "gamma"]


def test_package_paths_are_macos_case_and_unicode_safe(package_root: Path) -> None:
    """No package paths collide after macOS-style case folding and Unicode normalization."""
    seen: dict[str, str] = {}
    for path in package_root.rglob("*"):
        relative = path.relative_to(package_root).as_posix()
        key = unicodedata.normalize("NFC", relative).casefold()
        assert key not in seen, f"path collision: {seen.get(key)} <> {relative}"
        seen[key] = relative
        for component in path.relative_to(package_root).parts:
            assert len(component.encode("utf-8")) <= 255
