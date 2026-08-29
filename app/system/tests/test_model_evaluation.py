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
    "saw-rtc": ["seeded-variance", "aligned-pair", "false-ol-referral"],
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


def test_contract_inventory_has_three_exact_cases_per_registered_skill(package_root: Path) -> None:
    """The sealed Alpha suite must cover positive, zero, and adversarial behavior for every Skill."""
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
    assert payload["case_count"] == 21


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
