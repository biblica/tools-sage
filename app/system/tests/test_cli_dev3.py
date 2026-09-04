"""SAGE planning, generation, and initialization command tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import yaml


def run_cli(package_root: Path, workspace: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the SAGE CLI in an isolated subprocess for this test."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(package_root / "system" / "src")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "sage.cli",
            "--settings",
            str(workspace / "ecosystem.yml"),
            *arguments,
        ],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
        timeout=30,
    )


def test_setup_no_prompt_fails_fast_with_structured_input_required(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify `--no-prompt setup` never enters provider probing or an interactive menu."""
    root = make_workspace(configured=False)
    result = run_cli(package_root, root, "--json", "--no-prompt", "setup")
    assert result.returncode == 2, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "INPUT_REQUIRED"
    assert payload["reason_code"] == "SETUP_INPUT_REQUIRED"
    assert payload["retryable"] is True
    assert payload["suggestions"][0]["value"] == "sage setup"


def test_initialize_compiles_language_contracts(package_root: Path, make_workspace) -> None:
    """Verify that `initialize` compiles language contracts."""
    root = make_workspace(configured=True)
    result = run_cli(package_root, root, "--json", "workspace", "initialize")
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    contracts = payload["workflows"]["bic"]["language_contracts"]
    assert set(contracts) == {"CONTENT_SOURCE", "GENERATED_TARGET"}
    assert all(Path(item["cache"]).exists() for item in contracts.values())


def test_plan_command_measures_and_writes_exact_packets(package_root: Path, make_workspace) -> None:
    """Verify that plan command measures and writes exact packets."""
    root = make_workspace(configured=True, verse_max=3)
    output = root.parent / "localdata" / ".system" / "workflows" / "saw" / "output" / "custom" / "plan.json"
    result = run_cli(
        package_root,
        root,
        "--json",
        "workflow",
        "plan",
        "--workflow",
        "saw",
        "--operation",
        "focused",
        "--scope",
        "MAT 1:2",
        "--write-packets",
        "--output",
        str(output),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["summary"]["primary_atomic_coordinates"] == 1
    assert payload["plan_id"].startswith("SAW-FOCUSED-MAT-1-2-")
    assert len(payload["plan_fingerprint"]) == 64
    unit = payload["units"][0]
    assert unit["context_before"] == ["MAT 1:1"]
    assert unit["context_after"] == ["MAT 1:3"]
    assert len(unit["packet_sha256"]) == 64
    assert Path(unit["packet_path"]).exists()
    assert output.exists()
    packet = json.loads(Path(unit["packet_path"]).read_text(encoding="utf-8"))
    assert packet["shared"]["project_id"] == "usWIP"
    assert "target_generation" not in packet["shared"]


def test_saw_plan_uses_independent_wip_without_bic_generation_pin(package_root: Path, make_workspace) -> None:
    """Verify SAW planning reads its configured WIP and requires no BIC generation state."""
    root = make_workspace(configured=True)
    result = run_cli(
        package_root, root, "--json", "workflow", "plan",
        "--workflow", "saw", "--operation", "rtc", "--scope", "MAT 1"
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["project_id"] == "usWIP"
    assert payload["schema_version"] == "1.4"
    assert payload["rtc_planner"]["boundary_streams"] == ["WIP", "REFERENCE"]
    assert payload["rtc_planner"]["version"] == "SAGE_RTC_SFM_ROUTE_PLANNER_V5"
    assert payload["rtc_planner"]["reference_correlation"] == "CANONICAL_PROJECT_VRS"
    assert payload["reference_project_id"] == "usNIVv2"
    assert payload["shared_hashes"]["reference_resource_sha256"]
    package = payload["units"][0]["rtc_package"]
    assert package["route"]["estimated_tokens"] == (
        package["wip"]["estimated_tokens"] + package["ref"]["estimated_tokens"]
    )
    assert package["sizing_basis"] == "ROUTED_SFM_ONLY"
    assert package["projection"] == "SAGE_RTC_SFM_ROUTE_PLANNER_V5"
    assert package["alignment"]["canonical_atoms"]
    assert package["wip"]["estimated_tokens"] < 8000
    assert package["route"]["estimated_tokens"] <= 32000


def test_rtc_plan_correlates_projects_through_their_effective_vrs(
    package_root: Path,
    make_workspace,
) -> None:
    """CLI planning must route a WIP-local label to the matching Reference-local label."""
    root = make_workspace(configured=True, verse_max=3)
    projects_root = root.parent / "localdata/work/projects"
    (projects_root / "usWIP" / "custom.vrs").write_text(
        "MAT 1:3 = MAT 1:2\n",
        encoding="utf-8",
    )
    settings = root / "ecosystem.yml"
    settings_data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    settings_data["projects"]["usWIP"]["versification"]["custom_file"] = "custom.vrs"
    settings.write_text(yaml.safe_dump(settings_data, sort_keys=False), encoding="utf-8")

    result = run_cli(
        package_root,
        root,
        "--json",
        "workflow",
        "plan",
        "--workflow",
        "rtc",
        "--operation",
        "rtc",
        "--scope",
        "MAT 1:3",
    )

    assert result.returncode == 0, result.stderr + result.stdout
    package = json.loads(result.stdout)["units"][0]["rtc_package"]
    assert package["source_spans"]["WIP"] == ["MAT 1:3"]
    assert package["source_spans"]["REFERENCE"] == ["MAT 1:2"]
    assert package["alignment"] == {
        "primary_local_atoms": ["MAT 1:3"],
        "canonical_atoms": ["MAT 1:2"],
        "reference_local_spans": ["MAT 1:2"],
        "missing_canonical_atoms": [],
    }


def test_canonical_rtc_plan_uses_the_rtc_profile(package_root: Path, make_workspace) -> None:
    """New RTC planning persists canonical workflow identity and package sizing."""
    root = make_workspace(configured=True)
    result = run_cli(
        package_root, root, "--json", "workflow", "plan",
        "--workflow", "rtc", "--operation", "rtc", "--scope", "MAT 1",
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["workflow_id"] == "rtc"
    assert payload["plan_id"].startswith("RTC-RTC-")
    assert payload["units"][0]["rtc_package"]["sizing_basis"] == "ROUTED_SFM_ONLY"


def test_rtc_plan_does_not_treat_vrs_ranges_as_source_bridges(
    package_root: Path,
    make_workspace,
) -> None:
    """A coordinate VRS range must not merge an otherwise sliceable RTC book."""
    root = make_workspace(configured=True, verse_max=20)
    base_vrs = root / "system/resources/scripture/eng.vrs"
    base_vrs.write_text(
        "MAT 1:20\nMAT 1:1-20 = MAT 1:1-20\n",
        encoding="utf-8",
    )
    long_verses = ["\\id MAT Fixture", "\\c 1", "\\p"]
    for verse in range(1, 21):
        long_verses.append(f"\\v {verse} " + ("word " * 600))
    scripture = "\n".join(long_verses) + "\n"
    projects = root.parent / "localdata/work/projects"
    for project_id in ("usWIP", "usNIVv2"):
        (projects / project_id / "41MAT.SFM").write_text(scripture, encoding="utf-8")

    result = run_cli(
        package_root,
        root,
        "--json",
        "workflow",
        "plan",
        "--workflow",
        "saw",
        "--operation",
        "rtc",
        "--scope",
        "MAT 1",
    )

    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert len(payload["units"]) > 1
    assert all(
        unit["rtc_package"]["wip"]["estimated_tokens"] < 8000
        for unit in payload["units"]
    )


def test_stc_plan_measures_wip_and_primary_source_as_one_route(
    package_root: Path,
    make_workspace,
) -> None:
    """STC preview uses the same WIP-plus-primary-OL route as STC execution."""
    root = make_workspace(configured=True, verse_max=3)

    result = run_cli(
        package_root, root, "--json", "workflow", "plan",
        "--workflow", "saw", "--operation", "stc", "--scope", "MAT 1"
    )

    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["primary_ol_project_id"] == "GRK"
    assert payload["authority_family"] == "GRK"
    assert payload["analysis_route"] == "STC_CORRESPONDENCE"
    assert payload["stc_planner_version"] == "SAGE_STC_SFM_ROUTE_PLANNER_V2"
    assert payload["authority_correlation"] == "CANONICAL_PROJECT_VRS"
    assert payload["sizing_basis"] == "WIP_PLUS_PRIMARY_OL_ROUTED_SFM"
    assert payload["shared_hashes"]["primary_ol_resource_sha256"]
    package = payload["units"][0]["stc_package"]
    assert package["route"]["estimated_tokens"] == (
        package["wip"]["estimated_tokens"] + package["ol"]["estimated_tokens"]
    )
    assert package["projection"] == "SAGE_STC_SFM_ROUTE_PLANNER_V2"
    assert package["alignment"]["authority_stream"] == "GRK:PRIMARY"


def test_stc_plan_correlates_wip_and_ol_through_their_effective_vrs(
    package_root: Path,
    make_workspace,
) -> None:
    """STC CLI planning must route a WIP-local label to its canonical OL evidence."""
    root = make_workspace(configured=True, verse_max=3)
    projects_root = root.parent / "localdata/work/projects"
    (projects_root / "usWIP" / "custom.vrs").write_text(
        "MAT 1:3 = MAT 1:2\n",
        encoding="utf-8",
    )
    settings = root / "ecosystem.yml"
    settings_data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    settings_data["projects"]["usWIP"]["versification"]["custom_file"] = "custom.vrs"
    settings.write_text(yaml.safe_dump(settings_data, sort_keys=False), encoding="utf-8")

    result = run_cli(
        package_root,
        root,
        "--json",
        "workflow",
        "plan",
        "--workflow",
        "stc",
        "--operation",
        "stc",
        "--scope",
        "MAT 1:3",
    )

    assert result.returncode == 0, result.stderr + result.stdout
    package = json.loads(result.stdout)["units"][0]["stc_package"]
    assert package["source_spans"] == {
        "WIP": ["MAT 1:3"],
        "GRK:PRIMARY": ["MAT 1:2"],
    }
    assert package["source_text_issues"] == []
    assert package["alignment"]["canonical_atoms"] == ["MAT 1:2"]


def test_canonical_stc_plan_uses_the_stc_profile(package_root: Path, make_workspace) -> None:
    """New STC planning persists canonical workflow identity without Reference."""
    root = make_workspace(configured=True)
    result = run_cli(
        package_root, root, "--json", "workflow", "plan",
        "--workflow", "stc", "--operation", "stc", "--scope", "MAT 1",
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["workflow_id"] == "stc"
    assert payload["plan_id"].startswith("STC-STC-")
    assert payload["primary_ol_project_id"] == "GRK"


def test_stc_submit_uses_primary_ol_project_for_operational_logging(
    make_workspace,
    monkeypatch,
    capsys,
) -> None:
    """STC has no contemporary source, so submission logging must bind its primary OL Project."""
    import sage.cli as cli
    from sage.registry import load_ecosystem

    root = make_workspace(configured=True)
    config = load_ecosystem(root / "ecosystem.yml")
    manifest = root / "stc-task-manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(cli, "_load", lambda _args: (config, None))
    monkeypatch.setattr(
        cli,
        "submit_act_task",
        lambda _config, _path: {
            "task_id": "STC-TASK",
            "status": "FINALIZED",
            "operation": "stc",
            "output_project": "usWIP",
            "contemporary_source": None,
            "original_language_sources": [{"project": "GRK", "authority_role": "PRIMARY"}],
        },
    )

    code = cli.command_act_submit(
        Namespace(
            settings=str(root / "ecosystem.yml"),
            task=str(manifest),
            json=True,
            debug=False,
            verbose=False,
            quiet=False,
        )
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "FINALIZED"


def test_chapter_plan_ignores_defects_in_other_chapters(package_root: Path, make_workspace) -> None:
    """Evidence planning blocks only defects intersecting the requested chapter."""
    root = make_workspace(configured=True, verse_max=3)
    path = root.parent / "localdata" / "work" / "projects" / "usWIP" / "41MAT.SFM"
    path.write_text(
        path.read_text(encoding="utf-8") + "\\c 2\n\\p\n\\v 1 Out-of-VRS fixture.\n",
        encoding="utf-8",
    )

    result = run_cli(
        package_root,
        root,
        "--json",
        "workflow",
        "plan",
        "--workflow",
        "saw",
        "--operation",
        "rtc",
        "--scope",
        "MAT 1",
    )

    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["operator_scope"] == "MAT 1"
    assert payload["summary"]["primary_atomic_coordinates"] == 3


def test_rtc_plan_keeps_discontinuous_scope_portions_separate(
    package_root: Path,
    make_workspace,
) -> None:
    """One RTC Run may select separated chapters without widening across the gap."""
    root = make_workspace(configured=True, verse_max=1)
    data_root = root.parent / "localdata" / "work" / "projects"
    for project_id in ("usWIP", "usNIVv2"):
        path = data_root / project_id / "41MAT.SFM"
        path.write_text(
            path.read_text(encoding="utf-8") + "\\c 3\n\\p\n\\v 1 Chapter three.\n",
            encoding="utf-8",
        )
    for name in ("eng.vrs", "org.vrs"):
        (root / "system" / "resources" / "scripture" / name).write_text(
            "MAT 1:1 3:1\n",
            encoding="utf-8",
        )

    result = run_cli(
        package_root,
        root,
        "--json",
        "workflow",
        "plan",
        "--workflow",
        "saw",
        "--operation",
        "rtc",
        "--scope",
        "MAT 1; 3",
    )

    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["operator_scope"] == "MAT 1; MAT 3"
    assert payload["summary"]["primary_atomic_coordinates"] == 2
    assert [unit["primary_scope"] for unit in payload["units"]] == [
        "MAT 1:1",
        "MAT 3:1",
    ]


def test_scoped_saw_plan_preserves_wip_resource_identity(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify that scoped SAW planning preserves the independent WIP resource identity."""
    root = make_workspace(configured=True, verse_max=1)
    target = root.parent / "localdata" / "work" / "projects" / "usWIP"
    (target / "42MRK.SFM").write_text(
        "\\id MRK Fixture\n\\c 1\n\\p\n\\v 1 Mark verse.\n",
        encoding="utf-8",
    )
    eng = root / "system" / "resources" / "scripture" / "eng.vrs"
    eng.write_text(eng.read_text(encoding="utf-8") + "MRK 1:1\n", encoding="utf-8")
    org = root / "system" / "resources" / "scripture" / "org.vrs"
    org.write_text(org.read_text(encoding="utf-8") + "MRK 1:1\n", encoding="utf-8")

    result = run_cli(
        package_root,
        root,
        "--json",
        "workflow",
        "plan",
        "--workflow",
        "saw",
        "--operation",
        "rtc",
        "--scope",
        "MAT 1:1",
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["summary"]["primary_atomic_coordinates"] == 1
    assert payload["shared_hashes"]["resource_sha256"]
    assert payload["shared_hashes"]["compiled_files_sha256"]
    assert (
        payload["shared_hashes"]["resource_sha256"]
        != payload["shared_hashes"]["compiled_files_sha256"]
    )


def test_scope_limited_saw_plan_preserves_multibook_wip_identity(
    package_root: Path,
    make_workspace,
) -> None:
    """Planning one book must retain the full independent WIP resource identity."""
    root = make_workspace(configured=True, verse_max=3)
    for name in ("eng.vrs", "org.vrs"):
        path = root / "system" / "resources" / "scripture" / name
        path.write_text(
            path.read_text(encoding="utf-8") + "MRK 1:2\n",
            encoding="utf-8",
        )
    for project in ("idKKHv0", "usNIRVv2", "usBOLx1", "usWIP", "usNIVv2", "GRK", "HEB"):
        (root.parent / "localdata" / "work" / "projects" / project / "42MRK.SFM").write_text(
            "\\id MRK Fixture\n\\c 1\n\\p\n"
            "\\v 1 Mark verse 1.\n\\v 2 Mark verse 2.\n",
            encoding="utf-8",
        )

    result = run_cli(
        package_root,
        root,
        "--json",
        "workflow",
        "plan",
        "--workflow",
        "saw",
        "--operation",
        "rtc",
        "--scope",
        "MAT 1",
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["summary"]["primary_atomic_coordinates"] == 3
    assert payload["shared_hashes"]["resource_sha256"]
    assert payload["shared_hashes"]["compiled_files_sha256"]
    assert (
        payload["shared_hashes"]["resource_sha256"]
        != payload["shared_hashes"]["compiled_files_sha256"]
    )


def test_plan_id_changes_when_structure_policy_changes(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify that plan ID changes when structure policy changes."""
    root = make_workspace(configured=True, verse_max=3)
    first = run_cli(
        package_root,
        root,
        "--json",
        "workflow",
        "plan",
        "--workflow",
        "bic",
        "--operation",
        "inspect",
        "--scope",
        "MAT 1",
    )
    assert first.returncode == 0, first.stderr + first.stdout
    first_id = json.loads(first.stdout)["plan_id"]
    policy = root / "system" / "config" / "structure-planning.yml"
    content = policy.read_text(encoding="utf-8").replace("s2: 60", "s2: 61")
    policy.write_text(content, encoding="utf-8")
    second = run_cli(
        package_root,
        root,
        "--json",
        "workflow",
        "plan",
        "--workflow",
        "bic",
        "--operation",
        "inspect",
        "--scope",
        "MAT 1",
    )
    assert second.returncode == 0, second.stderr + second.stdout
    second_id = json.loads(second.stdout)["plan_id"]
    assert second_id != first_id



def test_generation_publish_requires_explicit_development_override(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify that generation publish requires explicit development override."""
    root = make_workspace(configured=True, qualification_status="IN_PROGRESS")
    blocked = run_cli(package_root, root, "generation", "publish")
    assert blocked.returncode == 2
    assert "--development-override" in blocked.stderr
    allowed = run_cli(
        package_root,
        root,
        "--json",
        "generation",
        "publish",
        "--development-override",
    )
    assert allowed.returncode == 0, allowed.stderr + allowed.stdout
    payload = json.loads(allowed.stdout)
    assert payload["publication_basis"] == "DEVELOPMENT_OVERRIDE"


def test_validated_bic_profile_publishes_without_override(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify that validated BIC profile publishes without override."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    result = run_cli(package_root, root, "--json", "generation", "publish")
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["publication_basis"] == "VALIDATED_WORKFLOW"


def test_plan_output_must_remain_inside_workflow_output_root(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify that plan output must remain inside workflow output root."""
    root = make_workspace(configured=True)
    outside = root / "outside-plan.json"
    result = run_cli(
        package_root,
        root,
        "workflow",
        "plan",
        "--workflow",
        "bic",
        "--operation",
        "inspect",
        "--scope",
        "MAT 1",
        "--output",
        str(outside),
    )
    assert result.returncode == 2
    assert "workflow output" in result.stderr
    assert not outside.exists()


def test_plan_write_is_guarded_by_a_workflow_lock(
    package_root: Path,
    make_workspace,
) -> None:
    """An identical concurrent plan must not replace derived files mid-write."""
    root = make_workspace(configured=True, verse_max=3)
    first = run_cli(
        package_root,
        root,
        "--json",
        "workflow",
        "plan",
        "--workflow",
        "bic",
        "--operation",
        "inspect",
        "--scope",
        "MAT 1",
    )
    assert first.returncode == 0, first.stderr + first.stdout
    plan_id = json.loads(first.stdout)["plan_id"]
    lock = root.parent / "localdata" / ".system" / "workflows" / "bic" / "locks" / f"plan-{plan_id}.lock"
    lock.mkdir(parents=True)
    (lock / "owner.json").write_text(
        json.dumps(
            {
                "pid": 999999999,
                "host": "other-host",
                "operation": "BIC_INSPECT_PLAN_WRITE",
                "acquired_utc": "2026-08-02T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    second = run_cli(
        package_root,
        root,
        "workflow",
        "plan",
        "--workflow",
        "bic",
        "--operation",
        "inspect",
        "--scope",
        "MAT 1",
    )
    assert second.returncode == 2
    assert "Workspace is locked" in second.stderr



def test_generation_pin_command_is_absent(package_root: Path, make_workspace) -> None:
    """Verify the removed BIC-to-SAW generation pin command cannot be invoked."""
    root = make_workspace(configured=True)
    blocked = run_cli(package_root, root, "generation", "pin")
    assert blocked.returncode == 2
    assert "Invalid value for generation_command" in blocked.stderr


def test_bic_plan_cannot_write_inside_publication_root(
    package_root: Path,
    make_workspace,
) -> None:
    """Verify that BIC plan cannot write inside publication root."""
    root = make_workspace(configured=True)
    publication_path = (
        root.parent
        / "localdata"
        / ".system"
        / "workflows"
        / "bic"
        / "output"
        / "published-targets"
        / "bad-plan.json"
    )
    result = run_cli(
        package_root,
        root,
        "workflow",
        "plan",
        "--workflow",
        "bic",
        "--operation",
        "inspect",
        "--scope",
        "MAT 1",
        "--output",
        str(publication_path),
    )
    assert result.returncode == 2
    assert "immutable publication root" in result.stderr
    assert not publication_path.exists()
