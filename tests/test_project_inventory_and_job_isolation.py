"""RC7.04 regressions for role-neutral SAGE Projects, Jobs, and runtime isolation."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sage_core.errors import ValidationError
from sage_core.iso_languages import resolve_paratext_language
from sage_core.jobs import JobStore
from sage_core.menu import MenuIO, SageControlCenter, ScriptedInput
from sage_core.paratext_catalog import inspect_paratext_project, scan_paratext_projects
from sage_core.profiles import load_workflow_profile
from sage_core.project_inventory import registered_project_records, update_project_record
from sage_core.registry import load_ecosystem
from sage_core.resource_mounts import clear_base_vrs_root, set_base_vrs_root, set_project_root
from sage_core.resource_registration import register_catalogued_scripture_project


def _write_pt_project(path: Path, *, iso: str, language: str, name: str) -> None:
    """Create one minimal Paratext fixture with settings metadata and one Scripture book."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "settings.xml").write_text(
        f"<Settings><Language>{language}</Language><FullName>{name}</FullName>"
        f"<LanguageIsoCode>{iso}:::</LanguageIsoCode></Settings>\n",
        encoding="utf-8",
    )
    (path / "01GEN.SFM").write_text("\\id GEN\n\\c 1\n\\v 1 Test.\n", encoding="utf-8")


def _add_fa_profile(root: Path) -> None:
    """Add the shipped Persian WIP profile under its existing `fa` namespace."""
    source = Path(__file__).resolve().parents[1] / "profiles" / "languages" / "fa" / "wip.yml"
    destination = root / "profiles" / "languages" / "fa" / "wip.yml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    settings_path = root / "ecosystem.yml"
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    raw["language_profiles"]["fa"] = {
        "script": "Arab",
        "variants": {"wip": {"file": "profiles/languages/fa/wip.yml", "role": "WIP"}},
    }
    settings_path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")


def test_saw_job_runtime_ignores_unbound_inactive_bic_template(make_workspace) -> None:
    """The active SAW Job must not be rejected because the inactive BIC template is unbound."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    bic_profile_path = root / "workflows" / "bic" / "profile.yml"
    bic_raw = yaml.safe_load(bic_profile_path.read_text(encoding="utf-8"))
    bic_raw["bindings"] = {}
    bic_raw["permissions"]["may_write_projects"] = []
    bic_profile_path.write_text(yaml.safe_dump(bic_raw, sort_keys=False), encoding="utf-8")

    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="SAW runtime isolation",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )

    config = load_ecosystem(job.runtime_settings_path)
    saw = load_workflow_profile(config, config.workflow("saw"))
    bic = load_workflow_profile(config, config.workflow("bic"))
    assert saw.bindings["WIP"] == "usWIP"
    assert saw.bindings["REFERENCE"] == "usNIVv2"
    assert bic.bindings == {}


def test_valid_persian_iso_adds_to_sage_without_language_profile(make_workspace, tmp_path: Path) -> None:
    """A valid ISO Project identity is inventory-valid even before a SAGE grammar profile exists."""
    root = make_workspace()
    _add_fa_profile(root)
    project = tmp_path / "faTMNv4"
    _write_pt_project(project, iso="pes", language="Iranian Persian", name="New Persian Contemporary Bible v.4")

    row = inspect_paratext_project(project)
    assert row["language_resolution"]["status"] == "VALID"
    assert row["language_resolution"]["prefix_evidence"] == "fa -> Persian [consistent]"
    created = register_catalogued_scripture_project(root / "ecosystem.yml", catalogue_row=row)
    assert created == "faTMNv4"

    config = load_ecosystem(root / "ecosystem.yml")
    sage_project = config.project("faTMNv4")
    assert sage_project.language_code == "pes"
    assert sage_project.scope.roles == ()
    assert "faTMNv4" in registered_project_records(root)

    store = JobStore(root, root / "ecosystem.yml")
    with pytest.raises(ValidationError) as caught:
        store.create_job(
            tool="saw",
            job_id="SAW_faTMNv4-usNIVv2",
            display_name="Persian profile gate",
            bindings={"wip": "faTMNv4", "reference": "usNIVv2"},
            profiles={},
            defaults={},
        )
    assert caught.value.code == "LANGUAGE_PROFILE_NOT_CONFIGURED"
    assert caught.value.details["profile_alias_suggestion"] == {
        "language": "pes",
        "language_name": "Iranian Persian",
        "project_prefix": "fa",
        "prefix_language_name": "Persian",
        "profile_alias": "fa",
        "script": "Arab",
        "role": "WIP",
        "variants": ["wip"],
    }


def test_menu_can_add_iso_profile_alias_and_retry_job_creation(make_workspace, tmp_path: Path) -> None:
    """The operator can approve pes -> fa in ecosystem.yml without changing Project identity."""
    root = make_workspace()
    _add_fa_profile(root)
    project = tmp_path / "faTMNv4"
    _write_pt_project(project, iso="pes", language="Iranian Persian", name="New Persian Contemporary Bible v.4")
    row = inspect_paratext_project(project)
    register_catalogued_scripture_project(root / "ecosystem.yml", catalogue_row=row)
    store = JobStore(root, root / "ecosystem.yml")

    with pytest.raises(ValidationError) as caught:
        store.create_job(
            tool="saw",
            job_id="SAW_faTMNv4-usNIVv2",
            display_name="Persian profile alias",
            bindings={"wip": "faTMNv4", "reference": "usNIVv2"},
            profiles={},
            defaults={},
        )

    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["1"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    assert center._offer_language_profile_alias(caught.value) is True

    raw = yaml.safe_load((root / "ecosystem.yml").read_text(encoding="utf-8"))
    assert raw["language_profiles"]["pes"] == {"script": "Arab", "profile_alias": "fa"}
    config = load_ecosystem(root / "ecosystem.yml")
    assert config.language_profiles["pes"].profile_language == "fa"
    assert config.project("faTMNv4").language_code == "pes"

    created = store.create_job(
        tool="saw",
        job_id="SAW_faTMNv4-usNIVv2",
        display_name="Persian profile alias",
        bindings={"wip": "faTMNv4", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )
    assert created.profiles["target_grammar"] == "pes/wip"
    runtime = load_ecosystem(store.write_runtime_files(created))
    assert runtime.project("faTMNv4").profile_ref == "pes/wip"
    assert "ISO language:    pes - Iranian Persian" in output.getvalue()
    assert "Updated ecosystem.yml" in output.getvalue()


def test_job_validation_can_apply_detected_base_vrs_with_operator_approval(
    make_workspace,
    tmp_path: Path,
) -> None:
    """A custom.vrs base correction is persisted only after the menu choice."""
    root = make_workspace()
    project = tmp_path / "faTMNv4"
    _write_pt_project(project, iso="pes", language="Iranian Persian", name="Persian Test")
    (project / "custom.vrs").write_text(
        '#\n# Versification "Farsi"\n# custom.vrs by Project Team\n'
        '# custom modifications to eng.vrs (English RSV versification)\n',
        encoding="utf-8",
    )
    row = inspect_paratext_project(project)
    register_catalogued_scripture_project(root / "ecosystem.yml", catalogue_row=row)
    record = registered_project_records(root)["faTMNv4"]
    incorrect = dict(record["versification"])
    incorrect["base_file"] = "org.vrs"
    update_project_record(root, "faTMNv4", {"versification": incorrect})

    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=root / "ecosystem.yml",
        io=MenuIO(input_func=ScriptedInput(["1"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    job = SimpleNamespace(bindings={"wip": "faTMNv4"})
    assert center._offer_detected_vrs_updates(job) is True
    updated = registered_project_records(root)["faTMNv4"]
    assert updated["versification"]["base_file"] == "eng.vrs"
    assert "faTMNv4: org.vrs -> eng.vrs" in output.getvalue()


def test_missing_persian_iso_uses_name_and_prefix_as_suggestions() -> None:
    """Missing ISO metadata may be suggested from evidence but is not silently replaced."""
    result = resolve_paratext_language(
        settings_code=None,
        language_name="Iranian Persian",
        project_prefix="fa",
    )
    assert result["status"] == "MISSING"
    assert "pes" in result["suggestions"]
    assert result["declared_code"] is None


def test_base_vrs_root_defaults_to_paratext_root_until_explicit_override(make_workspace, tmp_path: Path) -> None:
    """Paratext root is the default Base VRS root; an explicit override is sticky."""
    root = make_workspace()
    first = tmp_path / "PT-A"
    override = tmp_path / "VRS-OVERRIDE"
    second = tmp_path / "PT-B"
    for path in (first, override, second):
        path.mkdir()

    set_project_root(root, project_root=first)
    assert load_ecosystem(root / "ecosystem.yml").base_vrs_root == first.resolve()

    set_base_vrs_root(root, base_vrs_root=override)
    set_project_root(root, project_root=second)
    assert load_ecosystem(root / "ecosystem.yml").base_vrs_root == override.resolve()

    clear_base_vrs_root(root)
    assert load_ecosystem(root / "ecosystem.yml").base_vrs_root == second.resolve()


def test_paratext_scan_reports_simple_progress_heartbeat(tmp_path: Path) -> None:
    """Scanning reports deterministic completed/total progress for a rotating UI status line."""
    sage = tmp_path / "SAGE"
    sage.mkdir()
    projects = tmp_path / "Paratext Projects"
    projects.mkdir()
    _write_pt_project(projects / "usABCv0", iso="en", language="English", name="A")
    (projects / "ignored").mkdir()
    bad = projects / "bad"
    bad.mkdir()
    (bad / "settings.xml").write_text("<Settings>", encoding="utf-8")

    seen: list[tuple[int, int]] = []
    scan_paratext_projects(sage, projects, full=True, progress=lambda done, total: seen.append((done, total)))
    assert seen[0] == (0, 3)
    assert seen[-1] == (3, 3)
    assert [done for done, _ in seen] == sorted(done for done, _ in seen)


def test_remove_job_deletes_only_job_owned_state(make_workspace) -> None:
    """Remove Job clears Job-local state and pointers without deleting Scripture Projects."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="Disposable SAW Job",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )
    store.set_active_job("saw", job.job_id)
    run = store.create_run(job, operation="qa", scope="MAT 1:1")
    project_paths = [root / "projects" / "usWIP", root / "projects" / "usNIVv2"]
    assert run.root.is_dir()

    store.remove_job(job)

    assert not job.root.exists()
    assert store.active_jobs()["saw"] is None
    assert not store.last_run_path.exists()
    assert all(path.is_dir() for path in project_paths)


def test_pre_run_preview_supports_change_scope(make_workspace) -> None:
    """The preview must let the operator return to scope selection before a Run exists."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.bootstrap_default_jobs()[0]
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        io=MenuIO(input_func=ScriptedInput(["2"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    center.controller = lambda _job, _args: {
        "summary": {"work_units": 1, "largest_estimated_tokens": 2450},
        "policy": {"hard_estimated_tokens": 8000},
        "units": [{"primary_scope": "MAT 1:1-10", "measurement": {"estimated_tokens": 2450}}],
    }
    action = center._review_work_before_run(job, operation="inspect", scope="MAT 1:1-10")
    assert action == "CHANGE"
    assert "REVIEW WORK BEFORE RUNNING" in output.getvalue()
    assert "Change scope" in output.getvalue()
