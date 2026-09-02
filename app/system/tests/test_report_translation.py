"""Secondary-language SAW report rendering regressions."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from sage.storage import storage_layout
from sage.act_outputs import render_action_report
from sage.executors.base import (
    ModelCapability,
    ProviderResponse,
    ProviderStatus,
    ReasoningEffortOption,
)
from sage.llm_settings import LOCAL_AI_EXTERNAL_RENDERING_REQUIRED, set_local_admin_enabled
from sage.report_translation import ensure_secondary_saw_report_rendering
from sage.skill_routing import capability_fingerprint, resolve_skill_route
from sage.stc_reporting import _stc_report_markdown


def _workspace_with_uk_profile(package_root: Path, make_workspace) -> Path:
    """Return a fixture with explicit canonical EN and UK reporting LANGUAGE_PROFILE namespaces."""
    root = make_workspace(qualification_status="VALIDATED")
    uk_target = root / "system/config/profiles/grammar/uk-UA/wip.yml"
    uk_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(package_root / "system/config/profiles/grammar/uk-UA/wip.yml", uk_target)
    settings_path = root / "ecosystem.yml"
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    settings["language_profiles"]["uk-UA"] = {
        "script": "Cyrl",
        "variants": {
            "wip": {
                "file": "system/config/profiles/grammar/uk-UA/wip.yml",
                "role": "WIP",
            }
        },
    }
    settings["language_profiles"]["uk"] = {
        "script": "Cyrl",
        "profile_alias": "uk-UA",
    }
    settings_path.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
    return root


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


def _translation_status() -> ProviderStatus:
    """Return one deterministic live route for secondary-rendering tests."""
    capability = ModelCapability(
        id="gpt-test",
        model="gpt-test",
        display_name="GPT Test",
        supported_reasoning_efforts=(ReasoningEffortOption("medium"),),
        default_reasoning_effort="medium",
    )
    return ProviderStatus(
        provider="codex",
        available=True,
        ready=True,
        model_capabilities=(capability,),
        models=(capability.model,),
    )


def _bind_execution_route(root: Path, document: dict) -> dict:
    """Qualify and attach the originating exact SAW RTC route to a report fixture."""
    status = _translation_status()
    capability = status.model_capabilities[0]
    policy = yaml.safe_load((root / "system/config/model-policy.yml").read_text(encoding="utf-8"))
    skills = json.loads((root / "system/config/skills.json").read_text(encoding="utf-8"))
    route_policy = policy["skill_routes"]["saw-rtc"]
    seeds = {
        "schema_version": "1.0",
        "routes": [
            {
                "provider": "codex",
                "model_id": capability.model,
                "capability_fingerprint": capability_fingerprint(capability),
                "reasoning_id": "medium",
                "skill_id": "saw-rtc",
                "skill_sha256": skills["skills"]["saw-rtc"]["adapted_sha256"],
                "suite_id": route_policy["suite_id"],
                "suite_sha256": route_policy["suite_sha256"],
                "policy_version": policy["qualification_policy_version"],
                "qualification_status": "QUALIFIED",
                "evidence_sha256": "a" * 64,
                "cost_class": capability.cost_class,
                "semantic_score": 1.0,
                "semantic_score_material": False,
            }
        ],
    }
    (root / "system/config/model-qualification-seeds.json").write_text(
        json.dumps(seeds, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    document["execution_route"] = resolve_skill_route(
        root, "saw-rtc", [status]
    ).to_dict()
    return document


def test_saw_bilingual_report_generates_and_reuses_ukrainian_rendering(
    tmp_path: Path,
    monkeypatch,
    package_root: Path,
    make_workspace,
) -> None:
    """Verify one provider pass supplies UK prose and its receipt is reused."""
    calls = []

    class FakeExecutor:
        """Return one deterministic secondary rendering without external execution."""

        def status(self):
            """Return the live identity inherited from the report's source task."""
            return _translation_status()

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
                        "events": [],
                    },
                    ensure_ascii=False,
                ),
            )

    monkeypatch.setattr("sage.report_translation.make_executor", lambda provider, settings: FakeExecutor())
    sage_root = _workspace_with_uk_profile(package_root, make_workspace)
    report_path = tmp_path / "RUT_ACTION-REPORT.md"
    document = _bind_execution_route(sage_root, _document())
    rendered = ensure_secondary_saw_report_rendering(sage_root, report_path, document)
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
    assert "BOL-TARGET-001" in calls[0].prompt
    assert "UKUA-GR-001" in calls[0].prompt
    assert report.index("**Issue — English**") < report.index("**Proposed action — English**")
    assert report.index("**Proposed action — English**") < report.index("**Issue — Ukrainian**")
    assert report.index("**Issue — Ukrainian**") < report.index("**Proposed action — Ukrainian**")
    assert len(calls) == 1
    assert calls[0].model == "gpt-test"
    assert calls[0].reasoning_effort == "medium"
    assert rendered["report_renderings"]["execution_routes"]["report"] == document["execution_route"]
    assert set(rendered["report_renderings"]["linguistic_profile_bindings"]) == {
        "REPORT:PRIMARY",
        "REPORT:SECONDARY",
    }

    cached = ensure_secondary_saw_report_rendering(sage_root, report_path, document)
    assert cached["report_renderings"]["status"] == "AVAILABLE"
    assert len(calls) == 1
    receipt = storage_layout(sage_root).diagnostics_root / "report-renderings" / "RUT_ACTION-REPORT-SECONDARY-RENDERING.json"
    assert receipt.is_file()


def test_secondary_rendering_sends_exactly_one_report_item_per_provider_request(
    tmp_path: Path,
    monkeypatch,
    package_root: Path,
    make_workspace,
) -> None:
    """Findings and events are isolated, then assembled by the Python controller."""
    document = _document()
    document["findings"].append(
        {
            "finding_id": "SAW-RUT-001-0002",
            "target_reference": "RUT 1:1",
            "category": "CONSISTENCY",
            "issue": "A second independent report item.",
            "required_action": "Review the second item.",
            "action_level": "REVIEW",
            "confidence": "MEDIUM",
            "evidence_ids": ["REFERENCE", "WIP"],
            "grammar_rule_ids": [],
            "original_language_evidence": "",
        }
    )
    document["execution_events"] = [
        {
            "event_id": "EVT-001",
            "message": "One controller-recorded execution event.",
            "next_action": "Inspect its diagnostic.",
        }
    ]
    calls = []

    class FakeExecutor:
        """Render the exact schema-enumerated item for each isolated request."""

        def status(self):
            """Return the live identity inherited from every report item."""
            return _translation_status()

        def execute(self, request):
            """Return one translation for the single schema-enumerated report item."""
            calls.append(request)
            properties = request.schema["properties"]
            finding_ids = properties["findings"]["items"]["properties"]["finding_id"]["enum"]
            event_ids = properties["events"]["items"]["properties"]["event_id"]["enum"]
            findings = [
                {
                    "finding_id": finding_id,
                    "issue": f"UK issue for {finding_id}",
                    "required_action": f"UK action for {finding_id}",
                }
                for finding_id in finding_ids
            ]
            events = [
                {
                    "event_id": event_id,
                    "message": f"UK message for {event_id}",
                    "next_action": f"UK action for {event_id}",
                }
                for event_id in event_ids
            ]
            return ProviderResponse(
                provider="codex",
                model="gpt-test",
                reasoning_effort="medium",
                content=json.dumps(
                    {
                        "schema_version": "1.0",
                        "secondary_language": "uk",
                        "findings": findings,
                        "events": events,
                    }
                ),
            )

    monkeypatch.setattr("sage.report_translation.make_executor", lambda provider, settings: FakeExecutor())
    sage_root = _workspace_with_uk_profile(package_root, make_workspace)
    document = _bind_execution_route(sage_root, document)
    rendered = ensure_secondary_saw_report_rendering(
        sage_root,
        tmp_path / "RUT_ACTION-REPORT.md",
        document,
    )

    assert len(calls) == 3
    assert all(
        request.schema["properties"]["findings"]["maxItems"]
        + request.schema["properties"]["events"]["maxItems"]
        == 1
        for request in calls
    )
    assert [
        sum(identifier in request.prompt for request in calls)
        for identifier in ["SAW-RUT-001-0001", "SAW-RUT-001-0002", "EVT-001"]
    ] == [1, 1, 1]
    receipt = rendered["report_renderings"]
    assert receipt["status"] == "AVAILABLE"
    assert receipt["rendering_unit"] == "ONE_REPORT_ITEM_PER_PROVIDER_REQUEST"
    assert receipt["provider_request_count"] == 3
    assert set(receipt["findings"]) == {"SAW-RUT-001-0001", "SAW-RUT-001-0002"}
    assert set(receipt["events"]) == {"EVT-001"}


def test_stc_summaries_use_the_provisional_originating_route_one_at_a_time(
    tmp_path: Path,
    monkeypatch,
    package_root: Path,
    make_workspace,
) -> None:
    """Catch STC summaries being rejected before their one-item translation calls."""
    summaries = {
        "STC-JON-001": "The WIP contains an added verse at JON 1:17.",
        "STC-JON-002": "The WIP wording requires a correspondence review.",
    }
    ukrainian = {
        "STC-JON-001": "Робочий переклад містить доданий вірш у Йони 1:17.",
        "STC-JON-002": "Формулювання робочого перекладу потребує перевірки відповідності.",
    }
    document = _document()
    document.update(
        {
            "operation": "stc",
            "authority_family": "HEB",
            "resource_bindings": {
                "WIP": "ukrNPUv1",
                "ORIGINAL_LANGUAGE_HEBREW": "HEB",
            },
            "primary_coverage": ["JON 1:17"],
            "source_comparison_status": "COMPLETE",
            "findings": [
                {
                    "finding_id": finding_id,
                    "target_reference": "JON 1:17",
                    "category": "CORRESPONDENCE",
                    "summary": summary,
                    "issue": summary,
                    "required_action": "",
                    "wip_evidence": "WIP evidence",
                    "ol_evidence": "HEB evidence",
                    "evidence_ids": ["WIP", "ORIGINAL_LANGUAGE_HEBREW"],
                }
                for finding_id, summary in summaries.items()
            ],
        }
    )
    document["language_authority"]["secondary_language"] = "uk-UA"
    calls = []

    class FakeExecutor:
        """Render each isolated STC Summary through its originating route."""

        def status(self):
            """Return the same live capability used by the provisional STC route."""
            return _translation_status()

        def execute(self, request):
            """Return Ukrainian text for the one schema-enumerated Summary."""
            calls.append(request)
            finding_ids = request.schema["properties"]["findings"]["items"]["properties"]["finding_id"]["enum"]
            assert len(finding_ids) == 1
            finding_id = finding_ids[0]
            return ProviderResponse(
                provider="codex",
                model="gpt-test",
                reasoning_effort="medium",
                content=json.dumps(
                    {
                        "schema_version": "1.0",
                        "secondary_language": "uk-UA",
                        "findings": [
                            {
                                "finding_id": finding_id,
                                "issue": ukrainian[finding_id],
                                "required_action": "",
                            }
                        ],
                        "events": [],
                    },
                    ensure_ascii=False,
                ),
            )

    monkeypatch.setattr(
        "sage.report_translation.make_executor",
        lambda provider, settings: FakeExecutor(),
    )
    sage_root = _workspace_with_uk_profile(package_root, make_workspace)
    route = resolve_skill_route(sage_root, "saw-stc", [_translation_status()])
    assert route.qualification == "PROVISIONAL_UNQUALIFIED"
    document["execution_route"] = route.to_dict()

    rendered = ensure_secondary_saw_report_rendering(
        sage_root,
        tmp_path / "STC-JON_ACTION-REPORT.md",
        document,
    )

    assert rendered["report_renderings"]["status"] == "AVAILABLE"
    assert len(calls) == 2
    assert [
        sum(summary in request.prompt for request in calls)
        for summary in (
            "The ukrNPUv1 contains an added verse at JON 1:17.",
            "The ukrNPUv1 wording requires a correspondence review.",
        )
    ] == [1, 1]
    report = _stc_report_markdown(rendered)
    assert "**Summary — uk-UA**\n\n" + ukrainian["STC-JON-001"] in report
    assert "**Summary — uk-UA**\n\n" + ukrainian["STC-JON-002"] in report
    assert "Secondary report rendering is unavailable" not in report


def test_tampered_provisional_route_projection_degrades_before_execution(
    tmp_path: Path,
    monkeypatch,
    package_root: Path,
    make_workspace,
) -> None:
    """Catch projected route fields disagreeing with their retained route ID."""
    calls = []

    class FakeExecutor:
        """Expose the current provisional route and record improper execution."""

        def status(self):
            """Return the unchanged live capability behind the original route ID."""
            return _translation_status()

        def execute(self, request):
            """Return a valid payload so only route-integrity checks decide the result."""
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
                                "issue": "Український виклад питання.",
                                "required_action": "Український виклад дії.",
                            }
                        ],
                        "events": [],
                    },
                    ensure_ascii=False,
                ),
            )

    monkeypatch.setattr(
        "sage.report_translation.make_executor",
        lambda provider, settings: FakeExecutor(),
    )
    sage_root = _workspace_with_uk_profile(package_root, make_workspace)
    route = resolve_skill_route(sage_root, "saw-stc", [_translation_status()])
    assert route.qualification == "PROVISIONAL_UNQUALIFIED"
    document = _document()
    document["execution_route"] = route.to_dict()
    document["execution_route"]["capability_fingerprint"] = "f" * 64

    rendered = ensure_secondary_saw_report_rendering(
        sage_root,
        tmp_path / "TAMPERED_ACTION-REPORT.md",
        document,
    )

    assert rendered["report_renderings"]["status"] == "DEGRADED"
    assert (
        rendered["report_renderings"]["reason_code"]
        == "SECONDARY_REPORT_ROUTE_UNAVAILABLE"
    )
    assert calls == []


def test_secondary_rendering_without_originating_route_degrades_before_provider(
    tmp_path: Path, monkeypatch, package_root: Path, make_workspace
) -> None:
    """A report item without execution provenance cannot silently select another route."""
    sage_root = _workspace_with_uk_profile(package_root, make_workspace)
    monkeypatch.setattr(
        "sage.report_translation.make_executor",
        lambda provider, settings: (_ for _ in ()).throw(
            AssertionError("missing route must degrade before provider discovery")
        ),
    )
    rendered = ensure_secondary_saw_report_rendering(
        sage_root,
        tmp_path / "RUT_ACTION-REPORT.md",
        _document(),
    )
    assert rendered["report_renderings"]["status"] == "DEGRADED"
    assert rendered["report_renderings"]["reason_code"] == "SECONDARY_REPORT_ROUTE_MISSING"


def test_secondary_rendering_stale_originating_route_degrades_without_execution(
    tmp_path: Path, monkeypatch, package_root: Path, make_workspace
) -> None:
    """A changed route identity cannot be replaced during assistive rendering."""
    sage_root = _workspace_with_uk_profile(package_root, make_workspace)
    document = _bind_execution_route(sage_root, _document())
    document["execution_route"]["capability_fingerprint"] = "f" * 64

    class FakeExecutor:
        """Permit capability probing but reject secondary task execution."""

        def status(self):
            """Return the current capability identity."""
            return _translation_status()

        def execute(self, _request):
            """Fail if a stale originating route is substituted."""
            raise AssertionError("stale report route must not execute")

    monkeypatch.setattr("sage.report_translation.make_executor", lambda provider, settings: FakeExecutor())
    rendered = ensure_secondary_saw_report_rendering(
        sage_root,
        tmp_path / "RUT_ACTION-REPORT.md",
        document,
    )
    assert rendered["report_renderings"]["status"] == "DEGRADED"
    assert rendered["report_renderings"]["reason_code"] == "SECONDARY_REPORT_ROUTE_UNAVAILABLE"


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
    tmp_path: Path, monkeypatch, package_root: Path, make_workspace
) -> None:
    """Local AI does not block basic work; only the Job's Hosted-AI rendering is rejected."""
    sage_root = _workspace_with_uk_profile(package_root, make_workspace)
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
