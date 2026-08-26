"""Cross-platform Windows path and command portability contracts."""

from __future__ import annotations

from pathlib import Path

from sage.project_codes import project_code_is_path_safe
from sage.platform_commands import (
    is_sage_launcher_token,
    render_sage_command,
    sage_launcher,
    split_operator_command,
)


WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
WINDOWS_ILLEGAL = set('<>:"\\|?*')


def test_windows_rendering_uses_native_separator_and_quotes() -> None:
    """Render copyable commands that work in both Command Prompt and PowerShell."""
    command = render_sage_command(
        ["--settings", r"C:\SAGE Root\ecosystem.yml", "task", "submit", "--task", r"C:\Work Unit\task.json"],
        windows=True,
    )
    assert command.startswith(r".\system\bin\sage.cmd ")
    assert '"C:\\SAGE Root\\ecosystem.yml"' in command
    assert '"C:\\Work Unit\\task.json"' in command
    assert sage_launcher(windows=True, root=True) == r".\sage.cmd"


def test_windows_command_parser_preserves_backslashes_off_host() -> None:
    """Exercise the non-Windows test fallback without corrupting Windows path tokens."""
    command = r'.\system\bin\sage.cmd --settings "C:\SAGE Root\ecosystem.yml" status'
    tokens = split_operator_command(command, windows=True)
    assert tokens == [r".\system\bin\sage.cmd", "--settings", r"C:\SAGE Root\ecosystem.yml", "status"]
    assert is_sage_launcher_token(tokens[0])


def test_project_codes_reject_windows_device_names() -> None:
    """Reject logical Project IDs that would become invalid Windows directory/file names."""
    assert not project_code_is_path_safe("CON")
    assert not project_code_is_path_safe("NUL.txt")
    assert not project_code_is_path_safe("abc.")
    assert project_code_is_path_safe("usNIVv2")


def test_shipped_paths_are_windows_compatible(package_root: Path) -> None:
    """Reject Windows device names, illegal components, case collisions, and excessive internal depth."""
    seen: dict[str, str] = {}
    longest = 0
    for path in package_root.rglob("*"):
        relative = path.relative_to(package_root)
        rendered = relative.as_posix()
        longest = max(longest, len(rendered))
        folded = rendered.casefold()
        assert folded not in seen, f"Windows case-insensitive path collision: {seen.get(folded)} / {rendered}"
        seen[folded] = rendered
        for component in relative.parts:
            assert not component.endswith((" ", ".")), f"Windows-invalid trailing character: {rendered}"
            assert not any(char in WINDOWS_ILLEGAL or ord(char) < 32 for char in component), rendered
            assert component.split(".", 1)[0].upper() not in WINDOWS_RESERVED, f"Windows device name: {rendered}"
            assert len(component) <= 255, f"Windows path component too long: {rendered}"
    assert longest <= 180, f"SAGE relative path depth leaves too little legacy MAX_PATH headroom: {longest}"


def test_runtime_sources_do_not_emit_posix_only_sage_commands(package_root: Path) -> None:
    """Keep operator-facing runtime command rendering centralized and platform-aware."""
    source_root = package_root / "system" / "src" / "sage"
    offenders = []
    for path in source_root.rglob("*.py"):
        if path.name in {"platform_commands.py", "validation.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "./system/bin/sage" in text or "system/bin/sage.cmd" in text:
            offenders.append(path.relative_to(package_root).as_posix())
    assert offenders == []

def test_windows_launcher_uses_pushd_for_unc_roots(package_root: Path) -> None:
    """Use pushd/popd so cmd.exe can enter both local-drive and UNC SAGE roots."""
    launcher = (package_root / "system" / "bin" / "sage.cmd").read_text(encoding="utf-8")
    lowered = launcher.lower()
    assert 'pushd "%root_dir%"' in lowered
    assert "popd" in lowered
    assert 'cd /d "%root_dir%"' not in lowered
