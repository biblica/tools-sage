"""NCA immutable reference contracts, loading, and import boundaries."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import stat
import zipfile
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

from sage.errors import ValidationError
from sage.numbers.models import (
    Extraction,
    FootnoteDecision,
    NumericExpression,
    ProjectedUnit,
    ReadingDecision,
    ReferenceBundle,
    SemanticDecision,
    TargetNote,
    TargetUnit,
)
from sage.numbers.reference import load_reference, normalize_footnote_action, parse_values
from sage.numbers.resources import import_reference
from sage.vrs import VerseRef


FIXTURE = Path(__file__).parent / "fixtures" / "reference" / "lineage"


def _refresh_inventory(root: Path) -> None:
    """Re-sign a deliberately changed synthetic package using the real manifest shape."""
    manifest_path = root / "FILE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    inventory = []
    for row in manifest["files"]:
        path = root / row["path"]
        payload = path.read_bytes()
        inventory.append(
            {
                **row,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    manifest["files"] = inventory
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    paths = [manifest_path, *(root / row["path"] for row in inventory)]
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  ./{path.relative_to(root).as_posix()}"
        for path in paths
    ]
    (root / "CHECKSUMS.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _copy_fixture(tmp_path: Path) -> Path:
    """Copy the self-contained reference package for destructive test mutations."""
    root = tmp_path / "numbers-reference"
    shutil.copytree(FIXTURE, root)
    return root


def _rewrite_tsv(root: Path, name: str, transform) -> None:
    """Rewrite one synthetic table and renew its package inventories."""
    path = root / "reference" / name
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source, delimiter="\t"))
        fields = list(rows[0]) if rows else next(csv.reader(path.open(encoding="utf-8-sig"), delimiter="\t"))
    transformed_fields, transformed_rows = transform(fields, rows)
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=transformed_fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(transformed_rows)
    _refresh_inventory(root)


def _mutate_table_row(
    root: Path,
    name: str,
    reference: VerseRef,
    **changes: str,
) -> None:
    """Change named fields on one signed fixture row selected by Western key."""
    def mutate(fields, rows):
        """Apply the requested fields to exactly one matching table record."""
        matches = [
            row
            for row in rows
            if (row.get("BK"), row.get("CH"), row.get("VS"))
            == (reference.book, str(reference.chapter), str(reference.verse))
        ]
        assert len(matches) == 1
        matches[0].update(changes)
        return fields, rows

    _rewrite_tsv(root, name, mutate)


def _archive_tree(source: Path, destination: Path) -> None:
    """Archive a fixture beneath the same single-root shape as the real package."""
    with zipfile.ZipFile(destination, "w") as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, f"{source.name}/{path.relative_to(source).as_posix()}")


def test_exact_reference_encoding() -> None:
    """Canonical values retain exact integer, sequence, and fraction meaning."""
    assert parse_values("22000;10000;5/2") == (
        Fraction(22000),
        Fraction(10000),
        Fraction(5, 2),
    )
    assert parse_values("") == ()
    assert normalize_footnote_action("NONE_TEXT_CRITICAL") == "NONE"
    assert normalize_footnote_action("N/A") == "NONE"


@pytest.mark.parametrize("raw", ["01", "+1", "2/4", " 1", "1 ", "1.5", "⅓", "1/2/3", "1/0"])
def test_unsupported_numeric_encoding_is_rejected(raw: str) -> None:
    """Permissive Fraction spellings cannot enter the reference contract."""
    with pytest.raises(ValidationError) as caught:
        parse_values(raw)
    assert caught.value.code == "NCA_REFERENCE_ENCODING_INVALID"


def test_shared_models_reject_unknown_enums_and_freeze_nested_mappings() -> None:
    """Shared records close executable vocabularies and nested mutation paths."""
    expression = NumericExpression((Fraction(3),), "CARDINAL", "three", (0, 5))
    extraction = Extraction((expression,), "COMPLETE")
    semantic = SemanticDecision("PASS_AUTHORITY1")
    note = TargetNote("n1", "+", "note", (VerseRef("MAT", 1, 1),), ({"start": 0},))
    target = TargetUnit(
        "u1",
        (VerseRef("MAT", 1, 1),),
        "three",
        (note,),
        "0" * 64,
        {"line": 1},
    )
    projected = ProjectedUnit(
        target,
        (VerseRef("MAT", 1, 1),),
        (VerseRef("MAT", 1, 1),),
        "EXACT",
        "READY",
    )
    reading = ReadingDecision("OL", semantic, "NONE", None, ())
    assert projected.status == "READY"
    assert reading.source_validation_outcome is None
    with pytest.raises(TypeError):
        note.content_spans[0]["start"] = 2
    with pytest.raises(TypeError):
        target.source_locator["line"] = 2
    for constructor in (
        lambda: NumericExpression((Fraction(1),), "UNKNOWN", "1", (0, 1)),
        lambda: Extraction((), "UNKNOWN"),
        lambda: SemanticDecision("UNKNOWN"),
        lambda: FootnoteDecision("NONE", "UNKNOWN", "NONE"),
        lambda: ProjectedUnit(target, (), (), "EXACT", "UNKNOWN"),
        lambda: ReadingDecision("UNKNOWN", semantic, "NONE", None, ()),
    ):
        with pytest.raises(ValidationError) as caught:
            constructor()
        assert caught.value.code == "NCA_MODEL_INVALID"


def test_lineage_warning_retains_authoritative_values_in_strict_and_diagnostic_modes() -> None:
    """Supplementary gaps remain visible without replacing authoritative values."""
    for qualification in ("STRICT", "DIAGNOSTIC"):
        bundle = load_reference(FIXTURE, qualification=qualification)
        row = bundle.lookup(VerseRef("MAT", 1, 1))
        assert row is not None
        assert row.ol_values == (Fraction(3), Fraction(4))
        assert row.metadata["FOOTNOTE_IF_TARGET_FOLLOWS_OL"] == "NONE"
        assert row.metadata["FOOTNOTE_IF_TARGET_FOLLOWS_ALT"] == "N/A"
        assert bundle.qualification_status == "QUALIFIED_WITH_DIAGNOSTICS"
        assert [item["code"] for item in bundle.diagnostics] == ["REFERENCE_LINEAGE_INCOMPLETE"]
        bundle.require_qualified()
        with pytest.raises(TypeError):
            row.metadata["MATCH_STATUS"] = "changed"
        with pytest.raises(TypeError):
            bundle.rows[VerseRef("MAT", 1, 2)] = row
        with pytest.raises(TypeError):
            bundle.provenance["SRC-1"]["TITLE"] = "changed"
        with pytest.raises(TypeError):
            bundle.diagnostics[0]["count"] = 0


def test_synthetic_variant_and_unit_rows_retain_governed_registry_fields() -> None:
    """The fixture exercises real-shaped nonempty variant and unit joins."""
    bundle = load_reference(FIXTURE)
    variant = bundle.variants[VerseRef("JDG", 14, 15)]
    unit = bundle.units[VerseRef("LUK", 13, 21)]
    assert variant["OL_VALUE_RESEARCHED"] == "7"
    assert variant["NIV_VALUE_RESEARCHED"] == "4"
    assert unit["REF"] == "LUK 13:21"
    assert unit["LANG"] == "GRK"
    assert unit["OL_QUANTITY"] == "3 sata"
    assert unit["NIV_QUANTITY"] == "about 60 pounds"


def test_unknown_operator_status_is_rejected(tmp_path: Path) -> None:
    """An unregistered executable status cannot qualify by agreeing in both indexes."""
    root = _copy_fixture(tmp_path)
    ref = VerseRef("MAT", 1, 1)
    _mutate_table_row(root, "SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv", ref, MATCH_STATUS="ALIEN_STATUS")
    _mutate_table_row(root, "canonical_number_index.tsv", ref, MATCH_STATUS="ALIEN_STATUS")
    with pytest.raises(ValidationError) as caught:
        load_reference(root)
    assert caught.value.code == "NCA_REFERENCE_CONTRACT_CONFLICT"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("TARGET_DEFAULT", "FOLLOW_TRANSLATION"),
        ("TARGET_VALIDATION_RULE", "ACCEPT_ANY_VALUE"),
    ],
)
def test_unknown_operator_execution_policy_is_rejected(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    """Signed free text cannot replace the operator's status-bound execution policy."""
    root = _copy_fixture(tmp_path)
    _mutate_table_row(
        root,
        "SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv",
        VerseRef("MAT", 1, 1),
        **{field: value},
    )
    with pytest.raises(ValidationError) as caught:
        load_reference(root)
    assert caught.value.code == "NCA_REFERENCE_CONTRACT_CONFLICT"


def test_unregistered_blank_ol_row_is_rejected(tmp_path: Path) -> None:
    """Empty OL fields require the explicit registered-absence reading policy."""
    root = _copy_fixture(tmp_path)
    ref = VerseRef("MAT", 1, 1)
    blank = {"LANG": "", "OL_REF": "", "OL_TEXT": "", "OL_VALUES": ""}
    _mutate_table_row(root, "SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv", ref, **blank)
    _mutate_table_row(root, "canonical_number_index.tsv", ref, **blank)
    with pytest.raises(ValidationError) as caught:
        load_reference(root)
    assert caught.value.code == "NCA_REFERENCE_CONTRACT_CONFLICT"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("REF", "LUK 13:22"),
        ("LANG", "HEB"),
        ("OL_QUANTITY", ""),
        ("NIV_QUANTITY", "about sixty pounds"),
    ],
)
def test_invalid_unit_identity_or_quantity_contract_is_rejected(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    """Unit evidence must retain its registered coordinate, language, and typed quantities."""
    root = _copy_fixture(tmp_path)
    _mutate_table_row(root, "unit_conversion_registry.tsv", VerseRef("LUK", 13, 21), **{field: value})
    with pytest.raises(ValidationError) as caught:
        load_reference(root)
    assert caught.value.code == "NCA_REFERENCE_CONTRACT_CONFLICT"


def test_variant_value_must_match_authoritative_sequence(tmp_path: Path) -> None:
    """A signed variant row cannot redefine the operator index's OL sequence."""
    root = _copy_fixture(tmp_path)
    _mutate_table_row(
        root,
        "textual_variant_registry.tsv",
        VerseRef("JDG", 14, 15),
        OL_VALUE_RESEARCHED="8",
    )
    with pytest.raises(ValidationError) as caught:
        load_reference(root)
    assert caught.value.code == "NCA_REFERENCE_CONTRACT_CONFLICT"


def test_invalid_expression_ordinal_becomes_governed_diagnostic(tmp_path: Path) -> None:
    """Malformed supplementary ordinals cannot escape DIAGNOSTIC as raw ValueError."""
    root = _copy_fixture(tmp_path)
    path = root / "reference" / "ol_expression_audit.tsv"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("MAT 1:1\tGRK\t1\t", "MAT 1:1\tGRK\tnot-an-int\t", 1), encoding="utf-8")
    _refresh_inventory(root)
    bundle = load_reference(root, qualification="DIAGNOSTIC")
    assert bundle.qualification_status == "BLOCKED"
    assert bundle.diagnostics[0]["code"] == "NCA_REFERENCE_CONTRACT_CONFLICT"


def test_required_registry_provenance_cannot_be_blank(tmp_path: Path) -> None:
    """Variant policy records cannot silently qualify without source identity."""
    root = _copy_fixture(tmp_path)
    ref = VerseRef("JDG", 14, 15)
    _mutate_table_row(
        root,
        "SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv",
        ref,
        SOURCE_IDS="",
        SOURCE_URLS="",
    )
    _mutate_table_row(root, "textual_variant_registry.tsv", ref, SOURCE_IDS="")
    _mutate_table_row(root, "footnote_guidance.tsv", ref, SOURCE_IDS="", SOURCE_URLS="")
    with pytest.raises(ValidationError) as caught:
        load_reference(root)
    assert caught.value.code == "NCA_REFERENCE_PROVENANCE_MISSING"


def test_checksum_failure_blocks_strict_loading(tmp_path: Path) -> None:
    """A changed file cannot pass strict reference qualification."""
    root = _copy_fixture(tmp_path)
    path = root / "reference" / "SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValidationError) as caught:
        load_reference(root)
    assert caught.value.code == "NCA_REFERENCE_CHECKSUM_FAILED"


def test_diagnostic_loading_retains_blocking_diagnostics(tmp_path: Path) -> None:
    """Diagnostic mode reports unsafe bytes without exposing partial records."""
    root = _copy_fixture(tmp_path)
    path = root / "reference" / "SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv"
    path.write_bytes(path.read_bytes() + b"\n")
    bundle = load_reference(root, qualification="DIAGNOSTIC")
    assert bundle.qualification_status == "BLOCKED"
    assert bundle.diagnostics[0]["code"] == "NCA_REFERENCE_CHECKSUM_FAILED"
    with pytest.raises(ValidationError) as caught:
        bundle.require_qualified()
    assert caught.value.code == "NCA_REFERENCE_NOT_QUALIFIED"


def test_duplicate_western_keys_are_rejected_after_integrity_verification(tmp_path: Path) -> None:
    """A signed package still fails when two rows claim one Western key."""
    root = _copy_fixture(tmp_path)

    def duplicate(fields, rows):
        """Add a second authoritative row with the same Western coordinate."""
        return fields, [*rows, dict(rows[0])]

    _rewrite_tsv(root, "SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv", duplicate)
    manifest = json.loads((root / "HANDOVER_VERIFICATION.json").read_text(encoding="utf-8"))
    manifest["operator_index_rows"] = 2
    (root / "HANDOVER_VERIFICATION.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _refresh_inventory(root)
    with pytest.raises(ValidationError) as caught:
        load_reference(root)
    assert caught.value.code == "NCA_REFERENCE_DUPLICATE_KEY"


def test_missing_required_column_is_rejected(tmp_path: Path) -> None:
    """The loader refuses signed tables that omit a runtime authority field."""
    root = _copy_fixture(tmp_path)

    def remove_column(fields, rows):
        """Remove OL_VALUES from both the header and fixture records."""
        fields.remove("OL_VALUES")
        for row in rows:
            row.pop("OL_VALUES")
        return fields, rows

    _rewrite_tsv(root, "SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv", remove_column)
    with pytest.raises(ValidationError) as caught:
        load_reference(root)
    assert caught.value.code == "NCA_REFERENCE_COLUMNS_MISSING"


def test_unresolved_source_id_is_rejected(tmp_path: Path) -> None:
    """Every referenced provenance identifier must resolve inside the package."""
    root = _copy_fixture(tmp_path)

    def missing_source(fields, rows):
        """Point the authority row at an absent provenance record."""
        rows[0]["SOURCE_IDS"] = "UNKNOWN-SOURCE"
        return fields, rows

    _rewrite_tsv(root, "SAGE_NUMBERS_OPERATOR_VALIDATION_INDEX.tsv", missing_source)
    with pytest.raises(ValidationError) as caught:
        load_reference(root)
    assert caught.value.code == "NCA_REFERENCE_PROVENANCE_MISSING"


def test_non_utf8_table_is_rejected(tmp_path: Path) -> None:
    """Checksummed table bytes still require strict UTF-8 decoding."""
    root = _copy_fixture(tmp_path)
    path = root / "reference" / "provenance_sources.tsv"
    path.write_bytes(b"SOURCE_ID\tTITLE\nSRC-1\t\xff\n")
    _refresh_inventory(root)
    with pytest.raises(ValidationError) as caught:
        load_reference(root)
    assert caught.value.code == "NCA_REFERENCE_ENCODING_INVALID"


def test_contradictory_authoritative_canonical_values_are_rejected(tmp_path: Path) -> None:
    """Operator and canonical OL values cannot contradict each other."""
    root = _copy_fixture(tmp_path)

    def conflict(fields, rows):
        """Change the canonical OL sequence while keeping a valid encoding."""
        rows[0]["OL_VALUES"] = "3"
        return fields, rows

    _rewrite_tsv(root, "canonical_number_index.tsv", conflict)
    with pytest.raises(ValidationError) as caught:
        load_reference(root)
    assert caught.value.code == "NCA_REFERENCE_CONTRACT_CONFLICT"


def test_manifest_cardinalities_are_enforced(tmp_path: Path) -> None:
    """Published table counts cannot be bypassed by a smaller signed table."""
    root = _copy_fixture(tmp_path)
    verification = json.loads((root / "HANDOVER_VERIFICATION.json").read_text(encoding="utf-8"))
    verification["operator_index_rows"] = 2
    (root / "HANDOVER_VERIFICATION.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    _refresh_inventory(root)
    with pytest.raises(ValidationError) as caught:
        load_reference(root)
    assert caught.value.code == "NCA_REFERENCE_CARDINALITY_MISMATCH"


def test_archive_import_preserves_bytes_and_writes_external_receipt(tmp_path: Path) -> None:
    """Import publishes unchanged files and keeps qualification state external."""
    archive = tmp_path / "reference.zip"
    _archive_tree(FIXTURE, archive)
    config = SimpleNamespace(data_root=tmp_path / "localdata", root=tmp_path / "app")
    published = import_reference(config, archive)
    assert published.parent == config.data_root / "inputs" / "resources" / "numbers"
    for source in FIXTURE.rglob("*"):
        if source.is_file():
            assert (published / source.relative_to(FIXTURE)).read_bytes() == source.read_bytes()
    assert not (published / "qualification.json").exists()
    receipt = config.data_root / ".system" / "state" / "numbers" / "qualification" / f"{published.name}.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["qualification_status"] == "QUALIFIED_WITH_DIAGNOSTICS"
    assert payload["package_root"] == str(published)
    assert payload["archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()


@pytest.mark.parametrize("member", ["../escape", "/absolute", "root/../../escape", "C:/escape"])
def test_archive_import_rejects_unsafe_member_paths(tmp_path: Path, member: str) -> None:
    """Archive paths cannot escape or bypass the single publication root."""
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(member, b"bad")
    config = SimpleNamespace(data_root=tmp_path / "localdata", root=tmp_path / "app")
    with pytest.raises(ValidationError) as caught:
        import_reference(config, archive)
    assert caught.value.code == "NCA_REFERENCE_ARCHIVE_INVALID"
    assert not (config.data_root / "inputs" / "resources" / "numbers").exists()


def test_archive_import_rejects_symlinks(tmp_path: Path) -> None:
    """A ZIP symlink cannot redirect immutable resource publication."""
    archive = tmp_path / "symlink.zip"
    member = zipfile.ZipInfo("root/link")
    member.create_system = 3
    member.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(member, "target")
    config = SimpleNamespace(data_root=tmp_path / "localdata", root=tmp_path / "app")
    with pytest.raises(ValidationError) as caught:
        import_reference(config, archive)
    assert caught.value.code == "NCA_REFERENCE_ARCHIVE_INVALID"


def test_manifest_package_id_cannot_escape_publication_root(tmp_path: Path) -> None:
    """A signed manifest identity cannot become a path outside numbers resources."""
    root = _copy_fixture(tmp_path)
    for name in ("FILE_MANIFEST.json", "HANDOVER_VERIFICATION.json"):
        path = root / name
        document = json.loads(path.read_text(encoding="utf-8"))
        document["handover"] = "../../escaped"
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    _refresh_inventory(root)
    archive = tmp_path / "escaped.zip"
    _archive_tree(root, archive)
    config = SimpleNamespace(data_root=tmp_path / "localdata", root=tmp_path / "app")
    with pytest.raises(ValidationError) as caught:
        import_reference(config, archive)
    assert caught.value.code == "NCA_REFERENCE_MANIFEST_INVALID"
    assert not (config.data_root / "inputs" / "escaped").exists()


def test_receipt_failure_rolls_back_new_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A newly visible package cannot survive failure of its qualification receipt."""
    archive = tmp_path / "reference.zip"
    _archive_tree(FIXTURE, archive)
    config = SimpleNamespace(data_root=tmp_path / "localdata", root=tmp_path / "app")

    def fail_receipt(*args, **kwargs):
        """Simulate external receipt persistence failing after package validation."""
        raise OSError("receipt unavailable")

    monkeypatch.setattr("sage.numbers.resources._write_receipt", fail_receipt)
    with pytest.raises(OSError, match="receipt unavailable"):
        import_reference(config, archive)
    destination = (
        config.data_root
        / "inputs"
        / "resources"
        / "numbers"
        / "SYNTHETIC_NCA_REFERENCE_1"
    )
    assert not destination.exists()
