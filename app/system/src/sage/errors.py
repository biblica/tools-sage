"""Domain exceptions used by the SAGE runtime."""

from __future__ import annotations

from typing import Any


class SageError(Exception):
    """Base class for expected SAGE failures with a stable machine contract."""

    default_code = "SAGE_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        next_action: str | None = None,
        affected_scope: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the instance with the supplied governed state."""
        super().__init__(message)
        self.message = str(message)
        self.code = (code or self.default_code).strip().upper()
        self.next_action = next_action
        self.affected_scope = affected_scope
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for reports and state files."""
        value: dict[str, Any] = {
            "status": "ERROR",
            "reason_code": self.code,
            "message": self.message,
        }
        if self.affected_scope:
            value["affected_scope"] = self.affected_scope
        if self.next_action:
            value["next_action"] = self.next_action
        if self.details:
            value["details"] = self.details
        return value


class InputRequiredError(SageError):
    """Raised when operator input can be corrected or supplied interactively."""

    default_code = "INPUT_REQUIRED"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        received: Any = None,
        suggestions: list[dict[str, Any]] | None = None,
        retryable: bool = True,
        next_action: str | None = None,
        affected_scope: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the instance with the supplied governed state."""
        super().__init__(
            message,
            code=code or self.default_code,
            next_action=next_action,
            affected_scope=affected_scope,
            details=details,
        )
        self.received = received
        self.suggestions = list(suggestions or [])
        self.retryable = bool(retryable)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for reports and state files."""
        value = super().to_dict()
        value["status"] = "INPUT_REQUIRED"
        value["received"] = self.received
        value["suggestions"] = self.suggestions
        value["retryable"] = self.retryable
        return value


class OperatorCancelledError(SageError):
    """Raised when the Operator cancels a guided correction or setup flow."""

    default_code = "OPERATOR_CANCELLED"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation for reports and state files."""
        value = super().to_dict()
        value["status"] = "ABANDONED"
        return value


class ConfigurationError(SageError):
    """Raised when ecosystem or workflow configuration is invalid."""

    default_code = "CONFIGURATION_ERROR"


class ValidationError(SageError):
    """Raised when a project, resource, or package fails validation."""

    default_code = "VALIDATION_ERROR"


class LockError(SageError):
    """Raised when an operation cannot acquire or safely recover a lock."""

    default_code = "LOCK_ERROR"


class VersificationError(ValidationError):
    """Raised when a base or project-local VRS file is invalid."""

    default_code = "VERSIFICATION_ERROR"


class EvidenceLimitError(ValidationError):
    """Raised when a serialized evidence packet exceeds a governed hard limit."""

    default_code = "ACT_TOTAL_TOKEN_LIMIT_EXCEEDED"


class TransactionError(SageError):
    """Raised when a journaled multi-file transaction cannot commit or recover."""

    default_code = "TRANSACTION_ERROR"


class GenerationError(SageError):
    """Raised when an immutable generated-TARGET publication is invalid."""

    default_code = "GENERATION_ERROR"


class MemoryGovernanceError(SageError):
    """Raised when BIC memory or INSPECT data violates governed state rules."""

    default_code = "MEMORY_GOVERNANCE_ERROR"
