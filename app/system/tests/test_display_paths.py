"""Operator path rendering preserves full paths internally and shortens only display text."""

from pathlib import Path

from sage.display_paths import operator_path, operator_text


def test_operator_paths_are_checkout_relative_only_for_display(tmp_path: Path) -> None:
    """Internal checkout paths shorten while external paths and stored values remain full."""
    app = tmp_path / "SAGE" / "app"
    internal = tmp_path / "SAGE" / "localdata" / "reports" / "report.md"
    external = tmp_path / "outside" / "report.md"

    assert operator_path(app, internal) == ".../localdata/reports/report.md"
    assert operator_path(app, external) == str(external.resolve())
    assert operator_text(app, f"Report: {internal}") == "Report: .../localdata/reports/report.md"
