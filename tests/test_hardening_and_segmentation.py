"""Bounded TARGET safety, discourse segmentation, and handoff invariants."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import yaml

from sage_core.act_tasks import create_act_task
from sage_core.bounded_target import (
    extract_scope_usfm,
    list_target_history,
    merge_bounded_usfm,
    record_target_commit,
    revert_target_scope,
)
from sage_core.evidence import EvidencePolicy
from sage_core.errors import ValidationError
from sage_core.llm_tasks import _conditional_requests, _micro_scope_reads
from sage_core.registry import load_ecosystem
from sage_core.sections import index_usfm_structure
from sage_core.work_units import EvidenceRecord, plan_work_units



def _initialize_fixture(package_root: Path, root: Path) -> None:
    """Initialise one isolated current fixture through the public controller."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(package_root / "core")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sage_core.cli",
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
    import sage_core.bounded_target as bounded_target

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
    units = plan_work_units(records, policy, unit_prefix="SAW-QA")
    assert len(units) == 2
    assert [[item.verse_start for item in unit.primary] for unit in units] == [[1, 2], [3, 4]]
    assert all(len(unit.to_dict()["primary_discourse_units"]) == 1 for unit in units)


def test_normal_saw_policy_coalesces_short_discourse_units(package_root: Path) -> None:
    """The shipped QA policy must not turn every short paragraph into a microtask."""
    profile = yaml.safe_load(
        (package_root / "workflows" / "saw" / "profile.yml").read_text(encoding="utf-8")
    )
    policy = EvidencePolicy.from_mapping(profile["evidence_policies"]["qa"])
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

    units = plan_work_units(records, policy, unit_prefix="SAW-QA")

    assert policy.maximum_primary_discourse_units == 0
    assert policy.context_before_verses == policy.context_after_verses == 1
    assert len(units) == 1
    assert len(units[0].to_dict()["primary_discourse_units"]) == 8




def test_explicit_discourse_partition_routes_real_context_packets(package_root: Path, make_workspace) -> None:
    """A partitioned SAW child receives labelled adjacent WIP and REFERENCE context."""
    root = make_workspace(qualification_status="VALIDATED", verse_max=4)
    text = (
        "\\id MAT Fixture\n\\c 1\n"
        "\\p\n\\v 1 First paragraph one.\n\\v 2 First paragraph two.\n"
        "\\p\n\\v 3 Second paragraph one.\n\\v 4 Second paragraph two.\n"
    )
    for project_id in ("usWIP", "usNIVv2"):
        (root / "projects" / project_id / "41MAT.SFM").write_text(text, encoding="utf-8")
    profile_path = root / "workflows" / "saw" / "profile.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["evidence_policies"]["default"]["maximum_primary_discourse_units"] = 1
    profile["evidence_policies"]["default"]["context_before_verses"] = 1
    profile["evidence_policies"]["default"]["context_after_verses"] = 1
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    _initialize_fixture(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    result = create_act_task(
        config,
        workflow="saw",
        operation="qa",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1-4",
        qa_stage="TRANSLATION_AND_MEANING_QA",
    )
    assert result["status"] == "PARTITIONED"
    assert [row["scope"] for row in result["work_units"]] == ["MAT 1:1-2", "MAT 1:3-4"]
    manifests = []
    for row in result["work_units"]:
        manifest = __import__("json").loads(Path(row["manifest_path"]).read_text(encoding="utf-8"))
        manifests.append(manifest)
        assert manifest["qa_stage"] == "TRANSLATION_AND_MEANING_QA"
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

    source = "\\id MAT Source\n\\c 1\n\\v 1 FIRST\n\\v 2 SECOND\n\\v 3 THIRD\n"
    ol = "\\id MAT Greek\n\\c 1\n\\v 1 G1\n\\v 2 G2\n\\v 3 G3\n"
    focused = dict(
        _micro_scope_reads(
            [("workspace-data/task/packet/source.usfm", source), ("meta/rules.yml", "rules")],
            [("workspace-data/task/packet/original-language.usfm", ol)],
            "MAT 1:2",
        )
    )
    assert "SECOND" in focused["workspace-data/task/packet/source.usfm"]
    assert "FIRST" not in focused["workspace-data/task/packet/source.usfm"]
    assert "THIRD" not in focused["workspace-data/task/packet/source.usfm"]
    assert "G2" in focused["workspace-data/task/packet/original-language.usfm"]
    assert "G1" not in focused["workspace-data/task/packet/original-language.usfm"]
    assert "G3" not in focused["workspace-data/task/packet/original-language.usfm"]
    assert focused["meta/rules.yml"] == "rules"


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
    scripts = str(package_root / "scripts")
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
