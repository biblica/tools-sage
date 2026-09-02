"""Regressions for role-neutral SAGE Projects, Jobs, and runtime isolation."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sage.storage import storage_layout
from sage.errors import ValidationError
from sage.iso_languages import resolve_paratext_language
from sage.jobs import JobStore
from sage.menu import MenuIO, SageControlCenter, ScriptedInput
from sage.paratext_catalog import inspect_paratext_project, scan_paratext_projects
from sage.profiles import load_workflow_profile
from sage.project_inventory import registered_project_records, update_project_record
from sage.registry import load_ecosystem
from sage.resource_mounts import clear_base_vrs_root, set_base_vrs_root, set_project_root
from sage.resource_registration import register_catalogued_scripture_project
from sage.scripture import compile_project
from conftest import grammar_profile


def _write_pt_project(path: Path, *, iso: str, language: str, name: str) -> None:
    """Create one minimal Paratext fixture with settings metadata and one Scripture book."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "settings.xml").write_text(
        f"<Settings><Language>{language}</Language><FullName>{name}</FullName>"
        f"<LanguageIsoCode>{iso}:::</LanguageIsoCode></Settings>\n",
        encoding="utf-8",
    )
    (path / "01GEN.SFM").write_text("\\id GEN\n\\c 1\n\\v 1 Test.\n", encoding="utf-8")


def _add_fa_ir_profile(root: Path) -> None:
    """Add a test-only Iranian Persian WIP profile under the governed `fa-IR` namespace."""
    destination = root / "system" / "config" / "profiles" / "grammar" / "fa" / "wip.yml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        yaml.safe_dump(grammar_profile("fa-ir-wip", "fa-IR", "WIP"), sort_keys=False),
        encoding="utf-8",
    )
    settings_path = root / "ecosystem.yml"
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    raw["language_profiles"]["fa-IR"] = {
        "script": "Arab",
        "variants": {"wip": {"file": "system/config/profiles/grammar/fa-IR/wip.yml", "role": "WIP"}},
    }
    settings_path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _add_pes_ir_profile(root: Path) -> None:
    """Add a test-only Iranian Persian regional WIP profile."""
    destination = root / "system" / "config" / "profiles" / "grammar" / "pes-IR" / "wip.yml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        yaml.safe_dump(grammar_profile("pes-ir-wip", "pes-IR", "WIP"), sort_keys=False),
        encoding="utf-8",
    )
    settings_path = root / "ecosystem.yml"
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    raw["language_profiles"]["pes-IR"] = {
        "script": "Arab",
        "variants": {"wip": {"file": "system/config/profiles/grammar/pes-IR/wip.yml", "role": "WIP"}},
    }
    settings_path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")


def test_saw_job_runtime_ignores_unbound_inactive_bic_template(make_workspace) -> None:
    """The active SAW Job must not be rejected because the inactive BIC template is unbound."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    bic_profile_path = root / "system" / "config" / "workflows" / "bic" / "profile.yml"
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


def test_preserved_bic_job_derives_new_donor_profile_without_rewriting(
    make_workspace,
) -> None:
    """Load a beta BIC Job that predates the alpha donor-grammar binding."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="bic",
        job_id="BIC_idKKHv0-usNIVv2-usBOLx1",
        display_name="Preserved BIC profile contract",
        bindings={
            "content_source": "idKKHv0",
            "lexical_donor": "usNIVv2",
            "generated_target": "usBOLx1",
        },
        profiles={},
        defaults={},
    )
    raw = yaml.safe_load(job.manifest_path.read_text(encoding="utf-8"))
    raw["profiles"].pop("donor_grammar")
    job.manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    loaded = store.load_job(job.job_id, tool="bic")

    assert loaded.profiles["donor_grammar"]
    persisted = yaml.safe_load(job.manifest_path.read_text(encoding="utf-8"))
    assert "donor_grammar" not in persisted["profiles"]


def test_job_primary_and_optional_secondary_are_runtime_owned(make_workspace) -> None:
    """Each Job snapshots one primary and may independently add or clear a secondary."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    settings_path = root / "ecosystem.yml"
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    raw["human_output"] = {
        "operator_language": "id",
        "logs_and_reports": {
            "primary_language": "OPERATOR_LANGUAGE",
            "secondary_language": None,
            "bilingual": False,
            "verbosity": "normal",
        },
        "translation_challenges": {
            "primary_language": "OPERATOR_LANGUAGE",
            "secondary_language": None,
            "bilingual": False,
            "minimum_individual_urgency": 2,
            "aggregate_lower_levels": True,
            "consolidate_repeated_cause": True,
            "render_only_material_fields": True,
        },
        "machine_records": {"language": "canonical", "localise_codes": False},
    }
    settings_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    store = JobStore(root, settings_path)
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="Language ownership",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
        primary_report_language="fr",
        secondary_report_language="uk",
    )
    runtime = yaml.safe_load(job.runtime_settings_path.read_text(encoding="utf-8"))
    assert job.primary_report_language == "fr"
    assert job.secondary_report_language == "uk"
    assert runtime["human_output"]["operator_language"] == "fr"
    assert runtime["human_output"]["logs_and_reports"]["primary_language"] == "fr"
    assert runtime["human_output"]["logs_and_reports"]["secondary_language"] == "uk"
    assert runtime["human_output"]["logs_and_reports"]["bilingual"] is True
    assert runtime["human_output"]["translation_challenges"]["primary_language"] == "fr"
    assert runtime["human_output"]["translation_challenges"]["secondary_language"] == "uk"

    revised = store.revise_job(job, reporting={"secondary_language": None})
    revised_runtime = yaml.safe_load(revised.runtime_settings_path.read_text(encoding="utf-8"))
    assert revised.secondary_report_language is None
    assert revised_runtime["human_output"]["logs_and_reports"]["secondary_language"] is None
    assert revised_runtime["human_output"]["logs_and_reports"]["bilingual"] is False

    with pytest.raises(ValidationError) as caught:
        store.revise_job(revised, reporting={"secondary_language": "fr"})
    assert caught.value.code == "JOB_REPORTING_LANGUAGE_CONFLICT"


def test_legacy_job_primary_is_snapshotted_during_runtime_refresh(make_workspace) -> None:
    """A legacy secondary-only Job is upgraded once before it can create provider tasks."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="Legacy reporting upgrade",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
        secondary_report_language="uk",
    )
    raw = yaml.safe_load(job.manifest_path.read_text(encoding="utf-8"))
    raw["reporting"].pop("primary_language")
    job.manifest_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    legacy = store.load_job(job.job_id, tool="saw")
    assert legacy.reporting_contract_persisted is False
    assert legacy.primary_report_language == "en"

    store.ensure_runtime_files(legacy)
    upgraded = store.load_job(job.job_id, tool="saw")
    persisted = yaml.safe_load(upgraded.manifest_path.read_text(encoding="utf-8"))
    assert upgraded.reporting_contract_persisted is True
    assert persisted["reporting"] == {"primary_language": "en", "secondary_language": "uk"}
    assert upgraded.configuration_revision == 2


def test_global_default_change_does_not_rewrite_existing_job_primary(make_workspace) -> None:
    """A Job keeps the primary language captured when it was created."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    settings_path = root / "ecosystem.yml"
    store = JobStore(root, settings_path)
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="Stable report language",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )
    assert job.primary_report_language == "en"

    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    raw["human_output"] = {
        "operator_language": "id",
        "logs_and_reports": {
            "primary_language": "OPERATOR_LANGUAGE",
            "secondary_language": None,
            "bilingual": False,
            "verbosity": "normal",
        },
        "translation_challenges": {
            "primary_language": "OPERATOR_LANGUAGE",
            "secondary_language": None,
            "bilingual": False,
            "minimum_individual_urgency": 2,
            "aggregate_lower_levels": True,
            "consolidate_repeated_cause": True,
            "render_only_material_fields": True,
        },
        "machine_records": {"language": "canonical", "localise_codes": False},
    }
    settings_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    reloaded = store.load_job(job.job_id, tool="saw")
    store.ensure_runtime_files(reloaded)
    runtime = yaml.safe_load(reloaded.runtime_settings_path.read_text(encoding="utf-8"))
    assert reloaded.primary_report_language == "en"
    assert runtime["human_output"]["logs_and_reports"]["primary_language"] == "en"


def test_persian_project_requires_explicit_regional_profile_before_registration(make_workspace, tmp_path: Path) -> None:
    """Iranian Persian remains `pes` evidence and binds explicitly to `pes-IR` before registration."""
    root = make_workspace()
    _add_fa_ir_profile(root)
    project = tmp_path / "faTMNv4"
    _write_pt_project(project, iso="pes", language="Iranian Persian", name="New Persian Contemporary Bible v.4")

    row = inspect_paratext_project(project)
    assert row["language_resolution"]["status"] == "VALID"
    assert row["language_resolution"]["prefix_evidence"] == "fa -> Persian [consistent]"
    assert resolve_paratext_language(settings_code="pes", language_name="Iranian Persian", project_prefix="fa")["canonical_alpha_3"] == "pes"
    row["language_profile_tag"] = "pes-IR"
    with pytest.raises(ValidationError) as caught:
        register_catalogued_scripture_project(root / "ecosystem.yml", catalogue_row=row)
    assert caught.value.code == "LANGUAGE_PROFILE_NOT_CONFIGURED"

    _add_pes_ir_profile(root)
    assert register_catalogued_scripture_project(root / "ecosystem.yml", catalogue_row=row) == "faTMNv4"
    config = load_ecosystem(root / "ecosystem.yml")
    assert config.project("faTMNv4").language_code == "pes-IR"
    assert "faTMNv4" in registered_project_records(root)

    store = JobStore(root, root / "ecosystem.yml")
    created = store.create_job(
        tool="saw",
        job_id="SAW_faTMNv4-usNIVv2",
        display_name="Iranian Persian regional profile",
        bindings={"wip": "faTMNv4", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )
    assert created.profiles["target_grammar"] == "pes-IR/wip"


def test_current_operator_flow_does_not_create_profile_alias(make_workspace, tmp_path: Path) -> None:
    """Current Beta setup uses explicit regional profiles and never creates a `pes -> fa` alias."""
    root = make_workspace()
    _add_fa_ir_profile(root)
    _add_pes_ir_profile(root)
    project = tmp_path / "faTMNv4"
    _write_pt_project(project, iso="pes", language="Iranian Persian", name="New Persian Contemporary Bible v.4")
    row = inspect_paratext_project(project)
    row["language_profile_tag"] = "pes-IR"
    register_catalogued_scripture_project(root / "ecosystem.yml", catalogue_row=row)

    raw = yaml.safe_load((root / "ecosystem.yml").read_text(encoding="utf-8"))
    assert "pes" not in raw["language_profiles"]
    assert raw["language_profiles"]["pes-IR"].get("profile_alias") is None
    assert load_ecosystem(root / "ecosystem.yml").project("faTMNv4").language_code == "pes-IR"

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
    _add_pes_ir_profile(root)
    row["language_profile_tag"] = "pes-IR"
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
    sage = tmp_path / "SAGE" / "app"
    sage.mkdir(parents=True)
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
    run = store.create_run(job, operation="rtc", scope="MAT 1:1")
    project_paths = [storage_layout(root).projects_root / "usWIP", storage_layout(root).projects_root / "usNIVv2"]
    assert run.root.is_dir()

    store.remove_job(job)

    assert not job.root.exists()
    assert store.active_jobs()["saw"] is None
    assert not store.last_run_path.exists()
    assert all(path.is_dir() for path in project_paths)


def test_missing_active_job_manifest_does_not_block_recovery_ui(make_workspace) -> None:
    """Keep stale pointer evidence while treating its missing Job as unavailable."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    store.active_jobs_path.parent.mkdir(parents=True, exist_ok=True)
    store.active_jobs_path.write_text(
        '{"schema_version":"1.0","bic":null,"saw":"SAW_missing-usREF"}\n',
        encoding="utf-8",
    )

    assert store.active_job("saw") is None
    assert store.active_jobs()["saw"] == "SAW_missing-usREF"
    assert store.stale_active_job_pointers() == {"saw": "SAW_missing-usREF"}
    assert store.active_jobs_path.is_file()


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


def test_rtc_pre_run_preview_renders_aligned_routed_sfm_columns(make_workspace) -> None:
    """RTC preview reports WIP/REF/ROUTE SFM columns without packet-overhead concepts."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        io=MenuIO(input_func=ScriptedInput(["A"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    center.controller = lambda _job, _args: {
        "summary": {
            "work_units": 1,
            "largest_wip_estimated_tokens": 6100,
            "largest_ref_estimated_tokens": 5900,
            "largest_route_estimated_tokens": 12000,
        },
        "policy": {"hard_estimated_tokens": 7999},
        "units": [{
            "primary_scope": "MAT 1:1-10",
            "rtc_package": {
                "wip": {"estimated_tokens": 6100},
                "ref": {"estimated_tokens": 5900},
                "route": {"estimated_tokens": 12000},
            },
        }],
    }

    action = center._review_work_before_run(job, operation="rtc", scope="MAT 1:1-10")

    rendered = output.getvalue()
    assert action == "CANCEL"
    assert "Reference Text Comparison (RTC)" in rendered
    assert "  #  SCOPE                      WIP       REF      ROUTE" in rendered
    assert "  1. MAT 1:1-10              ~6,100    ~5,900    ~12,000" in rendered
    assert "     Largest work unit       ~6,100    ~5,900    ~12,000" in rendered
    assert "Token limit:" not in rendered


def test_stc_pre_run_preview_renders_aligned_routed_sfm_columns(make_workspace) -> None:
    """STC preview mirrors the RTC table with WIP/SRC/ROUTE columns."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        io=MenuIO(input_func=ScriptedInput(["A"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    center.controller = lambda _job, _args: {
        "summary": {
            "work_units": 1,
            "largest_wip_estimated_tokens": 610,
            "largest_ol_estimated_tokens": 390,
            "largest_route_estimated_tokens": 1000,
        },
        "policy": {"hard_estimated_tokens": 18000},
        "units": [{
            "primary_scope": "MAT 1:1-10",
            "stc_package": {
                "wip": {"estimated_tokens": 610},
                "ol": {"estimated_tokens": 390},
                "route": {"estimated_tokens": 1000},
            },
        }],
    }

    action = center._review_work_before_run(job, operation="stc", scope="MAT 1:1-10")

    rendered = output.getvalue()
    assert action == "CANCEL"
    assert "  #  SCOPE                      WIP       SRC      ROUTE" in rendered
    assert "  1. MAT 1:1-10                ~610      ~390     ~1,000" in rendered
    assert "     Largest work unit         ~610      ~390     ~1,000" in rendered
    assert "Token limit:" not in rendered


def test_stc_preview_rejects_generic_measurements_instead_of_downgrading_ui(
    make_workspace,
) -> None:
    """STC must never fall back to the unrelated one-stream token preview."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = next(item for item in store.bootstrap_default_jobs() if item.tool == "saw")
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        io=MenuIO(input_func=ScriptedInput([]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    center.controller = lambda _job, _args: {
        "summary": {"work_units": 1, "largest_estimated_tokens": 10917},
        "policy": {"hard_estimated_tokens": 18000},
        "units": [{
            "primary_scope": "1JN 1:1-5:21",
            "measurement": {"estimated_tokens": 10917},
        }],
    }

    with pytest.raises(ValidationError) as caught:
        center._review_work_before_run(job, operation="stc", scope="1JN 1:1-5:21")

    assert caught.value.code == "SAW_STC_PREVIEW_INVALID"
    rendered = output.getvalue()
    assert "Token limit:" not in rendered
    assert "estimated routed-SFM tokens" not in rendered
    assert "Planning bounded SAW work" not in rendered


def test_existing_ecosystem_can_register_packaged_ukrainian_wip_and_retry_job(make_workspace) -> None:
    """An existing pre-Beta ecosystem can recover Ukrainian SAW Job creation in-menu."""
    import copy

    root = make_workspace(configured=True, qualification_status="VALIDATED")
    settings_path = root / "ecosystem.yml"
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    assert "uk-UA" not in raw["language_profiles"]

    uk_project = copy.deepcopy(raw["projects"]["usWIP"])
    uk_project["path"] = "ukrNPUv1"
    uk_project["language"] = {"code": "uk-UA", "profile": "uk-UA"}
    raw["projects"]["ukrNPUv1"] = uk_project
    settings_path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    project_root = storage_layout(root).projects_root / "ukrNPUv1"
    project_root.mkdir()
    (project_root / "41MAT.SFM").write_text("\\id MAT Fixture\n\\c 1\n\\v 1 Тест.\n", encoding="utf-8")

    store = JobStore(root, settings_path)
    with pytest.raises(ValidationError) as caught:
        store.create_job(
            tool="saw",
            job_id="SAW_ukrNPUv1-usNIVv2",
            display_name="Ukrainian WIP",
            bindings={"wip": "ukrNPUv1", "reference": "usNIVv2"},
            profiles={},
            defaults={},
        )
    assert caught.value.code == "LANGUAGE_PROFILE_NOT_CONFIGURED"

    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=settings_path,
        io=MenuIO(input_func=ScriptedInput(["1"]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    assert center._offer_packaged_language_profile(caught.value) is True

    config = load_ecosystem(settings_path)
    assert config.language_profiles["uk-UA"].script == "Cyrl"
    assert config.language_profiles["uk-UA"].variants["wip"].role == "WIP"
    created = store.create_job(
        tool="saw",
        job_id="SAW_ukrNPUv1-usNIVv2",
        display_name="Ukrainian WIP",
        bindings={"wip": "ukrNPUv1", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )
    assert created.profiles["target_grammar"] == "uk-UA/wip"
    assert "Register uk-UA/wip and retry job creation" in output.getvalue()
    assert "Updated local settings: language_profiles.uk-UA.variants.wip" in output.getvalue()


def test_missing_language_setup_opens_maintain_and_chooses_existing_profile(make_workspace) -> None:
    """A missing Job language routes through Maintain grammar profiles and retries after selection."""
    import copy

    root = make_workspace(configured=True, qualification_status="VALIDATED")
    settings_path = root / "ecosystem.yml"
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    raw["language_profiles"].pop("uk-UA", None)
    uk_project = copy.deepcopy(raw["projects"]["usWIP"])
    uk_project["path"] = "ukrNPUv1"
    uk_project["language"] = {"code": "uk-UA", "profile": "uk-UA"}
    raw["projects"]["ukrNPUv1"] = uk_project
    settings_path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    project_root = storage_layout(root).projects_root / "ukrNPUv1"
    project_root.mkdir()
    (project_root / "41MAT.SFM").write_text("\\id MAT Fixture\n\\c 1\n\\v 1 Тест.\n", encoding="utf-8")

    store = JobStore(root, settings_path)
    with pytest.raises(ValidationError) as caught:
        store.create_job(
            tool="saw",
            job_id="SAW_ukrNPUv1-usNIVv2",
            display_name="Ukrainian WIP",
            bindings={"wip": "ukrNPUv1", "reference": "usNIVv2"},
            profiles={},
            defaults={},
        )
    assert caught.value.code == "LANGUAGE_PROFILE_NOT_CONFIGURED"

    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=settings_path,
        io=MenuIO(input_func=ScriptedInput(["1", "1", ""]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    assert center._maintain_missing_language_profile(caught.value) is True
    config = load_ecosystem(settings_path)
    assert config.language_profiles["uk-UA"].variants["wip"].role == "WIP"

    created = store.create_job(
        tool="saw",
        job_id="SAW_ukrNPUv1-usNIVv2",
        display_name="Ukrainian WIP",
        bindings={"wip": "ukrNPUv1", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )
    assert created.profiles["target_grammar"] == "uk-UA/wip"
    rendered = output.getvalue()
    assert "GRAMMAR PROFILE REQUIRED" in rendered
    assert "Choose from existing profile list" in rendered
    assert "uk-UA/wip [WIP; PROJECT_REVIEW_REQUIRED]" in rendered


def test_maintain_grammar_profiles_can_add_external_yaml_file(make_workspace, tmp_path: Path) -> None:
    """The maintenance menu can import a valid external profile into the local governed profile library."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    settings_path = root / "ecosystem.yml"
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    raw["language_profiles"].pop("uk-UA", None)
    settings_path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")

    source_raw = yaml.safe_load(
        (root / "system/config/profiles/grammar/uk-UA/wip.yml").read_text(encoding="utf-8")
    )
    source_raw["profile"]["id"] = "review-wip"
    external = tmp_path / "uk-UA-review-wip.yml"
    external.write_text(yaml.safe_dump(source_raw, sort_keys=False, allow_unicode=True), encoding="utf-8")

    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=settings_path,
        io=MenuIO(input_func=ScriptedInput(["2", str(external), ""]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    assert center.maintain_grammar_profiles(language="uk-UA", role="WIP", return_on_change=True) is True

    config = load_ecosystem(settings_path)
    variant = config.language_profiles["uk-UA"].variants["review-wip"]
    assert variant.role == "WIP"
    assert variant.path == (storage_layout(root).resources_root / "grammar-profiles/uk-UA/review-wip.yml").resolve()
    assert variant.path.is_file()
    assert "Grammar profile registered: uk-UA/review-wip" in output.getvalue()


def test_create_job_menu_recovers_missing_language_through_maintenance(make_workspace, monkeypatch) -> None:
    """The actual Create Job menu retries after Maintain grammar profiles resolves the missing WIP profile."""
    import copy

    root = make_workspace(configured=True, qualification_status="VALIDATED")
    settings_path = root / "ecosystem.yml"
    raw = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    raw["language_profiles"].pop("uk-UA", None)
    uk_project = copy.deepcopy(raw["projects"]["usWIP"])
    uk_project["path"] = "ukrNPUv1"
    uk_project["language"] = {"code": "uk-UA", "profile": "uk-UA"}
    raw["projects"]["ukrNPUv1"] = uk_project
    settings_path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    project_root = storage_layout(root).projects_root / "ukrNPUv1"
    project_root.mkdir()
    (project_root / "41MAT.SFM").write_text("\\id MAT Fixture\n\\c 1\n\\v 1 Тест.\n", encoding="utf-8")

    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        settings_path=settings_path,
        io=MenuIO(input_func=ScriptedInput(["1", "1", "1", "", "1", ""]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    config = load_ecosystem(settings_path)
    selected = iter((config.project("ukrNPUv1"), config.project("usNIVv2")))
    monkeypatch.setattr(center, "choose_or_add_resource", lambda *_args, **_kwargs: next(selected))

    center.create_job_wizard("saw")

    store = JobStore(root, settings_path)
    created = store.load_job("SAW_ukrNPUv1-usNIVv2", tool="saw")
    assert created.profiles["target_grammar"] == "uk-UA/wip"
    rendered = output.getvalue()
    assert "GRAMMAR PROFILE REQUIRED" in rendered
    assert "GRAMMAR PROFILE REQUIRED" in rendered
    assert "Created and selected Job: SAW_ukrNPUv1-usNIVv2" in rendered


def test_saw_preview_preflight_localizes_reference_defect_to_affected_work_unit(make_workspace) -> None:
    """Whole-book SAW setup must identify only the planned section intersecting a REFERENCE defect."""
    root = make_workspace(configured=True, qualification_status="VALIDATED", verse_max=4)
    reference = storage_layout(root).projects_root / "usNIVv2" / "41MAT.SFM"
    reference.write_text(
        "\\id MAT Fixture\n\\c 1\n\\p\n\\v 1 One.\n\\v 2 Two.\n\\v 3 Three.\n\\v 3 Duplicate.\n",
        encoding="utf-8",
    )
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="Section preflight",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )
    center = SageControlCenter(
        sage_root=root,
        io=MenuIO(input_func=ScriptedInput([]), output=io.StringIO()),
        skip_setup=True,
        dry_run_provider=True,
    )
    preview = {
        "units": [
            {"primary_scope": "MAT 1:1-2"},
            {"primary_scope": "MAT 1:3-4"},
        ]
    }

    blockers = center._saw_preview_blockers(job, preview)

    assert blockers
    assert {row["scope"] for row in blockers} == {"MAT 1:3-4"}
    assert {row["project_id"] for row in blockers} == {"usNIVv2"}
    assert {row["role"] for row in blockers} == {"SAW REFERENCE"}
    assert any(row["code"] == "DUPLICATE_VERSE_RANGE" for row in blockers)
    assert any(row["reference"].startswith("MAT 1:3") for row in blockers)


def test_option_10_preflight_requires_testament_specific_ol_binding(make_workspace) -> None:
    """Enabled RTC option #10 needs the applicable Greek or Hebrew binding before a Run."""
    root = make_workspace(configured=True, qualification_status="VALIDATED", verse_max=2)
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="Option 10 preflight",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )
    center = SageControlCenter(
        sage_root=root,
        io=MenuIO(input_func=ScriptedInput([]), output=io.StringIO()),
        skip_setup=True,
        dry_run_provider=True,
    )

    findings = center._saw_preview_findings(
        job,
        {"units": [{"primary_scope": "MAT 1:1-2"}]},
        require_original_language=True,
    )

    assert any(
        row["code"] == "APPLICABLE_ORIGINAL_LANGUAGE_NOT_CONFIGURED"
        and row["role"] == "SAW OL GREEK"
        for row in findings["blockers"]
    )
    assert store.list_runs(job) == []


def test_stc_preflight_requires_source_but_does_not_validate_reference(make_workspace) -> None:
    """STC preflight is independent from REFERENCE and validates its primary OL source."""
    root = make_workspace(configured=True, qualification_status="VALIDATED", verse_max=2)
    reference = storage_layout(root).projects_root / "usNIVv2" / "41MAT.SFM"
    reference.write_text(
        "\\id MAT Fixture\n\\c 1\n\\p\n\\v 1 One.\n\\v 1 Duplicate.\n",
        encoding="utf-8",
    )
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="STC independent preflight",
        bindings={
            "wip": "usWIP",
            "reference": "usNIVv2",
            "original_language_greek": "GRK",
        },
        profiles={},
        defaults={},
    )
    center = SageControlCenter(
        sage_root=root,
        io=MenuIO(input_func=ScriptedInput([]), output=io.StringIO()),
        skip_setup=True,
        dry_run_provider=True,
    )

    findings = center._saw_preview_findings(
        job,
        {"operation": "stc", "units": [{"primary_scope": "MAT 1:1-2"}]},
        require_original_language=True,
    )

    assert findings["blockers"] == []


def test_catalogued_project_without_declared_vrs_defaults_to_eng(make_workspace, tmp_path: Path) -> None:
    """Undeclared Paratext versification uses ENG/KJV, not canonical ORG."""
    root = make_workspace()
    project = tmp_path / "usNASB"
    _write_pt_project(project, iso="en", language="English", name="NASB")
    row = inspect_paratext_project(project)
    assert not str((row.get("versification") or {}).get("base_file") or "").strip()

    register_catalogued_scripture_project(root / "ecosystem.yml", catalogue_row=row)
    record = registered_project_records(root)["usNASB"]

    assert record["versification"]["base_file"] == "eng.vrs"
    assert record["versification"]["base_selection"] == "DEFAULT"
    assert record["versification"]["reported_base_file"] is None


def test_legacy_undeclared_org_fallback_is_effectively_migrated_to_eng(make_workspace, tmp_path: Path) -> None:
    """Legacy registered Projects that inherited org.vrs are treated as default ENG/KJV in memory."""
    root = make_workspace()
    project = tmp_path / "usNASB"
    _write_pt_project(project, iso="en", language="English", name="NASB")
    row = inspect_paratext_project(project)
    register_catalogued_scripture_project(root / "ecosystem.yml", catalogue_row=row)
    record = registered_project_records(root)["usNASB"]
    legacy_vrs = dict(record["versification"])
    legacy_vrs.pop("base_selection", None)
    legacy_vrs["base_file"] = "org.vrs"
    legacy_vrs["reported_base_file"] = None
    update_project_record(root, "usNASB", {"versification": legacy_vrs})

    config = load_ecosystem(root / "ecosystem.yml")
    assert config.default_versification == "eng.vrs"
    assert config.project("usNASB").versification.base_file == "eng.vrs"


def test_saw_preflight_reports_daniel_eng_org_differences_without_blocking(make_workspace) -> None:
    """NASB-style Daniel numbering is advisory against ORG when ENG/KJV explains the coordinates."""
    root = make_workspace(configured=True, qualification_status="VALIDATED", verse_max=4)
    eng_max = {1: 21, 2: 49, 3: 30, 4: 37, 5: 31, 6: 28, 7: 28, 8: 27, 9: 27, 10: 21, 11: 45, 12: 13}
    org_max = {1: 21, 2: 49, 3: 33, 4: 34, 5: 30, 6: 29, 7: 28, 8: 27, 9: 27, 10: 21, 11: 45, 12: 13}
    eng_line = "DAN " + " ".join(f"{c}:{v}" for c, v in eng_max.items())
    org_line = "DAN " + " ".join(f"{c}:{v}" for c, v in org_max.items())
    (root / "system/resources/scripture/eng.vrs").write_text(
        "MAT 1:4\n" + eng_line + "\n"
        "DAN 4:1-3 = DAN 3:31-33\nDAN 4:4-37 = DAN 4:1-34\n"
        "DAN 5:31 = DAN 6:1\nDAN 6:1-28 = DAN 6:2-29\n",
        encoding="utf-8",
    )
    (root / "system/resources/scripture/org.vrs").write_text("MAT 1:4\n" + org_line + "\n", encoding="utf-8")

    def dan_usfm() -> str:
        """Return a complete English/KJV-numbered Daniel fixture."""
        lines = ["\\id DAN Fixture"]
        for chapter, maximum in eng_max.items():
            lines.append(f"\\c {chapter}")
            lines.append("\\p")
            for verse in range(1, maximum + 1):
                lines.append(f"\\v {verse} Verse {chapter}:{verse}.")
        return "\n".join(lines) + "\n"

    for project_id in ("usWIP", "usNIVv2"):
        folder = storage_layout(root).projects_root / project_id
        (folder / "41MAT.SFM").unlink()
        (folder / "27DAN.SFM").write_text(dan_usfm(), encoding="utf-8")

    settings = root / "ecosystem.yml"
    raw = yaml.safe_load(settings.read_text(encoding="utf-8"))
    raw["versification"]["default_file"] = "eng.vrs"
    for project_id in ("usWIP", "usNIVv2"):
        raw["projects"][project_id]["scope"]["expected_books"] = ["DAN"]
        raw["projects"][project_id]["scope"]["testament"] = "OT"
    raw["projects"]["usNIVv2"]["versification"]["base_file"] = "org.vrs"
    settings.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    store = JobStore(root, settings)
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="Daniel VRS advisory",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )
    center = SageControlCenter(
        sage_root=root,
        io=MenuIO(input_func=ScriptedInput([]), output=io.StringIO()),
        skip_setup=True,
        dry_run_provider=True,
    )
    findings = center._saw_preview_findings(
        job,
        {"units": [{"primary_scope": "DAN 3:27-4:1"}, {"primary_scope": "DAN 4:31-35"}]},
    )

    assert findings["blockers"] == []
    refs = {row["reference"] for row in findings["advisories"]}
    assert {"DAN 3:31", "DAN 3:32", "DAN 3:33", "DAN 4:35"}.issubset(refs)
    assert all(row["default_vrs"] == "eng.vrs" for row in findings["advisories"])


def test_routine_saw_preflight_keeps_vrs_advisory_details_out_of_ui(make_workspace) -> None:
    """Non-blocking coordinate differences persist without cluttering Run preflight."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="Silent VRS advisory",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )
    output = io.StringIO()
    center = SageControlCenter(
        sage_root=root,
        io=MenuIO(input_func=ScriptedInput([]), output=output),
        skip_setup=True,
        dry_run_provider=True,
    )
    advisory = {
        "role": "SAW OL GREEK",
        "project_id": "GRK",
        "scope": "JHN 4:43-5:30",
        "status": "ADVISORY",
        "code": "EXPECTED_COORDINATE_MISSING",
        "reference": "JHN 5:4",
        "message": "Coordinate is expected by the effective VRS.",
        "effective_vrs": "org.vrs",
        "default_vrs": "eng.vrs",
    }
    center._saw_preview_findings = lambda *_args, **_kwargs: {
        "blockers": [],
        "advisories": [advisory],
    }

    status = center._preflight_saw_preview(
        job,
        {"units": [{"primary_scope": "JHN 4:43-5:30"}]},
        operation="stc",
        require_original_language=True,
    )

    assert status == "READY_WITH_STRUCTURE_PROBLEMS"
    assert center._pending_saw_vrs_advisories == [advisory]
    rendered = output.getvalue()
    assert "SAW VERSIFICATION ADVISORY" not in rendered
    assert "EXPECTED_COORDINATE_MISSING" not in rendered
    assert "JHN 5:4" not in rendered
    assert "Checking SAW resources for each planned section" not in rendered


def test_vrs_only_project_differences_do_not_block_saw_initialization(make_workspace) -> None:
    """VRS coordinate advisories keep SAW REFERENCE and GRK resources executable."""
    root = make_workspace(configured=True, qualification_status="VALIDATED", verse_max=4)
    # Remove MAT 1:4 from REFERENCE and GRK so the configured VRS expects a coordinate
    # that is absent. This must remain an advisory, not resource BLOCKED state.
    for project_id in ("usNIVv2", "GRK"):
        path = storage_layout(root).projects_root / project_id / "41MAT.SFM"
        path.write_text("\\id MAT Fixture\n\\c 1\n\\p\n\\v 1 One.\n\\v 2 Two.\n\\v 3 Three.\n", encoding="utf-8")

    store = JobStore(root, root / "ecosystem.yml")
    job = store.create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="VRS advisory readiness",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
    )
    config = load_ecosystem(root / "ecosystem.yml")
    reference = compile_project(config, config.project("usNIVv2"))
    greek = compile_project(config, config.project("GRK"))

    for result in (reference, greek):
        assert result["status"] == "READY_WITH_WARNINGS"
        assert result["issues"] == []
        assert any(row["code"] == "EXPECTED_COORDINATE_MISSING" for row in result["warnings"])

    # Workspace initialization already treats READY_WITH_WARNINGS as an executable
    # resource state; the regression here ensures VRS-only differences now reach it.
    assert {reference["status"], greek["status"]} <= {"READY", "READY_WITH_WARNINGS"}
