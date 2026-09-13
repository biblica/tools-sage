"""Pack protected NCA inputs with the existing routed-SFM sizing authority."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sage.errors import EvidenceLimitError, ValidationError
from sage.evidence import EvidencePolicy
from sage.sfm_slicer import SfmAnalysisRoute, SfmStream, plan_sfm_work_units, render_sfm_slice

from .models import freeze
from .transport import StreamInput, _digest

CONTRACT_VERSION = 'nca-optimization-2.0'


@dataclass(frozen=True)
class ExtractionBatch:
    """Protected extraction membership and precisely the bounded SFM sized for it."""
    batch_id: str
    inputs: tuple[StreamInput, ...]
    routed_sfm: str
    contract_version: str

    def __post_init__(self) -> None:
        """Require immutable, unique, bound membership while allowing actual routed context."""
        if (not isinstance(self.inputs, tuple) or not self.inputs
                or any(not isinstance(value, StreamInput) for value in self.inputs)
                or len({value.input_id for value in self.inputs}) != len(self.inputs)
                or not isinstance(self.routed_sfm, str) or not self.routed_sfm
                or self.contract_version != CONTRACT_VERSION):
            raise ValidationError('NCA extraction batch is invalid', code='NCA_BATCH_COVERAGE_INVALID')
        identity = 'batch:' + _digest({'inputs': [value.input_id for value in self.inputs],
            'sfm': self.routed_sfm, 'version': self.contract_version})
        if self.batch_id != identity:
            raise ValidationError('NCA extraction batch identity differs', code='NCA_BATCH_COVERAGE_INVALID')


@dataclass(frozen=True)
class BatchPlan:
    """Every eligible input is either routed once or explicitly blocked."""
    batches: tuple[ExtractionBatch, ...]
    blocked: Mapping[str, str]

    def __post_init__(self) -> None:
        """Own immutable limitations and reject overlapping terminal dispositions."""
        ids = [value.input_id for batch in self.batches for value in batch.inputs]
        if len(ids) != len(set(ids)) or set(ids).intersection(self.blocked):
            raise ValidationError('NCA batch coverage overlaps', code='NCA_BATCH_COVERAGE_INVALID')
        object.__setattr__(self, 'blocked', freeze(self.blocked))


def _batch(inputs: tuple[StreamInput, ...], sfm: str, version: str = CONTRACT_VERSION) -> ExtractionBatch:
    """Name a deterministic batch by its bound members and exact routed text."""
    digest = _digest({'inputs': [value.input_id for value in inputs], 'sfm': sfm, 'version': version})
    return ExtractionBatch('batch:' + digest, inputs, sfm, version)


def split_batch(batch: ExtractionBatch) -> tuple[ExtractionBatch, ...]:
    """Bisect failed membership without splitting an input; singletons terminate."""
    if len(batch.inputs) <= 1:
        return ()
    middle = len(batch.inputs) // 2
    return tuple(_batch(values, ''.join(value.routed_sfm for value in values), batch.contract_version)
                 for values in (batch.inputs[:middle], batch.inputs[middle:]))


def plan_batches(inputs: tuple[StreamInput, ...], *, policy: EvidencePolicy, max_units: int = 8) -> BatchPlan:
    """Apply an input cap outside the shared planner, preserving its actual hard limits."""
    if type(max_units) is not int or max_units <= 0:
        raise ValidationError('NCA extraction input cap must be a positive integer', code='NCA_BATCH_POLICY_INVALID')
    if (not isinstance(inputs, tuple) or any(not isinstance(value, StreamInput) for value in inputs)
            or len({value.input_id for value in inputs}) != len(inputs)):
        raise ValidationError('NCA extraction inputs must be unique typed members', code='NCA_BATCH_COVERAGE_INVALID')
    batches: list[ExtractionBatch] = []
    blocked: dict[str, str] = {}

    def plan_group(values: tuple[StreamInput, ...]) -> None:
        """Size each candidate; isolate a hard failure down to indivisible inputs."""
        records = tuple(record for value in values for record in value.records)
        route = SfmAnalysisRoute('NCA_EXTRACTION', tuple(SfmStream(value.input_id, value.records,
            require_primary_coverage=False) for value in values))
        try:
            units = plan_sfm_work_units(records, policy, unit_prefix='NCA', route=route,
                required_spans=tuple(tuple(ref for record in value.records for ref in record.refs) for value in values))
        except EvidenceLimitError as exc:
            if len(values) == 1:
                blocked[values[0].input_id] = str(exc.code or 'NCA_INPUT_EXCEEDS_LIMIT') + ': ' + str(exc)
            else:
                middle = len(values) // 2
                plan_group(values[:middle])
                plan_group(values[middle:])
            return
        for unit in units:
            members = tuple(value for value in values
                if any(ref in unit.primary_refs for record in value.records for ref in record.refs))
            selected = unit.primary_refs | unit.context_refs
            # Mirror the shared route selection, including bounded context. Each
            # stream is rendered independently, just as the shared sizer does.
            sfm = ''.join(render_sfm_slice(tuple(record for record in value.records
                if selected.intersection(record.refs))) for value in values)
            batches.append(_batch(members, sfm))

    pending: list[StreamInput] = []
    last = None
    for value in inputs:
        first = value.records[0]
        key = (first.book, first.chapter, first.verse_start)
        # Keep actual Scripture coordinates. Repeated note/heading anchors and
        # book/order boundaries start another candidate rather than fabricating refs.
        if pending and (len(pending) == max_units or first.book != last[0]
                or first.chapter != last[1] or key <= last
                or (value.purpose, value.language, value.conventions_sha256)
                != (pending[0].purpose, pending[0].language, pending[0].conventions_sha256)):
            plan_group(tuple(pending))
            pending = []
        pending.append(value)
        end = value.records[-1]
        last = (end.book, end.chapter, end.verse_end)
    if pending:
        plan_group(tuple(pending))
    result = BatchPlan(tuple(batches), blocked)
    if {value.input_id for batch in result.batches for value in batch.inputs} | set(result.blocked) != {value.input_id for value in inputs}:
        raise ValidationError('NCA batch coverage differs', code='NCA_BATCH_COVERAGE_INVALID')
    return result
