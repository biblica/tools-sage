"""Cross-platform rendering and parsing of SAGE operator command lines."""

from __future__ import annotations

import ctypes
import os
import shlex
import subprocess
from ctypes import wintypes
from typing import Sequence


def is_windows(*, windows: bool | None = None) -> bool:
    """Return the selected platform mode, defaulting to the current operating system."""
    return os.name == "nt" if windows is None else bool(windows)


def sage_launcher(*, windows: bool | None = None, root: bool = False) -> str:
    """Return the normal SAGE launcher token for the selected platform."""
    win = is_windows(windows=windows)
    if root:
        return r".\sage.cmd" if win else "./sage"
    return r".\system\bin\sage.cmd" if win else "./system/bin/sage"


def render_sage_command(
    argv: Sequence[object],
    *,
    windows: bool | None = None,
    root: bool = False,
) -> str:
    """Render one copyable SAGE command using native shell quoting and separators."""
    win = is_windows(windows=windows)
    parts = [sage_launcher(windows=win, root=root), *(str(value) for value in argv)]
    if win:
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def _split_windows_native(value: str) -> list[str]:
    """Split a Windows command line with the same Unicode parser used by Windows applications."""
    shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    argc = ctypes.c_int(0)
    command_line_to_argv = shell32.CommandLineToArgvW
    command_line_to_argv.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    command_line_to_argv.restype = ctypes.POINTER(wintypes.LPWSTR)
    argv = command_line_to_argv(value, ctypes.byref(argc))
    if not argv:
        raise ValueError("Windows command line could not be parsed")
    try:
        return [argv[index] for index in range(argc.value)]
    finally:
        kernel32.LocalFree(argv)


def split_operator_command(value: str, *, windows: bool | None = None) -> list[str]:
    """Split an operator-edited command without corrupting native Windows backslashes."""
    win = is_windows(windows=windows)
    if not win:
        return shlex.split(value)
    if os.name == "nt":
        return _split_windows_native(value)
    # Test-only fallback when Windows rendering is exercised on a non-Windows host.
    tokens = shlex.split(value, posix=False)
    return [token[1:-1] if len(token) >= 2 and token[0] == token[-1] == '"' else token for token in tokens]


def is_sage_launcher_token(value: str) -> bool:
    """Return whether one edited-command token names a supported SAGE launcher form."""
    token = str(value).strip().replace("\\", "/").casefold()
    return token in {
        "sage",
        "sage.cmd",
        "./sage.cmd",
        "./sage",
        "./system/bin/sage",
        "system/bin/sage",
        "./system/bin/sage.cmd",
        "system/bin/sage.cmd",
    }
