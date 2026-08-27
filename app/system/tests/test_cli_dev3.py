"""SAGE planning, generation, and initialization command tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


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
    assert payload["schema_version"] == "1.3"
    assert payload["reference_project_id"] == "usNIVv2"
    assert payload["shared_hashes"]["reference_resource_sha256"]
    package = payload["units"][0]["rtc_package"]
    assert package["pack"]["estimated_tokens"] == sum(
        package[name]["estimated_tokens"] for name in ("wip", "ref", "oh")
    )
    assert package["wip"]["estimated_tokens"] < 8000
    assert package["pack"]["estimated_tokens"] <= 32000


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
