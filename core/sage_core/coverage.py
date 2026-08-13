"""Truthful result, coverage, and confidence-basis controls for workflow reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from .errors import ValidationError

RESULT_VALUES = {"FINDINGS", "NO_FINDINGS", "INSUFFICIENT_DATA", "NOT_ASSESSED"}
COVERAGE_VALUES = {"COMPLETE", "COMPLETE_WITH_RESTRICTIONS", "PARTIAL", "NOT_ASSESSED"}
CONFIDENCE_BASIS_VALUES = {"FULL", "LIMITED"}


@dataclass(frozen=True)
class CoverageAssessment:
    """Represent one bounded analytical coverage statement without overstating review."""

    result: str
    coverage: str
    confidence_basis: str
    restrictions: tuple[str, ...] = ()
    skipped_checks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate and normalise fields after dataclass initialisation."""
        if self.result not in RESULT_VALUES:
            raise ValidationError(f"Uncontrolled result value: {self.result}")
        if self.coverage not in COVERAGE_VALUES:
            raise ValidationError(f"Uncontrolled coverage value: {self.coverage}")
        if self.confidence_basis not in CONFIDENCE_BASIS_VALUES:
            raise ValidationError(
                f"Uncontrolled confidence basis: {self.confidence_basis}"
            )
        if (self.result == "NOT_ASSESSED") != (self.coverage == "NOT_ASSESSED"):
            raise ValidationError(
                "NOT_ASSESSED result and coverage must be used together"
            )
        if self.result == "NOT_ASSESSED":
            if self.confidence_basis != "LIMITED":
                raise ValidationError("NOT_ASSESSED must use LIMITED confidence basis")
            return
        if self.coverage == "COMPLETE" and (self.restrictions or self.skipped_checks):
            raise ValidationError(
                "Coverage may not be COMPLETE when restrictions or skipped checks exist"
            )
        if self.result == "INSUFFICIENT_DATA" and self.coverage == "COMPLETE":
            raise ValidationError("INSUFFICIENT_DATA may not claim COMPLETE coverage")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation for reports and state files."""
        return asdict(self)


def assess_coverage(
    *,
    findings_present: bool,
    required_evidence_complete: bool,
    restrictions: Iterable[str] = (),
    skipped_checks: Iterable[str] = (),
    assessed: bool = True,
) -> CoverageAssessment:
    """Derive a concise coverage statement from actual evidence conditions."""
    restriction_values = tuple(sorted(set(item for item in restrictions if item)))
    skipped_values = tuple(sorted(set(item for item in skipped_checks if item)))
    if not assessed:
        return CoverageAssessment(
            result="NOT_ASSESSED",
            coverage="NOT_ASSESSED",
            confidence_basis="LIMITED",
            restrictions=restriction_values,
            skipped_checks=skipped_values,
        )
    if not required_evidence_complete:
        return CoverageAssessment(
            result="INSUFFICIENT_DATA",
            coverage="PARTIAL",
            confidence_basis="LIMITED",
            restrictions=restriction_values or ("Required evidence is incomplete.",),
            skipped_checks=skipped_values,
        )
    if restriction_values or skipped_values:
        return CoverageAssessment(
            result="FINDINGS" if findings_present else "NO_FINDINGS",
            coverage="COMPLETE_WITH_RESTRICTIONS",
            confidence_basis="LIMITED",
            restrictions=restriction_values,
            skipped_checks=skipped_values,
        )
    return CoverageAssessment(
        result="FINDINGS" if findings_present else "NO_FINDINGS",
        coverage="COMPLETE",
        confidence_basis="FULL",
    )
