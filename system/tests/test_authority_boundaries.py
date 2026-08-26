"""BIC/SAW authority-boundary contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from sage.act_tasks import create_act_task
from sage.errors import ValidationError
from sage.registry import load_ecosystem


def _initialize(package_root: Path, root: Path) -> None:
    """Initialize one isolated fixture through the public SAGE CLI."""
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


def test_bic_existing_target_is_destination_only(package_root: Path, make_workspace) -> None:
    """INSPECT/REWRITE must never route pre-existing TARGET Scripture as model evidence."""
    root = make_workspace(qualification_status="VALIDATED")
    target = root.parent / "SAGEdata" / "projects" / "usBOLx1" / "41MAT.SFM"
    target.write_text(
        "\\id MAT\n\\c 1\n\\v 1 FORBIDDEN_TARGET_SENTINEL existing target wording\n",
        encoding="utf-8",
    )
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    task = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1:1",
    )
    task_root = Path(task["manifest_path"]).parent
    packet_root = task_root / "packet"

    assert not (packet_root / "wip.usj.json").exists()
    assert not (packet_root / "target.usj.json").exists()
    source_packet = json.loads((packet_root / "source.usj.json").read_text(encoding="utf-8"))
    assert source_packet["type"] == "USJ"
    assert source_packet["sage"]["source_format"] == "USFM"
    assert source_packet["sage"]["comparison_format"] == "USJ"
    assert "packet.output_project" not in task["resource_fingerprints"]
    assert all("projects/usBOLx1/41MAT.SFM" not in row["path"] for row in task["allowed_reads"])
    for packet in packet_root.rglob("*"):
        if packet.is_file():
            assert "FORBIDDEN_TARGET_SENTINEL" not in packet.read_text(encoding="utf-8", errors="replace")


def test_bic_donor_routes_only_decontextualized_vocabulary(package_root: Path, make_workspace) -> None:
    """DONOR Scripture text must be reduced to an unordered lexical inventory before model routing."""
    root = make_workspace(qualification_status="VALIDATED")
    donor = root.parent / "SAGEdata" / "projects" / "usNIVv2" / "41MAT.SFM"
    donor.write_text(
        "\\id MAT\n\\c 1\n\\v 1 Alpha Beta Gamma Alpha.\n\\v 2 Delta Beta.\n",
        encoding="utf-8",
    )
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    task = create_act_task(
        config,
        workflow="bic",
        operation="inspect",
        output_project_id="usBOLx1",
        contemporary_source_id="idKKHv0",
        scope_value="MAT 1:1-2",
    )
    packet_root = Path(task["manifest_path"]).parent / "packet"
    donor_packet = packet_root / "lexical-donor-vocabulary.json"
    value = json.loads(donor_packet.read_text(encoding="utf-8"))

    assert value["role"] == "LEXICAL_DONOR"
    assert value["authority_rule"].startswith("Vocabulary evidence only.")
    assert value["forms"] == [
        {"form": "alpha", "attested_forms": ["Alpha"]},
        {"form": "beta", "attested_forms": ["Beta"]},
        {"form": "delta", "attested_forms": ["Delta"]},
        {"form": "gamma", "attested_forms": ["Gamma"]},
    ]
    serialized = donor_packet.read_text(encoding="utf-8")
    assert "occurrences_in_scope" not in serialized
    assert "Alpha Beta Gamma" not in serialized
    assert "\\v 1" not in serialized
    assert all("projects/usNIVv2/41MAT.SFM" not in row["path"] for row in task["allowed_reads"])
    assert any(row["path"].endswith("packet/lexical-donor-vocabulary.json") for row in task["allowed_reads"])
    assert not any(path.name == "donor.usfm" for path in packet_root.iterdir())


def test_bic_source_donor_target_must_be_distinct(package_root: Path, make_workspace) -> None:
    """A project cannot acquire two BIC authority roles in one task."""
    root = make_workspace(qualification_status="VALIDATED")
    settings = root / "ecosystem.yml"
    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    data["projects"]["idKKHv0"]["scope"]["roles"].append("LEXICAL_DONOR")
    settings.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    _initialize(package_root, root)
    config = load_ecosystem(settings)

    with pytest.raises(ValidationError, match="three bindings must be distinct"):
        create_act_task(
            config,
            workflow="bic",
            operation="inspect",
            output_project_id="usBOLx1",
            contemporary_source_id="idKKHv0",
            lexical_donor_id="idKKHv0",
            scope_value="MAT 1:1",
        )


def test_saw_packet_names_express_wip_and_reference(package_root: Path, make_workspace) -> None:
    """SAW keeps its two content inputs explicit: WIP under review and authorized REFERENCE."""
    root = make_workspace(qualification_status="VALIDATED")
    _initialize(package_root, root)
    config = load_ecosystem(root / "ecosystem.yml")

    task = create_act_task(
        config,
        workflow="saw",
        operation="qa",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    packet_root = Path(task["manifest_path"]).parent / "packet"

    assert (packet_root / "wip.usj.json").is_file()
    assert (packet_root / "reference.usj.json").is_file()
    for name in ("wip.usj.json", "reference.usj.json"):
        comparison = json.loads((packet_root / name).read_text(encoding="utf-8"))
        assert comparison["type"] == "USJ"
        assert comparison["sage"]["source_format"] == "USFM"
        assert comparison["sage"]["comparison_format"] == "USJ"
    assert task["allowed_evidence_ids"][:2] == ["WIP", "REFERENCE"] or set(task["allowed_evidence_ids"]) >= {"WIP", "REFERENCE"}


def test_external_base_vrs_is_hashed_into_packet_without_becoming_task_path(
    package_root: Path,
    make_workspace,
    tmp_path: Path,
) -> None:
    """A configured external VRS is authorized provenance, not a direct ACT read path."""
    root = make_workspace(qualification_status="VALIDATED")
    external = tmp_path / "Paratext Projects"
    external.mkdir()
    for name in ("eng.vrs", "org.vrs"):
        (external / name).write_text(
            (root / "system" / "resources" / "scripture" / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    settings = root / "ecosystem.yml"
    raw = yaml.safe_load(settings.read_text(encoding="utf-8"))
    raw["paths"]["base_vrs_root"] = str(external)
    settings.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    _initialize(package_root, root)

    task = create_act_task(
        load_ecosystem(settings),
        workflow="saw",
        operation="qa",
        output_project_id="usWIP",
        contemporary_source_id="usNIVv2",
        scope_value="MAT 1:1",
    )
    packet = json.loads(
        (Path(task["manifest_path"]).parent / "packet" / "vrs-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    provenance = packet["resources"]["output_project"]["source_provenance"]
    assert provenance["base_file"] == "@BASE_VRS/eng.vrs"
    assert len(provenance["base_sha256"]) == 64
    assert all(str(external) not in row["path"] for row in task["allowed_reads"])
