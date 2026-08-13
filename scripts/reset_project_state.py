#!/usr/bin/env python3
"""Reset generated SAGE runtime, task, transaction, receipt, and test state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Maintenance scripts must not contaminate the workspace they are inspecting.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from sage_core.registry import load_ecosystem
from sage_core.reset_state import reset_project_state


def main() -> int:
    """Load the selected ecosystem, remove generated state, and print the reset receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--settings",
        default="ecosystem.yml",
        help="Settings file, resolved relative to the SAGE root when not absolute.",
    )
    parser.add_argument(
        "--keep-test-artifacts",
        action="store_true",
        help="Preserve test artefacts while still removing normal generated runtime state.",
    )
    args = parser.parse_args()

    settings = Path(args.settings)
    if not settings.is_absolute():
        settings = ROOT / settings

    config = load_ecosystem(settings.resolve())
    result = reset_project_state(
        config,
        include_test_artifacts=not args.keep_test_artifacts,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
