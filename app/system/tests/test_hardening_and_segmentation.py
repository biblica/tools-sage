"""Bounded TARGET safety, discourse segmentation, and handoff invariants."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from sage.storage import storage_layout
from sage.act_tasks import create_act_task
from sage.bounded_target import (
    extract_scope_usfm,
    list_target_history,
    merge_bounded_usfm,
    record_target_commit,
    revert_target_scope,
)
from sage.evidence import EvidencePolicy
from sage.evidence_policy import AUTHORIZED_CONTENT_EVIDENCE, PROCESS_CONTROL
from sage.errors import ValidationError
from sage.llm_tasks import _conditional_requests, _micro_scope_reads
from sage.registry import load_ecosystem
from sage.sections import index_usfm_structure
from sage.usj import compile_usfm_text
from sage.work_units import EvidenceRecord, plan_work_units



def _initialize_fixture(package_root: Path, root: Path) -> None:
    """Initialize one isolated current fixture through the public controller."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "system" / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sage.cli",
            "--settings",
            str(root / "ecosystem.yml"),
            "workspace",
            "initialize",
        ],
        text=True,
        capture_output=True,
        env=env,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr + result.stdout

def test_missing_end_of_chapter_verse_is_inserted_before_next_chapter(tmp_path: Path) -> None:
    """A bounded insertion must never drift beneath the following chapter marker."""
    before = "\\id MAT Target\n\\c 1\n\\v 1 ONE\n\\c 2\n\\v 1 TWO-ONE\n"
    candidate = "\\id MAT Candidate\n\\c 1\n\\v 2 INSERTED\n"
    after = merge_bounded_usfm(before, candidate, "MAT 1:2")
    assert after.index("\\v 2 INSERTED") < after.index("\\c 2")
    assert extract_scope_usfm(after, "MAT 1:2") == "\\c 1\n\\v 2 INSERTED\n"

    target = tmp_path / "41MAT.SFM"
    target.write_text(after, encoding="utf-8")
    project_root = tmp_path / "job"
    tx_root = tmp_path / "transactions"
    record_target_commit(
        job_root=project_root,
        target_file=target,
        scope_value="MAT 1:2",
        before_text=before,
        after_text=after,
        transaction_id="ZZZZZZZZZZZZ-first",
        task_id="TASK-1",
        run_id="RUN-1",
        created_utc="2026-08-10T20:00:00Z",
    )
    result = revert_target_scope(
        job_root=project_root,
        target_file=target,
        scope_value="MAT 1:2",
        transaction_root=tx_root,
        allowed_roots=(tmp_path,),
    )
    assert result["status"] == "REVERTED"
    restored = target.read_text(encoding="utf-8")
    assert "\\v 2 INSERTED" not in restored
    assert restored == before


def test_target_history_same_second_uses_monotonic_ordering(tmp_path: Path, monkeypatch) -> None:
    """Same-second commits must be ordered by commit time, never transaction-id text."""
    import sage.bounded_target as bounded_target

    times = iter((100, 200))
    monkeypatch.setattr(bounded_target.time, "time_ns", lambda: next(times))
    before = "\\id MAT T\n\\c 1\n\\v 1 A\n"
    middle = "\\id MAT T\n\\c 1\n\\v 1 B\n"
    after = "\\id MAT T\n\\c 1\n\\v 1 C\n"
    target = tmp_path / "41MAT.SFM"
    created = "2026-08-10T20:00:00Z"
    first = record_target_commit(
        job_root=tmp_path / "project",
        target_file=target,
        scope_value="MAT 1:1",
        before_text=before,
        after_text=middle,
        transaction_id="ZZZZZZZZZZZZ-first",
        task_id="TASK-1",
        run_id="S",
        created_utc=created,
    )
    second = record_target_commit(
        job_root=tmp_path / "project",
        target_file=target,
        scope_value="MAT 1:1",
        before_text=middle,
        after_text=after,
        transaction_id="AAAAAAAAAAAA-second",
        task_id="TASK-2",
        run_id="S",
        created_utc=created,
    )
    rows = list_target_history(tmp_path / "project", scope_value="MAT 1:1")
    assert rows[0]["commit_id"] == second["commit_id"]
    assert rows[1]["commit_id"] == first["commit_id"]


def test_poetry_stanza_is_maximal_uninterrupted_poetry_run() -> None:
    """q/qm/qr/qc indentation changes remain one unit until an explicit structural breaker."""
    text = (
        "\\id PSA Fixture\n"
        "\\c 1\n"
        "\\cl Psalm 1\n"
        "\\d Superscription\n"
        "\\q1\n\\v 1 One.\n"
        "\\q2\n\\v 2 Two.\n"
        "\\qm1\n\\v 3 Three.\n"
        "\\qr\n\\v 4 Refrain.\n"
        "\\qc\n\\v 5 Centered.\n"
        "\\b\n"
        "\\q1\n\\v 6 New stanza.\n"
        "\\qa Aleph\n"
        "\\q1\n\\v 7 Acrostic unit.\n"
        "\\s1 New section\n"
        "\\q1\n\\v 8 Section poetry.\n"
    )
    rows = index_usfm_structure(text, "PSA")
    first_ids = {row["discourse_unit_id"] for row in rows[:5]}
    assert len(first_ids) == 1
    assert all(row["discourse_unit_kind"] == "POETRY_STANZA" for row in rows[:5])
    assert rows[5]["discourse_unit_id"] != rows[4]["discourse_unit_id"]
    assert rows[6]["discourse_unit_id"] != rows[5]["discourse_unit_id"]
    assert rows[7]["discourse_unit_id"] != rows[6]["discourse_unit_id"]


def test_list_li1_starts_major_unit_and_li2_children_stay_with_it() -> None:
    """lh/lf break list flow while each li1 owns its following subordinate list paragraphs."""
    text = (
        "\\id MAT Fixture\n\\c 1\n"
        "\\lh Header\n"
        "\\li1\n\\v 1 Major A\n"
        "\\li2\n\\v 2 Detail A\n"
        "\\li1\n\\v 3 Major B\n"
        "\\li2\n\\v 4 Detail B\n"
        "\\lf Footer\n"
        "\\p\n\\v 5 Prose\n"
    )
    rows = index_usfm_structure(text, "MAT")
    assert rows[0]["discourse_unit_kind"] == "LIST_MAJOR"
    assert rows[0]["discourse_unit_id"] == rows[1]["discourse_unit_id"]
    assert rows[2]["discourse_unit_kind"] == "LIST_MAJOR"
    assert rows[2]["discourse_unit_id"] == rows[3]["discourse_unit_id"]
    assert rows[2]["discourse_unit_id"] != rows[0]["discourse_unit_id"]
    assert rows[4]["discourse_unit_kind"] == "PROSE_PARAGRAPH"
    assert rows[4]["discourse_unit_id"] != rows[3]["discourse_unit_id"]


def test_planner_honours_an_explicit_primary_discourse_ceiling() -> None:
    """A nonzero specialist policy may still impose a hard discourse-unit ceiling."""
    records = tuple(
        EvidenceRecord(
            book="MAT",
            chapter=1,
            verse_start=verse,
            verse_end=verse,
            payload={"body_text": f"Verse {verse}"},
            discourse_unit_id="MAT-D001" if verse <= 2 else "MAT-D002",
            discourse_unit_kind="PROSE_PARAGRAPH",
            discourse_unit_marker="p",
        )
        for verse in range(1, 5)
    )
    policy = EvidencePolicy(
        target_estimated_tokens=10000,
        hard_estimated_tokens=20000,
        hard_serialized_bytes=100000,
        minimum_target_tokens=1,
        maximum_primary_verse_units=20,
        maximum_primary_discourse_units=1,
        context_before_verses=0,
        context_after_verses=0,
    )
    units = plan_work_units(records, policy, unit_prefix="SAW-RTC")
    assert len(units) == 2
    assert [[item.verse_start for item in unit.primary] for unit in units] == [[1, 2], [3, 4]]
    assert all(len(unit.to_dict()["primary_discourse_units"]) == 1 for unit in units)


def test_normal_saw_policy_coalesces_short_discourse_units(package_root: Path) -> None:
    """The shipped RTC policy must not turn every short paragraph into a microtask."""
    profile = yaml.safe_load(
        (package_root / "system" / "config" / "workflows" / "saw" / "profile.yml").read_text(encoding="utf-8")
    )
    policy = EvidencePolicy.from_mapping(profile["evidence_policies"]["rtc"])
    records = tuple(
        EvidenceRecord(
            book="MAT",
            chapter=1,
            verse_start=verse,
            verse_end=verse,
            payload={"body_text": f"Short paragraph {verse}."},
            discourse_unit_id=f"MAT-D{verse:03d}",
            discourse_unit_kind="PROSE_PARAGRAPH",
            discourse_unit_marker="p",
        )
        for verse in range(1, 9)
    )

    units = plan_work_units(records, policy, unit_prefix="SAW-RTC")

    assert policy.maximum_primary_discourse_units == 0
    assert policy.preferred_primary_discourse_units == 4
    assert policy.context_before_verses == policy.context_after_verses == 1
    assert len(units) == 1
    assert len(units[0].to_dict()["primary_discourse_units"]) == 8
    assert units[0].to_dict()["primary_scope"] == "MAT 1:1-8"




def test_shipped_focus_batch_caps_sharpen_model_work_without_splitting_discourse(package_root: Path) -> None:
    """Ship conservative discourse-unit caps for RTC/focused/OL and BIC INSPECT focus."""
    saw = yaml.safe_load(
        (package_root / "system" / "config" / "workflows" / "saw" / "profile.yml").read_text(encoding="utf-8")
    )
    bic = yaml.safe_load(
        (package_root / "system" / "config" / "workflows" / "bic" / "profile.yml").read_text(encoding="utf-8")
    )
    assert saw["evidence_policies"]["rtc"]["maximum_primary_discourse_units"] == 0
    assert saw["evidence_policies"]["rtc"]["preferred_primary_discourse_units"] == 4
    assert saw["evidence_policies"]["focused"]["maximum_primary_discourse_units"] == 2
    assert saw["evidence_policies"]["ol"]["maximum_primary_discourse_units"] == 1
    assert bic["evidence_policies"]["inspect"]["maximum_primary_discourse_units"] == 4


def test_explicit_discourse_partition_routes_real_context_packets(package_root: Path, make_workspace) -> None:
    """A partitioned SAW child receives labelled adjacent WIP and REFERENCE context."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=4)
    text = (
        "\\id MAT Fixture\n\\c 1\n"
        "\\p\n\\v 1 First paragraph one.\n\\v 2 First paragraph two.\n"
        "\\p\n\\v 3 Second paragraph one.\n\\v 4 Second paragraph two.\n"
    )
    for project_id in ("usWIP", "usNIVv2"):
        (storage_layout(root).projects_root / project_id / "41MAT.SFM").write_text(text, encoding="utf-8")
    profile_path = root / "system" / "config" / "workflows" / "saw" / "profile.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["evidence_policies"]["rtc"] = dict(profile["evidence_policies"]["default"])
    profile["evidence_policies"]["rtc"]["maximum_primary_discourse_units"] = 1
    profile["evidence_policies"]["rtc"]["context_before_verses"] = 1
    profile["evidence_policies"]["rtc"]["context_after_verses"] = 1
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    _initialize_fixture(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    result = create_act_task(
        config,
        workflow="saw",
        operation="rtc",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1-4",
        rtc_stage="REFERENCE_TEXT_COMPARISON",
    )
    assert result["status"] == "PARTITIONED"
    assert [row["scope"] for row in result["work_units"]] == ["MAT 1:1-2", "MAT 1:3-4"]
    manifests = []
    for row in result["work_units"]:
        manifest = __import__("json").loads(Path(row["manifest_path"]).read_text(encoding="utf-8"))
        manifests.append(manifest)
        assert manifest["rtc_stage"] == "REFERENCE_TEXT_COMPARISON"
        assert manifest["context_budget"]["policy"]["maximum_primary_discourse_units"] == 1
        assert manifest["packets"]["context_contemporary_source"]["context_mode"] == "CONTEXT_ONLY"
        assert manifest["packets"]["context_output_project"]["context_mode"] == "CONTEXT_ONLY"
        assert "REFERENCE_CONTEXT" in manifest["allowed_evidence_ids"]
        assert "WIP_CONTEXT" in manifest["allowed_evidence_ids"]
    assert manifests[0]["context_references"] == {
        "mode": "CONTEXT_ONLY",
        "before": [],
        "after": ["MAT 1:3"],
    }
    assert manifests[1]["context_references"] == {
        "mode": "CONTEXT_ONLY",
        "before": ["MAT 1:2"],
        "after": [],
    }
    assert manifests[0]["expected_references"] == ["MAT 1:1", "MAT 1:2"]
    assert manifests[1]["expected_references"] == ["MAT 1:3", "MAT 1:4"]

def test_bic_conditional_ol_is_one_question_and_one_raw_scripture_verse() -> None:
    """Conditional BIC OL transport must not leak neighbouring SOURCE/OL Scripture."""
    challenges = {
        "challenges": [
            {
                "challenge_id": "CH-V1",
                "scripture_reference": "MAT 1:2",
                "category": "VERB_CHOICE",
                "summary": "Resolve the disputed verb",
                "risk": {"before_ol": 2, "material_triggers": ["semantic ambiguity"]},
                "ol_referral": {"performed": False},
            }
        ]
    }
    requests = _conditional_requests({"output/translation-challenges.json": __import__("json").dumps(challenges)})
    assert len(requests) == 1
    assert requests[0]["scripture_reference"] == "MAT 1:2"
    assert "verbal sense/function" in requests[0]["question"]

    source = json.dumps(
        compile_usfm_text("\\id MAT Source\n\\c 1\n\\v 1 FIRST\n\\v 2 SECOND\n\\v 3 THIRD\n"),
        ensure_ascii=False,
    )
    ol = json.dumps(
        compile_usfm_text("\\id MAT Greek\n\\c 1\n\\v 1 G1\n\\v 2 G2\n\\v 3 G3\n"),
        ensure_ascii=False,
    )
    focused = {
        path: content
        for path, content, _ in _micro_scope_reads(
            [
                ("workspace_data/task/packet/source.usj.json", source, AUTHORIZED_CONTENT_EVIDENCE),
                ("system/config/rules.yml", "rules", PROCESS_CONTROL),
            ],
            [
                (
                    "workspace_data/task/packet/original-language.usj.json",
                    ol,
                    AUTHORIZED_CONTENT_EVIDENCE,
                )
            ],
            "MAT 1:2",
        )
    }
    assert "SECOND" in focused["workspace_data/task/packet/source.usj.json"]
    assert "FIRST" not in focused["workspace_data/task/packet/source.usj.json"]
    assert "THIRD" not in focused["workspace_data/task/packet/source.usj.json"]
    assert "G2" in focused["workspace_data/task/packet/original-language.usj.json"]
    assert "G1" not in focused["workspace_data/task/packet/original-language.usj.json"]
    assert "G3" not in focused["workspace_data/task/packet/original-language.usj.json"]
    assert "system/config/rules.yml" not in focused


def test_bic_conditional_ol_rejects_multi_verse_challenge() -> None:
    """Controller-derived OL clarification cannot silently broaden a challenge to multiple verses."""
    raw = __import__("json").dumps(
        {
            "challenges": [
                {
                    "challenge_id": "CH-RANGE",
                    "scripture_reference": "MAT 1:1-2",
                    "category": "VERB_CHOICE",
                    "risk": {"before_ol": 2, "material_triggers": ["ambiguity"]},
                    "ol_referral": {"performed": False},
                }
            ]
        }
    )
    import pytest

    with pytest.raises(ValidationError, match="single verse"):
        _conditional_requests({"output/translation-challenges.json": raw})

def test_hardening_schedules_every_test_module(package_root: Path) -> None:
    """The documented hardening gate must automatically include every test_*.py module."""
    scripts = str(package_root / "system" / "tools")
    sys.path.insert(0, scripts)
    try:
        hardening = importlib.import_module("hardening")
        batches, discovered, errors = hardening._scheduled_test_batches(package_root)
    finally:
        sys.path.remove(scripts)
        sys.modules.pop("hardening", None)
    scheduled = [path for batch in batches for path in batch[1:]]
    assert errors == []
    assert sorted(scheduled) == sorted(discovered)


def test_hardening_shards_cover_every_module_exactly_once(package_root: Path) -> None:
    """Sorted modulo sharding must cover the discovered module inventory once with no overlap."""
    scripts = str(package_root / "system" / "tools")
    sys.path.insert(0, scripts)
    try:
        hardening = importlib.import_module("hardening")
        all_scheduled: list[str] = []
        discovered_reference: list[str] | None = None
        for shard_index in range(4):
            batches, discovered, errors = hardening._scheduled_test_batches(
                package_root, shard_count=4, shard_index=shard_index
            )
            assert errors == []
            if discovered_reference is None:
                discovered_reference = discovered
            else:
                assert discovered == discovered_reference
            scheduled = [path for batch in batches for path in batch[1:]]
            assert scheduled == [
                path for position, path in enumerate(discovered) if position % 4 == shard_index
            ]
            all_scheduled.extend(scheduled)
        assert discovered_reference is not None
        assert sorted(all_scheduled) == sorted(discovered_reference)
        assert len(all_scheduled) == len(set(all_scheduled))
    finally:
        sys.path.remove(scripts)
        sys.modules.pop("hardening", None)


def test_formal_hardening_combine_requires_complete_exact_hash_shards(package_root: Path, tmp_path: Path) -> None:
    """The combine gate accepts only complete PASS shards bound to the current governed source hash."""
    scripts = str(package_root / "system" / "tools")
    sys.path.insert(0, scripts)
    try:
        hardening = importlib.import_module("hardening")
        _batches, discovered, errors = hardening._scheduled_test_batches(package_root)
        assert errors == []
        source_hash = hardening._source_tree_sha256(package_root)
        receipt_paths: list[Path] = []
        for shard_index in range(3):
            scheduled = [
                path for position, path in enumerate(discovered) if position % 3 == shard_index
            ]
            receipt = {
                "schema_version": hardening.RECEIPT_SCHEMA_VERSION,
                "status": "PASS",
                "source_tree_sha256": source_hash,
                "governed_source_unchanged": True,
                "shard_count": 3,
                "shard_index": shard_index,
                "discovered_tests": discovered,
                "scheduled_tests": scheduled,
                "test_cases_discovered": 0,
                "tests_passed": 0,
                "tests_failed": 0,
                "tests_skipped": 0,
                "errors": [],
                "warnings": [],
                "steps": [
                    {"name": "post_schema_validation", "returncode": 0},
                    {"name": "post_package_validation", "returncode": 0},
                    {"name": "post_deep_audit", "returncode": 0},
                ],
            }
            path = tmp_path / f"shard-{shard_index}.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            receipt_paths.append(path)
        combined = hardening.combine_reports(receipt_paths, expected_source_sha256=source_hash)
        assert combined["status"] == "PASS"
        assert combined["formal_combine"] == "PASS"
        assert combined["test_modules_scheduled_exactly_once"] is True
        assert combined["test_files_discovered"] == len(discovered)
        assert combined["test_files_scheduled"] == len(discovered)
        assert combined["schema_validation"] == "PASS"
        assert combined["package_validation"] == "PASS"
        assert combined["deep_audit"] == "PASS"
        assert combined["errors"] == []
        assert combined["warnings"] == []
    finally:
        sys.path.remove(scripts)
        sys.modules.pop("hardening", None)
