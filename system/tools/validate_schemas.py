#!/usr/bin/env python3
"""Validate all shipped SAGE schema contracts and applicable source instances."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "system" / "src"))

from sage.schema_validation import validate_schema_contracts


def main() -> int:
    """Run the schema-contract gate and return a blocking process status."""
    result = validate_schema_contracts(ROOT)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
