"""macOS/Linux path, shell, and release metadata portability contracts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import unicodedata
from pathlib import Path

import pytest


APP_POSIX_EXECUTABLES = {
    "sage-python",
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
    assert actual == APP_POSIX_EXECUTABLES
    assert os.access(package_root.parent / "sage", os.X_OK)


def test_posix_shell_entrypoints_are_sh_syntax_clean(package_root: Path) -> None:
    """All shipped POSIX shell entrypoints parse with /bin/sh."""
    for relative in sorted(APP_POSIX_EXECUTABLES):
        if not relative.endswith(".sh") and relative not in {"sage-python", "system/bin/sage", "system/bin/bic", "system/bin/saw"}:
            continue
        path = package_root / relative
        result = subprocess.run(["sh", "-n", str(path)], text=True, capture_output=True, check=False)
        assert result.returncode == 0, result.stderr
    result = subprocess.run(["sh", "-n", str(package_root.parent / "sage")], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


def test_root_launcher_preserves_spaces_and_arguments(package_root: Path, tmp_path: Path) -> None:
    """The root POSIX launcher resolves its own path and forwards arguments without word splitting."""
    root = tmp_path / "SAGE path with spaces"
    (root / "app" / "system" / "bin").mkdir(parents=True)
    (root / "sage").write_bytes((package_root.parent / "sage").read_bytes())
    implementation = root / "app" / "system" / "bin" / "sage"
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


def test_launcher_ignores_broken_host_python_commands(package_root: Path, tmp_path: Path) -> None:
    """Launch through the managed runtime even when every host-Python command fails."""
    if os.name == "nt":
        pytest.skip("POSIX launcher contract")
    bundle = tmp_path / "SAGE without host Python"
    app = bundle / "app"
    tools = app / "system" / "tools"
    config = app / "system" / "config"
    bin_root = app / "system" / "bin"
    tools.mkdir(parents=True)
    config.mkdir(parents=True)
    bin_root.mkdir(parents=True)
    (bundle / "sage").write_bytes((package_root.parent / "sage").read_bytes())
    (bin_root / "sage").write_bytes((package_root / "system" / "bin" / "sage").read_bytes())
    (tools / "bootstrap_python.sh").write_bytes(
        (package_root / "system" / "tools" / "bootstrap_python.sh").read_bytes()
    )
    (config / "python-runtime.json").write_bytes(
        (package_root / "system" / "config" / "python-runtime.json").read_bytes()
    )
    managed = bundle / "localdata" / ".system" / "runtime" / "python" / "bin" / "python3"
    venv = bundle / "localdata" / ".system" / "runtime" / "venv" / "bin" / "python"
    managed.parent.mkdir(parents=True)
    venv.parent.mkdir(parents=True)
    managed.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    venv.write_text("#!/bin/sh\nprintf 'MANAGED:%s\\n' \"$*\"\n", encoding="utf-8")
    for path in (bundle / "sage", bin_root / "sage", managed, venv):
        path.chmod(0o755)

    restricted = tmp_path / "restricted-path"
    restricted.mkdir()
    for name in ("dirname", "uname", "sed", "head", "awk"):
        target = shutil.which(name)
        assert target is not None
        (restricted / name).symlink_to(target)
    hash_name = "shasum" if shutil.which("shasum") else "sha256sum"
    hash_target = shutil.which(hash_name)
    assert hash_target is not None
    (restricted / hash_name).symlink_to(hash_target)
    for name in ("python", "python3", "py"):
        (restricted / name).symlink_to("/usr/bin/false")

    result = subprocess.run(
        [str(bundle / "sage"), "--json", "data-home", "show"],
        cwd=bundle,
        env={
            **os.environ,
            "PATH": str(restricted),
            "SAGE_DATA_HOME": str(bundle / "localdata"),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "MANAGED:-m sage.cli --json data-home show\n"


def test_macos_bootstrap_accepts_approved_existing_homebrew_python(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """Use an approved Homebrew CPython by absolute prefix without depending on the terminal PATH."""
    bundle = tmp_path / "SAGE with Homebrew Python"
    app = bundle / "app"
    tools = app / "system" / "tools"
    config = app / "system" / "config"
    tools.mkdir(parents=True)
    config.mkdir(parents=True)
    data = bundle / "localdata"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    brew_root = tmp_path / "homebrew" / "opt" / "python@3.12"
    brew_python = brew_root / "bin" / "python3.12"
    brew_python.parent.mkdir(parents=True)
    brew_python.write_text(
        "#!/bin/sh\n"
        "case \"${2:-}\" in\n"
        "  *'print(platform.python_version())'*) printf '%s\\n' '3.12.9' ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_brew = tmp_path / "brew"
    fake_brew.write_text(
        f"#!/bin/sh\n[ \"${{1:-}}\" = '--prefix' ] && printf '%s\\n' '{brew_root}'\n",
        encoding="utf-8",
    )
    fake_uname = fake_bin / "uname"
    fake_uname.write_text(
        "#!/bin/sh\n"
        "case \"${1:-}\" in\n"
        "  -s) printf '%s\\n' Darwin ;;\n"
        "  -m) printf '%s\\n' arm64 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    for path in (brew_python, fake_brew, fake_uname):
        path.chmod(0o755)

    source = (package_root / "system" / "tools" / "bootstrap_python.sh").read_text(encoding="utf-8")
    source = source.replace("/opt/homebrew/bin/brew", str(fake_brew))
    source = source.replace("/usr/local/bin/brew", str(tmp_path / "missing-brew"))
    source = source.replace("/Library/Frameworks/Python.framework", str(tmp_path / "missing-framework"))
    bootstrap = tools / "bootstrap_python.sh"
    bootstrap.write_text(source, encoding="utf-8")
    bootstrap.chmod(0o755)
    (tools / "bootstrap_runtime.py").write_text("# fake bootstrap boundary\n", encoding="utf-8")
    (config / "python-runtime.json").write_bytes(
        (package_root / "system" / "config" / "python-runtime.json").read_bytes()
    )
    venv = data / ".system" / "runtime" / "venv" / "bin" / "python"
    venv.parent.mkdir(parents=True)
    venv.write_text("#!/bin/sh\nprintf 'HOST-VENV:%s\\n' \"$*\"\n", encoding="utf-8")
    venv.chmod(0o755)

    result = subprocess.run(
        [
            "/bin/sh",
            str(bootstrap),
            str(app),
            "base",
            "launch",
            "--data-home",
            str(data),
        ],
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Using approved Homebrew CPython 3.12.9" in result.stdout
    assert "HOST-VENV:-m sage.cli --data-home" in result.stdout
    assert not (data / ".system" / "runtime" / "python").exists()


def test_macos_bootstrap_clears_quarantine_only_after_archive_hash_verification(
    package_root: Path,
    tmp_path: Path,
) -> None:
    """A pinned runtime archive must not trigger Gatekeeper merely because its ZIP was quarantined."""
    if sys.platform != "darwin":
        pytest.skip("macOS quarantine contract")
    bundle = tmp_path / "SAGE quarantined download"
    app = bundle / "app"
    config = app / "system" / "config"
    config.mkdir(parents=True)
    data = bundle / "localdata"
    downloads = data / ".system" / "runtime" / "downloads"
    downloads.mkdir(parents=True)
    payload_root = tmp_path / "payload" / "python" / "bin"
    payload_root.mkdir(parents=True)
    payload_python = payload_root / "python3"
    payload_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    payload_python.chmod(0o755)
    archive = downloads / "runtime.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(payload_root.parent, arcname="python")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "python_version": "3.12.14",
        "host_python_minimum_version": "3.12.4",
        "artifacts": {
            "macos-arm64": {
                "archive_name": archive.name,
                "python_path": "python/bin/python3",
                "sha256": digest,
                "url": "https://invalid.example/runtime.tar.gz",
            }
        },
    }
    (config / "python-runtime.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    bootstrap = app / "system" / "tools" / "bootstrap_python.sh"
    bootstrap.parent.mkdir(parents=True, exist_ok=True)
    bootstrap_source = (package_root / "system" / "tools" / "bootstrap_python.sh").read_text(encoding="utf-8")
    bootstrap.write_text(
        bootstrap_source.replace("if select_host_python; then", "if false; then"),
        encoding="utf-8",
    )
    bootstrap.chmod(0o755)
    venv_python = data / ".system" / "runtime" / "venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\nprintf 'MANAGED:%s\\n' \"$*\"\n", encoding="utf-8")
    venv_python.chmod(0o755)
    subprocess.run(
        [
            "/usr/bin/xattr",
            "-w",
            "com.apple.quarantine",
            "0081;00000000;SAGE-Test;00000000-0000-0000-0000-000000000000",
            str(archive),
        ],
        check=True,
    )

    result = subprocess.run(
        [
            "/bin/sh",
            str(bootstrap),
            str(app),
            "base",
            "launch",
            "--data-home",
            str(data),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    installed = data / ".system" / "runtime" / "python" / "bin" / "python3"
    assert result.returncode == 0, result.stderr
    assert "Cleared macOS quarantine from the exact SHA-256-verified" in result.stdout
    assert "MANAGED:-m sage.cli --data-home" in result.stdout
    for path in (archive, installed):
        probe = subprocess.run(
            ["/usr/bin/xattr", "-p", "com.apple.quarantine", str(path)],
            capture_output=True,
            check=False,
        )
        assert probe.returncode != 0


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
