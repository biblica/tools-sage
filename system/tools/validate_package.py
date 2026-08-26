#!/usr/bin/env python3
"""Validate a SAGE source tree without creating runtime artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Package validation must not create the bytecode that it is designed to detect.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "system" / "src"))

from sage.validation import validate_package


def main() -> int:
    """Validate the source package, print stable JSON, and return a blocking exit code."""
    result = validate_package(ROOT)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if result["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
