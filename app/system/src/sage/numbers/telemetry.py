"""Exact provider-call measurements for NCA execution and benchmark receipts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class CallMeasurement:
    """One provider request or reuse event with exact transport measurements."""

    request_id: str
    phase: str
    unit_ids: tuple[str, ...]
    elapsed_ms: int
    request_bytes: int
    response_bytes: int
    input_tokens: int | None
    output_tokens: int | None
    status: str
    reused: bool

    def __post_init__(self) -> None:
        """Require exact nonnegative counters and immutable request identity fields."""
        if not isinstance(self.request_id, str) or not self.request_id:
            raise ValueError("NCA measurement request ID must be nonempty text")
        if not isinstance(self.phase, str) or not self.phase:
            raise ValueError("NCA measurement phase must be nonempty text")
        if (
            not isinstance(self.unit_ids, tuple)
            or not self.unit_ids
            or any(not isinstance(value, str) or not value for value in self.unit_ids)
        ):
            raise ValueError("NCA measurement unit IDs must be a nonempty text tuple")
        for label, value in (
            ("elapsed", self.elapsed_ms),
            ("request bytes", self.request_bytes),
            ("response bytes", self.response_bytes),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"NCA measurement {label} must be a nonnegative exact count")
        for label, value in (
            ("input tokens", self.input_tokens),
            ("output tokens", self.output_tokens),
        ):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(
                    f"NCA measurement {label} must be null or a nonnegative exact count"
                )
        if not isinstance(self.status, str) or not self.status:
            raise ValueError("NCA measurement status must be nonempty text")
        if type(self.reused) is not bool:
            raise ValueError("NCA measurement reused flag must be Boolean")


def summarize_calls(calls: tuple[CallMeasurement, ...]) -> dict[str, object]:
    """Aggregate unique provider requests while retaining failures and reuse events."""
    actual: dict[str, CallMeasurement] = {}
    reuse_events: list[CallMeasurement] = []
    identities: dict[str, tuple[object, ...]] = {}
    identity_fields = tuple(field.name for field in fields(CallMeasurement) if field.name != "reused")
    for call in calls:
        identity = tuple(getattr(call, name) for name in identity_fields)
        previous = identities.setdefault(call.request_id, identity)
        if previous != identity:
            raise ValueError(f"Inconsistent NCA call measurements for request {call.request_id!r}")
        if call.reused:
            reuse_events.append(call)
        else:
            actual.setdefault(call.request_id, call)

    executed = tuple(actual.values())
    failures = tuple(
        call for call in executed if call.status not in {"COMPLETE", "SUCCESS", "VALIDATED"}
    )

    def usage(field_name: str) -> int | None:
        """Sum one provider usage counter only when every executed call reports it."""
        values = tuple(getattr(call, field_name) for call in executed)
        return None if any(value is None for value in values) else sum(values)

    return {
        "provider_calls": len(executed),
        "reuse_events": len(reuse_events),
        "failed_calls": len(failures),
        "phase_counts": dict(sorted(Counter(call.phase for call in executed).items())),
        "status_counts": dict(sorted(Counter(call.status for call in executed).items())),
        "elapsed_ms": sum(call.elapsed_ms for call in executed),
        "request_bytes": sum(call.request_bytes for call in executed),
        "response_bytes": sum(call.response_bytes for call in executed),
        "input_tokens": usage("input_tokens"),
        "output_tokens": usage("output_tokens"),
        "failure_request_ids": tuple(call.request_id for call in failures),
        "reused_request_ids": tuple(call.request_id for call in reuse_events),
    }
