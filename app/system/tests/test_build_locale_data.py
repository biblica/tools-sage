"""Offline --check coverage for the CLDR locale-facts vendoring tool."""
import json
import subprocess
import sys
from pathlib import Path

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
TOOL = PACKAGE_ROOT / "system/tools/build_locale_data.py"
BUNDLE = PACKAGE_ROOT / "system/src/sage/data/cldr-locale-facts.json"


def _run_check(output: Path) -> subprocess.CompletedProcess:
    """Invoke the vendoring tool's offline --check mode against one bundle path."""
    return subprocess.run(
        [sys.executable, str(TOOL), "--check", "--output", str(output)],
        cwd=PACKAGE_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_check_passes_against_the_committed_bundle_with_no_network_call() -> None:
    """The vendored bundle already covers every ecosystem.yml language_profiles tag."""
    result = _run_check(BUNDLE)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "PASS"
    assert payload["locales_registered"] > 0


def test_check_reports_a_gap_without_crashing(tmp_path: Path) -> None:
    """Removing one registered tag's coverage must be reported, not crash the tool."""
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    bundle["locales"].pop("uk-UA", None)
    bundle["locales"].pop("uk", None)
    bundle["locales"].pop("en", None)
    incomplete = tmp_path / "cldr-locale-facts.json"
    incomplete.write_text(json.dumps(bundle), encoding="utf-8")

    result = _run_check(incomplete)
    assert result.returncode == 1
    assert "uk-UA" in result.stderr


def test_check_reports_a_missing_bundle_file(tmp_path: Path) -> None:
    """A bundle path that does not exist must be reported, not raise an unhandled error."""
    result = _run_check(tmp_path / "does-not-exist.json")
    assert result.returncode == 1
    assert "missing vendored bundle" in result.stderr


@pytest.mark.parametrize("tag", ["en", "pt-BR", "hi-IN", "ar-SA"])
def test_bundle_entries_have_all_three_field_groups(tag: str) -> None:
    """Every sampled bundle entry must carry all three locale-facts field groups."""
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    entry = bundle["locales"][tag]
    assert set(entry) == {"numbers", "punctuation", "datetime"}
