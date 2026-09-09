"""Number Consistency & Accuracy domain contracts."""

from .extraction import build_extraction_payload, validate_extraction_response
from .model_tasks import (
    CorrespondenceEvidence,
    ModelPhaseReceipt,
    ModelPhaseResult,
    NcaModelTasks,
    validate_correspondence_response,
)

from .models import (
    Extraction,
    FootnoteDecision,
    NumericExpression,
    ProjectedUnit,
    ReadingDecision,
    ReferenceBundle,
    ReferenceRow,
    RunResult,
    SemanticDecision,
    TargetNote,
    TargetUnit,
    UnitResult,
)

__all__ = [
    "CorrespondenceEvidence",
    "Extraction",
    "FootnoteDecision",
    "ModelPhaseReceipt",
    "ModelPhaseResult",
    "NcaModelTasks",
    "NumericExpression",
    "ProjectedUnit",
    "ReadingDecision",
    "ReferenceBundle",
    "ReferenceRow",
    "RunResult",
    "SemanticDecision",
    "TargetNote",
    "TargetUnit",
    "UnitResult",
    "build_extraction_payload",
    "validate_correspondence_response",
    "validate_extraction_response",
]
