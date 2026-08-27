"""Secondary-language SAW report rendering regressions."""

from __future__ import annotations

import json
from pathlib import Path

from sage.storage import storage_layout
from sage.act_outputs import render_action_report
from sage.executors.base import ProviderResponse
from sage.llm_settings import LOCAL_AI_EXTERNAL_RENDERING_REQUIRED, set_local_admin_enabled
from sage.report_translation import ensure_secondary_saw_report_rendering


def _document() -> dict:
    """Return one canonical SAW finding document configured for EN + UK reporting."""
    return {
        "schema_version": "2.0",
        "task_id": "SAW-RUT-001",
        "operation": "rtc",
        "stage": "COMPOSITE_FINALIZED",
        "scope": "RUT",
        "resource_bindings": {"WIP": "ukrNPUv1", "REFERENCE": "usNIVv2"},
        "coverage": {"status": "COMPLETE", "reviewed_references": ["RUT 1:1"]},
        "findings": [
            {
                "finding_id": "SAW-RUT-001-0001",
                "target_reference": "RUT 1:1",
                "category": "MEANING",
                "issue": "The wording adds a temporary-residence qualification not expressed in the reference.",
                "required_action": "Remove the added temporary qualification.",
                "action_level": "CHANGE",
                "confidence": "HIGH",
                "evidence_ids": ["REFERENCE", "WIP"],
                "grammar_rule_ids": [],
                "original_language_evidence": "",
            }
        ],
        "language_authority": {
            "schema_version": "1.0",
            "primary_language": "en",
            "primary_authority": "GOVERNING_HUMAN_RENDERING",
            "primary_confidence": "BASELINE_NOT_CORRECTNESS_GUARANTEE",
            "secondary_language": "uk",
            "secondary_authority": "ASSISTIVE_TRANSLATION_ONLY",
            "secondary_confidence": "LOWER_UNVERIFIED_TRANSLATION_CONFIDENCE",
            "secondary_generation_cost": "ADDITIONAL_MODEL_USAGE_AND_COMPILATION_TIME",
            "secondary_review_requirement": "GREATER_THAN_SINGLE_LANGUAGE_REPORT",
            "canonical_machine_evidence": "AUTHORITATIVE",
        },
    }


def test_saw_bilingual_report_generates_and_reuses_ukrainian_rendering(tmp_path: Path, monkeypatch) -> None:
    """Verify one provider pass supplies UK prose and its receipt is reused."""
    calls = []

    class FakeExecutor:
        """Return one deterministic secondary rendering without external execution."""

        def execute(self, request):
            """Return the fixed provider payload used by this regression."""
            calls.append(request)
            return ProviderResponse(
                provider="codex",
                model="gpt-test",
                reasoning_effort="medium",
                content=json.dumps(
                    {
                        "schema_version": "1.0",
                        "secondary_language": "uk",
                        "findings": [
                            {
                                "finding_id": "SAW-RUT-001-0001",
                                "issue": "Формулювання додає ознаку тимчасового проживання, якої немає в референсі.",
                                "required_action": "Приберіть додану ознаку тимчасовості.",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            )

    monkeypatch.setattr("sage.report_translation.make_executor", lambda provider, settings: FakeExecutor())
    sage_root = tmp_path / "SAGE" / "app"
    sage_root.mkdir(parents=True)
    report_path = tmp_path / "RUT_ACTION-REPORT.md"
    rendered = ensure_secondary_saw_report_rendering(sage_root, report_path, _document())
    assert rendered["report_renderings"]["status"] == "AVAILABLE"
    report = render_action_report(rendered)
    assert "SAW Action Report / Звіт SAW про необхідні дії" in report
    assert "**Issue — English**" in report
    assert "temporary-residence qualification" in report
    assert "**Issue — Ukrainian**" in report
    assert "ознаку тимчасового проживання" in report
    assert "**Proposed action — English**" in report
    assert "**Proposed action — Ukrainian**" in report
    assert "Приберіть додану ознаку тимчасовості." in report
    assert "usNIVv2" in calls[0].prompt
    assert "not expressed in the reference" not in calls[0].prompt
    assert report.index("**Issue — English**") < report.index("**Proposed action — English**")
    assert report.index("**Proposed action — English**") < report.index("**Issue — Ukrainian**")
    assert report.index("**Issue — Ukrainian**") < report.index("**Proposed action — Ukrainian**")
    assert len(calls) == 1

    cached = ensure_secondary_saw_report_rendering(sage_root, report_path, _document())
    assert cached["report_renderings"]["status"] == "AVAILABLE"
    assert len(calls) == 1
    receipt = storage_layout(sage_root).diagnostics_root / "report-renderings" / "RUT_ACTION-REPORT-SECONDARY-RENDERING.json"
    assert receipt.is_file()


def test_secondary_rendering_failure_is_visible_without_invalidating_primary_report(tmp_path: Path, monkeypatch) -> None:
    """Verify secondary-rendering failure is visible while primary findings remain usable."""

    class FailingExecutor:
        """Raise the expected provider failure for degraded-report coverage."""

        def execute(self, request):
            """Raise a governed provider failure."""
            from sage.errors import ValidationError
            raise ValidationError("provider unavailable", code="LLM_PROVIDER_EXECUTION_FAILED")

    monkeypatch.setattr("sage.report_translation.make_executor", lambda provider, settings: FailingExecutor())
    sage_root = tmp_path / "SAGE" / "app"
    sage_root.mkdir(parents=True)
    report_path = tmp_path / "RUT_ACTION-REPORT.md"
    rendered = ensure_secondary_saw_report_rendering(sage_root, report_path, _document())
    assert rendered["report_renderings"]["status"] == "DEGRADED"
    report = render_action_report(rendered)
    assert "Secondary report rendering is unavailable" in report
    assert "Вторинний переклад звіту недоступний" in report
    assert "temporary-residence qualification" in report


def test_local_ai_rejects_only_job_external_rendering_and_preserves_primary_report(
    tmp_path: Path, monkeypatch
) -> None:
    """Local AI does not block basic work; only the Job's Hosted-AI rendering is rejected."""
    sage_root = tmp_path / "SAGE" / "app"
    sage_root.mkdir(parents=True)
    set_local_admin_enabled(sage_root, True)
    monkeypatch.setattr(
        "sage.report_translation.make_executor",
        lambda provider, settings: (_ for _ in ()).throw(AssertionError("must not invoke Hosted AI")),
    )

    rendered = ensure_secondary_saw_report_rendering(
        sage_root, tmp_path / "RUT_ACTION-REPORT.md", _document()
    )

    rendering = rendered["report_renderings"]
    assert rendering["status"] == "DEGRADED"
    assert rendering["reason_code"] == LOCAL_AI_EXTERNAL_RENDERING_REQUIRED
    assert "rejected for this Job" in rendering["diagnostic"]
    report = render_action_report(rendered)
    assert "temporary-residence qualification" in report
    assert "Secondary report rendering is unavailable" in report


def test_monolingual_report_does_not_invoke_translation(tmp_path: Path, monkeypatch) -> None:
    """Verify single-language reports never invoke the secondary-rendering provider."""
    document = _document()
    document.pop("language_authority")
    monkeypatch.setattr(
        "sage.report_translation.make_executor",
        lambda provider, settings: (_ for _ in ()).throw(AssertionError("must not invoke provider")),
    )
    sage_root = tmp_path / "SAGE" / "app"
    sage_root.mkdir(parents=True)
    rendered = ensure_secondary_saw_report_rendering(sage_root, tmp_path / "RUT.md", document)
    assert "report_renderings" not in rendered
