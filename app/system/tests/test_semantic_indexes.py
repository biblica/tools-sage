"""Local-first RWC, SEMDOM, FLEx/Combine, and semantic-index regressions."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from openpyxl import Workbook

from sage.storage import storage_layout
from sage.hashing import sha256_file
from sage.registry import load_ecosystem
from sage.semantic.diagnostics import analysis_signals_from_scope_evidence
from sage.semantic.evidence import scope_evidence_for_project
from sage.semantic.indexes import semantic_status
from sage.semantic.importers import (
    import_lift_snapshot,
    import_rwc_seed_xlsx,
    import_semdom_authority_json,
    import_specific_first_docx,
)
from sage.semantic.indexes import build_semantic_indexes
from sage.semantic.lift import export_lift
from sage.semantic.store import load_import_selection, set_binding, set_import_active, set_review_state


def _rwc_workbook(path: Path) -> None:
    """Create a compact KKH-style RWC seed workbook."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Entire Luke"
    sheet.append(["idKKHv0 Text", "English gloss", "Key Term", "SIL SemDom"])
    sheet.append(["meka", "carry", "Yes", "7.3.1 Carry"])
    sheet.append(["luma", "speak", "No", "3.5.1 Say"])
    book.save(path)


def _specific_first_docx(path: Path) -> None:
    """Create a minimal DOCX container with enough unique folder divisions for validation."""
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    paragraphs: list[str] = []
    for index in range(1, 102):
        paragraphs.append(
            f'<w:p><w:r><w:t>{index} Domain {index}</w:t></w:r></w:p>'
        )
        paragraphs.append('<w:p><w:r><w:t>----------</w:t></w:r></w:p>')
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{namespace}"><w:body>'
        + "".join(paragraphs)
        + "</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)


def test_rwc_seed_builds_local_indexes_and_binds_idkkh_to_kkh(make_workspace, tmp_path: Path) -> None:
    """Verify KKH seed data builds locally while idKKHv0 remains an explicit project binding."""
    root = make_workspace(qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    source = tmp_path / "KKH-Luke.xlsx"
    _rwc_workbook(source)
    result = import_rwc_seed_xlsx(config, source, source_id="KKH-Luke-RWC", language="KKH", headword_column="idKKHv0 Text")
    assert result["record_count"] == 2
    assert result["status"] == "SEED"
    set_binding(config, project_id="idKKHv0", language="KKH")
    coverage = build_semantic_indexes(config, language="KKH")
    assert coverage["lemmas"] == 0
    assert coverage["lexical_heads"] == 2
    assert coverage["semantic_domains"] == 2
    evidence = scope_evidence_for_project(config, project_id="idKKHv0", text="meka meka luma")
    assert evidence["semantic_language"] == "KKH"
    assert evidence["matched_record_count"] == 2
    assert {item["surface_form"] for item in evidence["matches"]} == {"meka", "luma"}


def test_import_snapshots_are_immutable_and_selection_is_external(make_workspace, tmp_path: Path) -> None:
    """Verify repeated imports cannot overwrite snapshots and inactive imports leave index evidence."""
    root = make_workspace(qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    first = tmp_path / "first.xlsx"
    _rwc_workbook(first)
    imported = import_rwc_seed_xlsx(config, first, source_id="RWC-BASE", language="KKH", headword_column="idKKHv0 Text")
    assert imported["status_detail"] == "IMPORTED_IMMUTABLE_SNAPSHOT"
    repeated = import_rwc_seed_xlsx(config, first, source_id="RWC-BASE", language="KKH", headword_column="idKKHv0 Text")
    assert repeated["status_detail"] == "UNCHANGED_IMMUTABLE_SNAPSHOT"
    assert load_import_selection(config, "KKH") == ["RWC-BASE"]
    set_import_active(config, language="KKH", source_id="RWC-BASE", active=False)
    assert load_import_selection(config, "KKH") == []
    from sage.errors import ValidationError
    try:
        build_semantic_indexes(config, language="KKH")
    except ValidationError as exc:
        assert "No semantic imports" in str(exc)
    else:
        raise AssertionError("Inactive semantic imports must not feed generated indexes")


def test_imports_are_project_index_only_and_not_scripture_authority(make_workspace, tmp_path: Path) -> None:
    """Verify retained semantic imports are governed project-index evidence, not content authority."""
    root = make_workspace(qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    source = tmp_path / "KKH-Luke.xlsx"
    _rwc_workbook(source)
    result = import_rwc_seed_xlsx(
        config, source, source_id="RWC-PROJECT-INDEX", language="KKH", headword_column="idKKHv0 Text"
    )
    assert result["authority"] == "PROJECT_INDEX_ONLY"
    assert result["evidence_class"] == "PROJECT_INDEX_EVIDENCE"
    assert result["translation_authority"] is False
    assert result["scripture_authority"] is False


def test_lift_import_is_namespace_neutral_and_exports_are_new_files(make_workspace, tmp_path: Path) -> None:
    """Verify immutable LIFT input supports namespaces and separate FLEx/Combine output views."""
    root = make_workspace(qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    source = tmp_path / "lexicon.lift"
    source.write_text(
        '''<?xml version="1.0" encoding="UTF-8"?>\n'''
        '''<lift xmlns="urn:test-lift" version="0.13">'''
        '''<entry id="E1"><lexical-unit><form lang="KKH"><text>meka</text></form></lexical-unit>'''
        '''<sense id="S1"><gloss><form lang="id"><text>membawa</text></form></gloss>'''
        '''<definition><form lang="en"><text>carry something</text></form></definition>'''
        '''<grammatical-info value="verb"/><trait name="semantic-domain-ddp4" value="7.3.1 Carry"/>'''
        '''</sense></entry></lift>''',
        encoding="utf-8",
    )
    original_hash = sha256_file(source)
    result = import_lift_snapshot(
        config,
        source,
        source_id="KKH-FLEx",
        source_application="FLEx",
        language="KKH",
    )
    assert result["record_count"] == 1
    records = json.loads((Path(result["import_root"]) / "records.json").read_text(encoding="utf-8"))
    assert records[0]["record_id"] != "E1"
    assert records[0]["provenance"]["source_entry_id"] == "E1"
    assert records[0]["senses"][0]["sense_id"] != "S1"
    assert records[0]["senses"][0]["source_sense_id"] == "S1"
    assert sha256_file(source) == original_hash
    build_semantic_indexes(config, language="KKH")
    flex = export_lift(config, language="KKH", profile="flex", view="starter", output=tmp_path / "out-flex.lift")
    combine = export_lift(config, language="KKH", profile="combine", view="starter", output=tmp_path / "out-combine.lift")
    flex_text = Path(flex["output"]).read_text(encoding="utf-8")
    combine_text = Path(combine["output"]).read_text(encoding="utf-8")
    assert "grammatical-info" in flex_text
    assert "SAGE-status" in flex_text
    assert "grammatical-info" not in combine_text
    assert "SAGE-status" not in combine_text
    assert any("FLEx profile retains" in rule for rule in flex["rules"])
    assert any("Combine profile intentionally omits" in rule for rule in combine["rules"])
    assert sha256_file(source) == original_hash


def test_semdom_and_rapidwords_resources_are_classification_not_translation_authority(
    make_workspace, tmp_path: Path
) -> None:
    """Verify SIL authority and RapidWords traversal metadata keep translation authority false."""
    root = make_workspace(qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    semdom_path = tmp_path / "semdom.json"
    semdom_path.write_text(
        json.dumps(
            [
                {
                    "code": "7.3.1",
                    "name": "Carry",
                    "guid": "guid-1",
                    "description": "Move while supporting.",
                    "questions": [],
                    "childCodes": [],
                    "relatedGuids": [],
                }
            ]
        ),
        encoding="utf-8",
    )
    authority = import_semdom_authority_json(config, semdom_path)
    assert authority["semantic_authority"] is True
    assert authority["translation_authority"] is False
    folder_path = tmp_path / "folders.docx"
    _specific_first_docx(folder_path)
    folders = import_specific_first_docx(config, folder_path)
    assert folders["processing_metadata_only"] is True
    assert folders["translation_authority"] is False
    assert folders["folder_count"] == 101
    from sage.semantic.indexes import semantic_status
    status = semantic_status(config, language="KKH")
    assert status["active_authority"]["sil_semdom"] == "sil-semdom-v4"
    assert status["active_authority"]["rapidwords_folders"] == "rapidwords-specific-first-v4"


def test_saw_semantic_signals_are_triage_only() -> None:
    """Verify local index anomalies remain SAW interrogation candidates rather than findings."""
    packet = {
        "project_id": "idKKHv0",
        "semantic_language": "KKH",
        "matches": [
            {
                "surface_form": "meka",
                "senses": [
                    {"sense_id": "S1", "semdom": [{"code": "1.1"}]},
                    {"sense_id": "S2", "semdom": [{"code": "3.2"}]},
                    {"sense_id": "S3", "semdom": [{"code": "7.4"}]},
                ],
            }
        ],
    }
    result = analysis_signals_from_scope_evidence(packet)
    assert result["signal_count"] == 2
    assert {item["signal"] for item in result["signals"]} == {
        "MULTIPLE_INDEXED_SENSES",
        "BROAD_SEMANTIC_DISPERSION",
    }
    assert all(item["interpretation"] == "TRIAGE_ONLY" for item in result["signals"])
    assert "must verify" in result["authority_rule"]



def test_semantic_index_freshness_fails_closed_after_input_change(make_workspace, tmp_path: Path) -> None:
    """Verify active-source changes make indexes stale and prevent bound BIC/SAW retrieval until rebuild."""
    from sage.errors import ValidationError

    root = make_workspace(qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    source = tmp_path / "KKH-Luke.xlsx"
    _rwc_workbook(source)
    import_rwc_seed_xlsx(config, source, source_id="RWC-BASE", language="KKH", headword_column="idKKHv0 Text")
    set_binding(config, project_id="idKKHv0", language="KKH")
    build_semantic_indexes(config, language="KKH")
    assert semantic_status(config, language="KKH")["index_state"] == "CURRENT"

    set_import_active(config, language="KKH", source_id="RWC-BASE", active=False)
    status = semantic_status(config, language="KKH")
    assert status["index_state"] == "STALE"
    assert status["indexes_ready"] is False
    try:
        scope_evidence_for_project(config, project_id="idKKHv0", text="meka")
    except ValidationError as exc:
        assert "STALE" in str(exc)
    else:
        raise AssertionError("Bound BIC/SAW evidence retrieval must reject stale semantic indexes")


def test_lift_import_cannot_grant_approval_and_review_state_is_separate(make_workspace, tmp_path: Path) -> None:
    """Verify imported LIFT is OBSERVED and approval requires an explicit reviewed-state action."""
    root = make_workspace(qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    source = tmp_path / "lexicon.lift"
    source.write_text(
        '<lift version="0.13"><entry id="E1"><lexical-unit><form lang="KKH"><text>meka</text></form></lexical-unit>'
        '<sense id="S1"><gloss><form lang="id"><text>membawa</text></form></gloss></sense></entry></lift>',
        encoding="utf-8",
    )
    imported = import_lift_snapshot(
        config,
        source,
        source_id="KKH-FLEx",
        source_application="FLEx",
        language="KKH",
    )
    records = json.loads((Path(imported["import_root"]) / "records.json").read_text(encoding="utf-8"))
    sense_id = records[0]["senses"][0]["sense_id"]
    assert records[0]["senses"][0]["status"] == "OBSERVED"

    build_semantic_indexes(config, language="KKH")
    set_review_state(
        config,
        language="KKH",
        sense_id=sense_id,
        status="APPROVED",
        reviewer="LC",
        note="Reviewed in project lexical work",
    )
    assert semantic_status(config, language="KKH")["index_state"] == "STALE"
    build_semantic_indexes(config, language="KKH")
    sense_doc = json.loads((storage_layout(root).indexes_root / "semantic" / "languages" / "KKH" / "indexes" / "sense-semdom.json").read_text(encoding="utf-8"))
    assert sense_doc["senses"][sense_id]["status"] == "APPROVED"
    assert sense_doc["senses"][sense_id]["imported_status"] == "OBSERVED"


def test_lift_exports_require_explicit_status_view(make_workspace, tmp_path: Path) -> None:
    """Verify starter and approved views are explicit and filter senses deterministically."""
    root = make_workspace(qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    source = tmp_path / "lexicon.lift"
    source.write_text(
        '<lift version="0.13"><entry id="E1"><lexical-unit><form lang="KKH"><text>meka</text></form></lexical-unit>'
        '<sense id="S1"><gloss><form lang="id"><text>membawa</text></form></gloss></sense></entry></lift>',
        encoding="utf-8",
    )
    imported = import_lift_snapshot(config, source, source_id="KKH-FLEx", source_application="FLEx", language="KKH")
    records = json.loads((Path(imported["import_root"]) / "records.json").read_text(encoding="utf-8"))
    sense_id = records[0]["senses"][0]["sense_id"]
    build_semantic_indexes(config, language="KKH")

    starter = export_lift(config, language="KKH", profile="combine", view="starter", output=tmp_path / "starter.lift")
    approved_empty = export_lift(config, language="KKH", profile="flex", view="approved", output=tmp_path / "approved-empty.lift")
    assert starter["sense_count"] == 1
    assert approved_empty["sense_count"] == 0

    set_review_state(config, language="KKH", sense_id=sense_id, status="APPROVED", reviewer="LC")
    build_semantic_indexes(config, language="KKH")
    approved = export_lift(config, language="KKH", profile="flex", view="approved", output=tmp_path / "approved.lift")
    assert approved["sense_count"] == 1
    assert approved["exported_status_counts"] == {"APPROVED": 1}


def test_stable_lift_identity_reconciles_duplicates_but_preserves_conflicts(make_workspace, tmp_path: Path) -> None:
    """Verify repeated stable LIFT IDs dedupe for retrieval only when their indexed content agrees."""
    root = make_workspace(qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")

    def write_lift(path: Path, domain: str) -> None:
        """Write one minimal LIFT fixture with a stable external sense identity."""
        path.write_text(
            '<lift version="0.13"><entry id="E1"><lexical-unit><form lang="KKH"><text>meka</text></form></lexical-unit>'
            f'<sense id="S1"><gloss><form lang="id"><text>membawa</text></form></gloss>'
            f'<trait name="semantic-domain-ddp4" value="{domain}"/></sense></entry></lift>',
            encoding="utf-8",
        )

    first = tmp_path / "first.lift"
    second = tmp_path / "second.lift"
    write_lift(first, "7.3.1 Carry")
    write_lift(second, "7.3.1 Carry")
    import_lift_snapshot(config, first, source_id="FLEX-A", source_application="FLEx", language="KKH")
    import_lift_snapshot(config, second, source_id="FLEX-B", source_application="FLEx", language="KKH")
    set_binding(config, project_id="idKKHv0", language="KKH")
    coverage = build_semantic_indexes(config, language="KKH")
    assert coverage["reconciled_duplicate_groups"] == 1
    packet = scope_evidence_for_project(config, project_id="idKKHv0", text="meka")
    assert len(packet["matches"][0]["senses"]) == 1

    third = tmp_path / "third.lift"
    write_lift(third, "3.5.1 Say")
    import_lift_snapshot(config, third, source_id="FLEX-C", source_application="FLEx", language="KKH")
    coverage = build_semantic_indexes(config, language="KKH")
    assert coverage["reconciliation_conflicts"] == 1
    packet = scope_evidence_for_project(config, project_id="idKKHv0", text="meka")
    assert len(packet["matches"][0]["senses"]) == 3
    signals = analysis_signals_from_scope_evidence(packet)
    assert any(item["signal"] == "INDEX_IDENTITY_CONFLICT" for item in signals["signals"])


def test_review_changes_can_be_batched_without_rebuilding_between_senses(make_workspace, tmp_path: Path) -> None:
    """Verify review-only staleness allows more review while BIC/SAW/export still require rebuild."""
    root = make_workspace(qualification_status="VALIDATED")
    config = load_ecosystem(root / "ecosystem.yml")
    source = tmp_path / "KKH-Luke.xlsx"
    _rwc_workbook(source)
    import_rwc_seed_xlsx(config, source, source_id="KKH-Luke-RWC", language="KKH", headword_column="idKKHv0 Text")
    build_semantic_indexes(config, language="KKH")

    sense_doc = json.loads(
        (storage_layout(root).indexes_root / "semantic" / "languages" / "KKH" / "indexes" / "sense-semdom.json").read_text(encoding="utf-8")
    )
    sense_ids = sorted(sense_doc["senses"])
    assert len(sense_ids) == 2

    set_review_state(config, language="KKH", sense_id=sense_ids[0], status="TEAM_CONFIRMED", reviewer="LC")
    assert semantic_status(config, language="KKH")["index_state"] == "STALE"

    from sage.semantic.evidence import evidence_for_form
    lookup = evidence_for_form(config, language="KKH", form="luma")
    assert lookup["review_index_state"] == "REVIEW_PENDING"
    assert lookup["review_changes_pending"] is True

    # A second reviewed state is accepted against the same unchanged import/authority structure.
    set_review_state(config, language="KKH", sense_id=sense_ids[1], status="ESTABLISHED", reviewer="LC")
    assert semantic_status(config, language="KKH")["index_state"] == "STALE"

    build_semantic_indexes(config, language="KKH")
    assert semantic_status(config, language="KKH")["index_state"] == "CURRENT"

    # A structural input change is different: review must stop until the index is rebuilt.
    import_rwc_seed_xlsx(config, source, source_id="KKH-Luke-RWC-2", language="KKH", headword_column="idKKHv0 Text")
    from sage.errors import ValidationError
    try:
        set_review_state(config, language="KKH", sense_id=sense_ids[0], status="APPROVED", reviewer="LC")
    except ValidationError as exc:
        assert "structurally STALE" in str(exc)
    else:
        raise AssertionError("Structural semantic-input changes must block review until rebuild")
