"""The typed NCA reference package (rebuilt OL + NIV layers) and its loader."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from sage.errors import ValidationError
from sage.numbers.compare import compare_group
from sage.numbers.reference import is_typed_package, load_reference
from sage.numbers.resources import resolve_reference_package
from sage.vrs import VerseRef

F = Fraction


def _pinned(package_root: Path) -> Path:
    """The Core-pinned package directory."""
    pin = json.loads((package_root / "system/config/numbers-reference.json").read_text(encoding="utf-8"))
    return package_root / pin["path"]


def test_core_pin_is_the_typed_package(package_root):
    """The bundled default is the typed package and qualifies with only its provisional-row warning."""
    path = _pinned(package_root)
    assert is_typed_package(path)
    bundle = resolve_reference_package(SimpleNamespace(root=package_root))
    assert bundle.package_id.startswith("SAGE_NUMBERS_TYPED_")
    assert {item["code"] for item in bundle.diagnostics} <= {"NCA_REFERENCE_PROVISIONAL_ROWS"}


def test_typed_rows_carry_what_each_number_counts(package_root):
    """EZR 1:10 keeps both layers with the items each number counts."""
    row = load_reference(_pinned(package_root)).lookup(VerseRef("EZR", 1, 10))
    assert row.ol_values == row.niv_values == (F(30), F(410), F(1000))
    assert [item["REFERENT"] for item in row.niv_items] == ["gold bowls", "matching silver bowls", "other articles"]
    assert all(item["REFERENT"] for item in row.ol_items)
    assert row.metadata["MATCH_STATUS"] == "PASS_EXACT"


def test_pinned_package_referent_errata_are_applied(package_root):
    """EZK 48:34: the 4,500 measures the west side and the 3 counts its gates (the package says "gates", "gate")."""
    row = load_reference(_pinned(package_root)).lookup(VerseRef("EZK", 48, 34))
    assert [item["REFERENT"] for item in row.ol_items][:2] == ["west", "gates"]


def test_pinned_package_value_errata_are_applied(package_root):
    """Unit titles ("officials over fifties and tens") are not counted; "a thousand officers" is."""
    bundle = load_reference(_pinned(package_root))
    assert bundle.lookup(VerseRef("EXO", 18, 21)).ol_values == ()
    captain = bundle.lookup(VerseRef("2KI", 1, 13))
    assert captain.ol_values == (F(50), F(50)) and [item["EXPR_NO"] for item in captain.ol_items] == ["1", "2"]
    officers = bundle.lookup(VerseRef("1CH", 12, 34))
    assert officers.ol_values == officers.niv_values == (F(1000), F(37000))
    assert [item["EXPR_NO"] for item in officers.ol_items] == ["1", "2"]


def test_text_critical_registries_carry_over_unchanged(package_root):
    """Textual variants, footnote guidance and unit conversions are the curated 2026-09-09 bytes."""
    typed = _pinned(package_root) / "reference"
    old = package_root / "system/resources/numbers/2026-09-09/reference"
    for name in ("textual_variant_registry.tsv", "footnote_guidance.tsv", "unit_conversion_registry.tsv",
                 "provenance_sources.tsv", "eng_org_map_rules.txt"):
        assert (typed / name).read_bytes() == (old / name).read_bytes()
    bundle = load_reference(_pinned(package_root))
    absent = bundle.lookup(VerseRef("NEH", 7, 68))
    assert absent is not None and absent.ol_values == () and absent.niv_values == (F(736), F(245))
    assert VerseRef("NEH", 7, 68) in bundle.footnote_guidance


@pytest.mark.parametrize("damage", ["edit", "extra", "missing"])
def test_typed_package_fails_closed_on_damage(package_root, tmp_path, damage):
    """A changed, added or removed file is refused (an integrity guard, not a content judgment)."""
    path = tmp_path / "package"
    shutil.copytree(_pinned(package_root), path)
    if damage == "edit":
        with (path / "reference/values.tsv").open("a", encoding="utf-8") as handle:
            handle.write("corrupt\n")
    elif damage == "extra":
        (path / "reference/extra.tsv").write_text("x\n", encoding="utf-8")
    else:
        (path / "reference/verses.tsv").unlink()
    with pytest.raises(ValidationError):
        load_reference(path)


def test_package_identity_is_the_checksum_file_digest(package_root):
    """The package SHA-256 is the digest of CHECKSUMS.sha256, as the Core pin records it."""
    path = _pinned(package_root)
    bundle = load_reference(path)
    assert bundle.sha256 == hashlib.sha256((path / "CHECKSUMS.sha256").read_bytes()).hexdigest()


def test_mismatch_on_a_provisional_row_is_review_not_fail():
    """A rebuilt value nobody has reviewed yet can raise a review item, never a FAIL."""
    from sage.numbers.models import ReferenceRow
    provisional = ReferenceRow(VerseRef("GEN", 5, 3), "GEN 5:3", "HEB", "", (F(130),), "", (),
                               {"MATCH_STATUS": "OL_EXPLICIT_NIV_NONEXPLICIT", "OL_REVIEW_STATUS": "PROVISIONAL"})
    result = compare_group((F(131),), [provisional], mode="UNORDERED")
    assert result.outcome == "NEEDS_REVIEW" and result.review_context["kind"] == "INDEX_UNSETTLED" and result.review_context["reason"] == "PROVISIONAL_INDEX"


def test_rule_decisions_leave_no_provisional_rows(package_root):
    """Every open review item carries a recorded decision, so the shipped package has no provisional rows."""
    bundle = load_reference(_pinned(package_root))
    assert not [row for row in bundle.rows.values() if "PROVISIONAL" in (
        row.metadata["OL_REVIEW_STATUS"], row.metadata["NIV_REVIEW_STATUS"])]
