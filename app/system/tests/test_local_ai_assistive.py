"""Local AI assistive-mode authority, input-boundary, and fallback contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sage.errors import ValidationError
from sage.build_policy import ENABLED_AUTOMATED_PROVIDER_IDS
from sage.errors import ConfigurationError
from sage.jobs import JobStore
from sage.llm_settings import (
    load_llm_settings,
    local_ai_policy_status,
    set_local_admin_enabled,
    settings_path,
    update_llm_selection,
)
from sage.local_assistive import (
    ASSISTIVE_LABEL,
    LocalTransformService,
    compact_report_view,
)
from sage.ui_services import OperatorUIService


def _create_saw_job(root: Path, *, secondary: str | None = None):
    """Create the standard SAW fixture Job with optional secondary reporting."""
    return JobStore(root, root / "ecosystem.yml").create_job(
        tool="saw",
        job_id="SAW_usWIP-usNIVv2",
        display_name="Local AI fixture",
        bindings={"wip": "usWIP", "reference": "usNIVv2"},
        profiles={},
        defaults={},
        secondary_report_language=secondary,
    )


def test_existing_admin_assistant_switch_loads_unchanged(make_workspace) -> None:
    """The existing persisted Ollama boolean remains the sole Local AI enable switch."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "selected_provider": "codex",
                "providers": {"ollama": {"admin_assistant_enabled": True}},
            }
        ),
        encoding="utf-8",
    )

    loaded = load_llm_settings(root)

    assert loaded["providers"]["ollama"]["admin_assistant_enabled"] is True
    assert local_ai_policy_status(root)["authority"] == "ASSISTIVE_ONLY"


def test_enable_local_ai_does_not_scan_or_mutate_jobs_with_secondary_reporting(make_workspace) -> None:
    """Local AI enablement is global configuration, not a cross-Job compatibility gate."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    job = _create_saw_job(root, secondary="uk")
    before_job = job.manifest_path.read_bytes()

    set_local_admin_enabled(root, True)

    assert job.manifest_path.read_bytes() == before_job
    assert local_ai_policy_status(root)["enabled"] is True
    assert local_ai_policy_status(root)["enablement_blocked"] is False


def test_local_ai_allows_job_secondary_reporting_configuration(make_workspace) -> None:
    """Job reporting can be configured while its external rendering remains a Job-level decision."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    set_local_admin_enabled(root, True)
    store = JobStore(root, root / "ecosystem.yml")

    created = _create_saw_job(root, secondary="uk")
    assert created.secondary_report_language == "uk"

    updated = store.revise_job(created, reporting={"secondary_language": "fr"})
    assert updated.secondary_report_language == "fr"


def test_local_ai_enable_disable_does_not_change_operator_language(make_workspace) -> None:
    """Assistive enablement never rewrites the global Operator reporting language."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    settings = root / "ecosystem.yml"
    before = settings.read_bytes()

    set_local_admin_enabled(root, True)
    set_local_admin_enabled(root, False)

    assert settings.read_bytes() == before


def test_local_transform_rejects_scripture_paths_and_unwhitelisted_capabilities(make_workspace) -> None:
    """Assistive model inputs cannot contain Scripture payload fields or host filesystem paths."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    set_local_admin_enabled(root, True)
    service = LocalTransformService(root)

    with pytest.raises(ValidationError) as scripture:
        service.explain_status({"scripture_text": "In the beginning"})
    assert scripture.value.code == "LOCAL_AI_INPUT_POLICY_VIOLATION"

    with pytest.raises(ValidationError) as path_error:
        service.explain_status({"diagnostic": "/tmp/private/state.json"})
    assert path_error.value.code == "LOCAL_AI_INPUT_POLICY_VIOLATION"

    with pytest.raises(ValidationError) as arbitrary:
        service.explain_status({"message": "arbitrary prose is not a typed controller fact"})
    assert arbitrary.value.code == "LOCAL_AI_INPUT_POLICY_VIOLATION"

    with pytest.raises(ValidationError) as capability:
        service._transform("governed_workflow_execution", {"status": "READY"})
    assert capability.value.code == "LOCAL_AI_CAPABILITY_NOT_ALLOWED"


def test_local_ai_status_uses_one_shared_policy_contract(make_workspace) -> None:
    """Shared UI state exposes the exact normalized Local AI policy used by CLI/menu/TUI."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    set_local_admin_enabled(root, True)

    expected = local_ai_policy_status(root)
    actual = OperatorUIService(root=root, settings_path=root / "ecosystem.yml").runtime_snapshot()["local_ai"]

    assert actual == expected
    assert actual["enabled"] is True
    assert actual["authority"] == "ASSISTIVE_ONLY"
    assert actual["readiness"] == "NOT_PROBED"
    assert actual["reporting_mode"] == "SINGLE_LANGUAGE"
    assert actual["secondary_language_allowed"] is True
    assert actual["enablement_blocked"] is False


def test_local_ai_never_becomes_a_governed_workflow_provider(make_workspace) -> None:
    """The Local AI switch cannot promote Ollama into BIC/SAW execution authority."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    set_local_admin_enabled(root, True)

    assert ENABLED_AUTOMATED_PROVIDER_IDS == ("codex",)
    with pytest.raises(ConfigurationError, match="disabled for automated execution"):
        update_llm_selection(root, provider="ollama")
    assert load_llm_settings(root)["selected_provider"] == "codex"


def test_local_transform_preserves_actions_without_calling_ai(make_workspace) -> None:
    """Administrative explanations are deterministic and preserve controller actions."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    set_local_admin_enabled(root, True)
    service = LocalTransformService(root)

    result = service.explain_diagnostic(
        {"reason_code": "PROJECT_ROOT_MISSING", "status": "ACTION_NEEDED"},
        approved_actions=("CONFIGURE_PROJECT_ROOT",),
    )

    assert result.status == "READY"
    assert result.fallback_used is False
    assert result.action_tokens == ("CONFIGURE_PROJECT_ROOT",)
    assert "CONFIGURE_PROJECT_ROOT" in str(result.text)
    receipt = json.loads(Path(result.receipt_path).read_text(encoding="utf-8"))
    assert receipt["provider"] is None
    assert receipt["label"] == ASSISTIVE_LABEL


def test_report_summary_uses_compact_view_and_separate_artifact(make_workspace, tmp_path: Path) -> None:
    """Report summaries exclude prose evidence and leave the canonical report byte-identical."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    set_local_admin_enabled(root, True)
    service = LocalTransformService(root)
    canonical = tmp_path / "ACTION-REPORT.md"
    canonical.write_text("canonical report bytes\n", encoding="utf-8")
    before = canonical.read_bytes()
    document = {
        "workflow": "saw",
        "operation": "qa",
        "scope": "MAT 1:1",
        "status": "COMPLETE",
        "findings": [
            {
                "finding_id": "F-001",
                "scripture_reference": "MAT 1:1",
                "category": "meaning",
                "risk_level": 4,
                "status": "OPEN",
                "message": "RAW SCRIPTURE OR EVIDENCE MUST NEVER REACH LOCAL AI",
            }
        ],
    }

    view = compact_report_view(document)
    assert "message" not in json.dumps(view)
    destination = service.write_report_executive_summary(canonical, document)

    assert destination is not None and destination.is_file()
    assert canonical.read_bytes() == before
    artifact = json.loads(destination.read_text(encoding="utf-8"))
    assert artifact["label"] == ASSISTIVE_LABEL
    assert artifact["critical_unresolved_ids"] == ["F-001"]
    assert artifact["item_ids"] == ["F-001"]
    assert artifact["summary"] == (
        "SAW qa report for MAT 1:1: 1 finding. Critical unresolved: F-001."
    )


def test_report_summary_does_not_depend_on_local_model(make_workspace, tmp_path: Path) -> None:
    """Deterministic summary publication does not depend on local-model availability."""
    root = make_workspace(configured=True, qualification_status="VALIDATED")
    set_local_admin_enabled(root, True)
    service = LocalTransformService(root)
    canonical = tmp_path / "ACTION-REPORT.md"
    canonical.write_text("canonical\n", encoding="utf-8")
    before = canonical.read_bytes()

    destination = service.write_report_executive_summary(
        canonical,
        {"workflow": "saw", "operation": "qa", "scope": "MAT 1:1", "findings": []},
    )

    assert destination is not None and destination.is_file()
    assert canonical.read_bytes() == before
