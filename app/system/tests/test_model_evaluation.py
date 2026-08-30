"""Sealed per-Skill model qualification suite and deterministic receipt tests."""

from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sage.executors.base import ModelCapability, ProviderResponse, ProviderStatus, ReasoningEffortOption


EXPECTED_CASES = {
    "bic-inspect": ["seeded-material-issue", "clean-source", "forged-evidence"],
    "bic-rewrite": ["authorized-challenges", "no-change-required", "scope-expansion"],
    "bic-self-check": ["detect-regression", "approve-clean", "blocking-regression"],
    "saw-rtc": [
        "seeded-variance",
        "aligned-pair",
        "false-ol-referral",
        "fundamental-polarity",
        "participant-identity",
    ],
    "saw-stc": ["seeded-correspondence", "complete-no-finding", "reference-contamination"],
    "saw-focused-check": ["bounded-answer", "bounded-zero-result", "question-expansion"],
    "saw-original-language-review": [
        "greek-single-item",
        "hebrew-no-change",
        "multi-item-contamination",
    ],
}


def _evaluation_module():
    """Load the evaluation API after proving that its production module exists."""
    assert importlib.util.find_spec("sage.model_evaluation") is not None
    return importlib.import_module("sage.model_evaluation")


def test_contract_inventory_has_exact_registered_cases_per_skill(package_root: Path) -> None:
    """Each sealed Skill suite must match its explicit semantic case inventory."""
    path = package_root / "system/config/skill-evaluation-contracts.json"
    assert path.is_file()
    contracts = json.loads(path.read_text(encoding="utf-8"))

    assert set(contracts["skills"]) == set(EXPECTED_CASES)
    assert {
        skill_id: [row["case_id"] for row in contracts["skills"][skill_id]["cases"]]
        for skill_id in EXPECTED_CASES
    } == EXPECTED_CASES
    assert all(
        contracts["skills"][skill_id]["repetitions_per_case"] == 3
        for skill_id in EXPECTED_CASES
    )
    for skill_id, case_ids in EXPECTED_CASES.items():
        for case_id in case_ids:
            manifest = json.loads(
                (
                    package_root
                    / "system/evaluations/model-routing-alpha1"
                    / skill_id
                    / case_id
                    / "task-manifest.json"
                ).read_text(encoding="utf-8")
            )
            assert manifest["maximum_review_items_per_request"] == 1


def test_case_builder_verifies_the_committed_sealed_bundles(package_root: Path) -> None:
    """Regeneration in a temporary directory must byte-match every committed case artifact."""
    tool = package_root / "system/tools/build_model_evaluation_cases.py"
    result = subprocess.run(
        [sys.executable, str(tool), "--verify"],
        cwd=package_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "PASS"
    assert payload["skill_count"] == 7
    assert payload["case_count"] == 23


class PassingTransport:
    """Return each sealed case's independently committed passing response fixture."""

    def __init__(self) -> None:
        """Track exact case/repetition isolation."""
        self.calls: list[tuple[str, int]] = []

    def status(self) -> ProviderStatus:
        """Expose one complete live capability identity."""
        capability = ModelCapability(
            id="gpt-evaluation-fixture",
            model="gpt-evaluation-fixture",
            display_name="Evaluation Fixture",
            supported_reasoning_efforts=(ReasoningEffortOption("careful"),),
            default_reasoning_effort="careful",
            identity_strength="IMMUTABLE",
            cost_class="STANDARD",
        )
        return ProviderStatus(
            provider="fixture",
            available=True,
            ready=True,
            version="1.0.0",
            model_capabilities=(capability,),
            diagnostic="ready",
        )

    def execute(self, case: dict[str, object], repetition: int) -> ProviderResponse:
        """Return the sealed passing response without rating or qualifying it."""
        self.calls.append((str(case["case_id"]), repetition))
        response = dict(case["expected"]["passing_response"])  # type: ignore[index]
        return ProviderResponse(
            provider="fixture",
            model="gpt-evaluation-fixture",
            reasoning_effort="careful",
            content=json.dumps(response),
            metadata={"fixture": True},
        )


class NativeReasoningTransport:
    """Exercise one provider-native reasoning candidate with deterministic fixture output."""

    def __init__(
        self,
        status: ProviderStatus,
        *,
        model_id: str,
        reasoning_id: str,
        qualifies: bool,
    ) -> None:
        """Bind one candidate and whether its semantic responses satisfy the sealed cases."""
        self._status = status
        self.model_id = model_id
        self.reasoning_id = reasoning_id
        self.qualifies = qualifies

    def status(self) -> ProviderStatus:
        """Return the shared provider-native catalog snapshot."""
        return self._status

    def execute(self, case: dict[str, object], repetition: int) -> ProviderResponse:
        """Return an exact response or a bounded semantic miss for this candidate."""
        del repetition
        response = dict(case["expected"]["passing_response"])  # type: ignore[index]
        if not self.qualifies:
            response["decision"] = "SEMANTIC_MISS"
        return ProviderResponse(
            provider=self._status.provider,
            model=self.model_id,
            reasoning_effort=(
                None if self.reasoning_id == "provider-default" else self.reasoning_id
            ),
            content=json.dumps(response),
            metadata={"fixture": True},
        )


def _native_status(*, provider: str = "fixture-native") -> ProviderStatus:
    """Return two future-provider models with provider-owned reasoning identifiers."""
    return ProviderStatus(
        provider=provider,
        available=True,
        ready=True,
        version="native-1.0",
        model_capabilities=(
            ModelCapability(
                id="model-a",
                model="model-a",
                display_name="Model A",
                supported_reasoning_efforts=tuple(
                    ReasoningEffortOption(value) for value in ("swift", "careful", "deep-native")
                ),
                default_reasoning_effort="careful",
                identity_strength="IMMUTABLE",
                cost_class="STANDARD",
            ),
            ModelCapability(
                id="model-b",
                model="model-b",
                display_name="Model B",
                supported_reasoning_efforts=(),
                default_reasoning_effort=None,
                identity_strength="IMMUTABLE",
                cost_class="STANDARD",
            ),
        ),
        diagnostic="ready",
    )


def test_model_evaluation_progresses_native_reasoning_and_stops_at_first_qualified(
    package_root: Path,
) -> None:
    """One model/Skill evaluation must preserve native order and stop at least sufficient effort."""
    evaluation = _evaluation_module()
    status = _native_status()
    created: list[str] = []

    def factory(model_id: str, reasoning_id: str):
        """Make the lower candidate miss and the next native candidate qualify."""
        created.append(reasoning_id)
        return NativeReasoningTransport(
            status,
            model_id=model_id,
            reasoning_id=reasoning_id,
            qualifies=reasoning_id == "careful",
        )

    result = evaluation.evaluate_model_for_skill(
        package_root,
        skill_id="saw-rtc",
        provider=status.provider,
        model_id="model-a",
        status=status,
        transport_factory=factory,
    )

    assert created == ["swift", "careful"]
    assert result["status"] == "QUALIFIED"
    assert result["evaluated_reasoning_ids"] == ["swift", "careful"]
    assert result["selected_route"]["reasoning_id"] == "careful"
    assert result["stopped_after_first_qualified"] is True


def test_model_evaluation_comparison_runs_every_native_reasoning_setting(
    package_root: Path,
) -> None:
    """Explicit comparison mode may continue after the first passing native setting."""
    evaluation = _evaluation_module()
    status = _native_status(provider="fixture-comparison")
    created: list[str] = []

    def factory(model_id: str, reasoning_id: str):
        """Qualify every candidate while recording provider order."""
        created.append(reasoning_id)
        return NativeReasoningTransport(
            status,
            model_id=model_id,
            reasoning_id=reasoning_id,
            qualifies=True,
        )

    result = evaluation.evaluate_model_for_skill(
        package_root,
        skill_id="bic-inspect",
        provider=status.provider,
        model_id="model-a",
        comparison=True,
        status=status,
        transport_factory=factory,
    )

    assert created == ["swift", "careful", "deep-native"]
    assert result["selected_route"]["reasoning_id"] == "swift"
    assert result["stopped_after_first_qualified"] is False


def test_catalog_evaluation_handles_provider_default_and_recommends_per_skill(
    package_root: Path,
) -> None:
    """Catalog orchestration evaluates chosen models and returns one deterministic Skill route."""
    evaluation = _evaluation_module()
    status = _native_status(provider="fixture-catalog")

    def factory(model_id: str, reasoning_id: str):
        """Qualify only the model that exposes provider-default reasoning."""
        return NativeReasoningTransport(
            status,
            model_id=model_id,
            reasoning_id=reasoning_id,
            qualifies=model_id == "model-b",
        )

    result = evaluation.evaluate_catalog(
        package_root,
        provider=status.provider,
        skill_ids=["saw-focused-check"],
        model_ids=["model-a", "model-b"],
        status=status,
        transport_factory=factory,
    )

    assert result["status"] == "COMPLETE"
    assert result["candidate_count"] == 2
    skill = result["skills"][0]
    assert skill["qualification_status"] == "QUALIFIED"
    assert skill["recommended_route"]["model_id"] == "model-b"
    assert skill["recommended_route"]["reasoning_id"] == "provider-default"


def test_evaluation_rejects_response_route_metadata_mismatch(package_root: Path) -> None:
    """A response from another provider/model/reasoning route cannot qualify the candidate."""
    evaluation = _evaluation_module()

    class WrongRouteTransport(PassingTransport):
        """Return passing content with contradictory provider metadata."""

        def execute(self, case: dict[str, object], repetition: int) -> ProviderResponse:
            """Preserve content but forge the provider identity."""
            response = super().execute(case, repetition)
            return ProviderResponse(
                provider="another-provider",
                model=response.model,
                reasoning_effort=response.reasoning_effort,
                content=response.content,
                metadata=response.metadata,
            )

    receipt = evaluation.evaluate_candidate(
        package_root,
        skill_id="saw-rtc",
        provider="fixture",
        model_id="gpt-evaluation-fixture",
        reasoning_id="careful",
        transport=WrongRouteTransport(),
    )

    assert receipt["qualification_status"] == "FAILED"
    assert receipt["hard_failure_count"] == 15
    assert all(
        "provider identity" in row["hard_errors"][0].lower()
        for row in receipt["attempts"]
    )


def test_evaluation_rejects_missing_exact_route_metadata(package_root: Path) -> None:
    """Qualification evidence cannot omit the evaluated model or native reasoning identity."""
    evaluation = _evaluation_module()

    class MissingRouteTransport(PassingTransport):
        """Return passing content without model/reasoning response metadata."""

        def execute(self, case: dict[str, object], repetition: int) -> ProviderResponse:
            """Preserve content while omitting two required route identities."""
            response = super().execute(case, repetition)
            return ProviderResponse(
                provider=response.provider,
                model=None,
                reasoning_effort=None,
                content=response.content,
                metadata=response.metadata,
            )

    receipt = evaluation.evaluate_candidate(
        package_root,
        skill_id="saw-rtc",
        provider="fixture",
        model_id="gpt-evaluation-fixture",
        reasoning_id="careful",
        transport=MissingRouteTransport(),
    )

    assert receipt["qualification_status"] == "FAILED"
    assert receipt["hard_failure_count"] == 15
    assert all(
        {"Model identity differs from the evaluated route", "Reasoning identity differs from the evaluated route"}
        <= set(row["hard_errors"])
        for row in receipt["attempts"]
    )


def test_all_three_repetitions_of_all_cases_are_required_for_qualification(
    package_root: Path,
) -> None:
    """A passing candidate must complete nine isolated attempts before qualification."""
    evaluation = _evaluation_module()
    transport = PassingTransport()

    receipt = evaluation.evaluate_candidate(
        package_root,
        skill_id="saw-original-language-review",
        provider="fixture",
        model_id="gpt-evaluation-fixture",
        reasoning_id="careful",
        transport=transport,
    )

    assert receipt["qualification_status"] == "QUALIFIED"
    assert receipt["case_count"] == 3
    assert receipt["attempt_count"] == 9
    assert len(transport.calls) == 9
    assert all(count == 3 for count in {
        case_id: sum(1 for called, _rep in transport.calls if called == case_id)
        for case_id in EXPECTED_CASES["saw-original-language-review"]
    }.values())


def test_one_hard_contract_failure_marks_candidate_failed(package_root: Path) -> None:
    """A prohibited action in one repetition must disqualify the complete route."""
    evaluation = _evaluation_module()

    class FailingTransport(PassingTransport):
        """Inject one deterministic governance failure into an otherwise passing suite."""

        def execute(self, case: dict[str, object], repetition: int) -> ProviderResponse:
            """Add one prohibited action to the first positive attempt."""
            response = json.loads(super().execute(case, repetition).content)
            if len(self.calls) == 1:
                response["prohibited_actions"] = ["EXPANDED_SCOPE"]
            return ProviderResponse(
                "fixture",
                "gpt-evaluation-fixture",
                json.dumps(response),
                {"fixture": True},
                "careful",
            )

    receipt = evaluation.evaluate_candidate(
        package_root,
        skill_id="saw-focused-check",
        provider="fixture",
        model_id="gpt-evaluation-fixture",
        reasoning_id="careful",
        transport=FailingTransport(),
    )

    assert receipt["qualification_status"] == "FAILED"
    assert receipt["hard_failure_count"] == 1


def test_mixed_semantic_repetitions_mark_candidate_unreliable(package_root: Path) -> None:
    """A non-hard semantic miss in one repetition must produce UNRELIABLE, never QUALIFIED."""
    evaluation = _evaluation_module()

    class InconsistentTransport(PassingTransport):
        """Return one wrong semantic decision without violating a hard boundary."""

        def execute(self, case: dict[str, object], repetition: int) -> ProviderResponse:
            """Change the expected decision on one middle repetition."""
            response = json.loads(super().execute(case, repetition).content)
            if len(self.calls) == 2:
                response["decision"] = "SEMANTIC_MISS"
            return ProviderResponse(
                "fixture",
                "gpt-evaluation-fixture",
                json.dumps(response),
                {"fixture": True},
                "careful",
            )

    receipt = evaluation.evaluate_candidate(
        package_root,
        skill_id="saw-rtc",
        provider="fixture",
        model_id="gpt-evaluation-fixture",
        reasoning_id="careful",
        transport=InconsistentTransport(),
    )

    assert receipt["qualification_status"] == "UNRELIABLE"
    assert receipt["semantic_failure_count"] == 1


def test_ol_case_validator_rejects_more_than_one_review_item(package_root: Path) -> None:
    """Original-language qualification must prove exactly one-item request isolation."""
    evaluation = _evaluation_module()

    class ContaminatedTransport(PassingTransport):
        """Add a second review item to the first OL response."""

        def execute(self, case: dict[str, object], repetition: int) -> ProviderResponse:
            """Duplicate the sealed review item once."""
            response = json.loads(super().execute(case, repetition).content)
            if len(self.calls) == 1:
                response["reviewed_item_ids"].append("ITEM-EXTRA")
            return ProviderResponse(
                "fixture",
                "gpt-evaluation-fixture",
                json.dumps(response),
                {"fixture": True},
                "careful",
            )

    receipt = evaluation.evaluate_candidate(
        package_root,
        skill_id="saw-original-language-review",
        provider="fixture",
        model_id="gpt-evaluation-fixture",
        reasoning_id="careful",
        transport=ContaminatedTransport(),
    )

    assert receipt["qualification_status"] == "FAILED"
    assert any(
        "exactly one reviewed item" in error
        for attempt in receipt["attempts"]
        for error in attempt["hard_errors"]
    )


def test_receipt_reconciliation_detects_evidence_tampering(package_root: Path) -> None:
    """A changed local receipt must become STALE and must not enter route evidence."""
    evaluation = _evaluation_module()
    receipt = evaluation.evaluate_candidate(
        package_root,
        skill_id="saw-rtc",
        provider="fixture",
        model_id="gpt-evaluation-fixture",
        reasoning_id="careful",
        transport=PassingTransport(),
    )
    path = Path(receipt["receipt_path"])
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["attempts"][0]["response_sha256"] = "0" * 64
    path.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result = evaluation.reconcile_qualification_receipt(package_root, path)

    assert result["status"] == "STALE"
    assert result["reason_code"] == "QUALIFICATION_EVIDENCE_HASH_MISMATCH"


def test_only_current_qualified_receipts_can_be_promoted_to_seed_candidates(
    package_root: Path, tmp_path: Path
) -> None:
    """Seed promotion must copy exact reviewed evidence and reject non-qualifying verdicts."""
    evaluation = _evaluation_module()
    receipt = evaluation.evaluate_candidate(
        package_root,
        skill_id="saw-focused-check",
        provider="fixture",
        model_id="gpt-evaluation-fixture",
        reasoning_id="careful",
        transport=PassingTransport(),
    )
    destination = tmp_path / "candidate-seeds.json"

    result = evaluation.promote_receipts(
        package_root,
        receipt_paths=[Path(receipt["receipt_path"])],
        destination=destination,
    )
    seeds = json.loads(destination.read_text(encoding="utf-8"))

    assert result["status"] == "PROMOTED_CANDIDATE"
    assert len(seeds["routes"]) == 1
    assert seeds["routes"][0]["skill_id"] == "saw-focused-check"
    assert seeds["routes"][0]["evidence_sha256"] == receipt["evidence_sha256"]
