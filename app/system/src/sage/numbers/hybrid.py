"""Bind the existing phase builders and validators to task-local durable evidence."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, replace
import json

from sage.errors import ValidationError
from .extraction import BatchValidation
from .model_tasks import ModelPhaseReceipt, ModelPhaseResult
from .policy import _plain
from .replay import PhaseKey, PhaseStore


def canonical(value: object) -> bytes:
    """Encode explicitly derived phase identity bytes, never reconstructed source bytes."""
    return json.dumps(_plain(value), ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


class CheckpointFailure(RuntimeError):
    """Keep persistence/control failure outside legacy semantic-insufficiency handlers."""


class PhaseSession:
    """One attempt's exact builders, validators, checkpoint IDs, and physical evidence."""

    # Durable requests remain distinct from accepted receipts and checkpoint reuse.
    def __init__(self, inputs: object, tasks: object, store: PhaseStore) -> None:
        """Bind sealed original policy/contracts once, with no resource qualification loop."""
        self.inputs, self.tasks, self.store = inputs, tasks, store
        self.checkpoints = {}
        self.validators = {}
        self.artifacts = {}
        self.reused = set()

    def validate_phase(self, key: PhaseKey, artifact: Mapping[str, object], *, allow_empty: bool = False) -> object:
        """Reapply the actual phase validator to its exact current protected input payload."""
        try:
            validator, payload, version = self.validators[key.identity]
        except KeyError as exc:
            raise CheckpointFailure('Phase checkpoint lacks current protected context') from exc
        prompt = json.loads(artifact['attempt']['request']['prompt'])
        if (prompt['input'] != _plain(payload) or artifact['receipt']['task_version'] != version
                or dict(artifact['route_snapshot']) != dict(self.inputs.policy['model_route'])):
            raise CheckpointFailure('Phase checkpoint payload or route differs')
        value = validator(json.loads(artifact['raw_response']))
        items = dict(value.item_sha256) if isinstance(value, BatchValidation) else {}
        if items != dict(artifact['item_sha256']) or isinstance(value, BatchValidation) and not value.accepted and not allow_empty:
            raise CheckpointFailure('Phase checkpoint has no admitted member or different item hashes')
        return ModelPhaseResult(value, ModelPhaseReceipt(**artifact['receipt']), artifact['raw_response'], artifact['request_id'])

    def execute(self, phase: str, payload: Mapping[str, object], validator: object, *,
                task_version: str, schema: Mapping[str, object], physical: object) -> object:
        """Replay accepted membership or immediately commit one real admitted response."""
        ids = (tuple(x['input_id'] for x in payload['work_units']) if phase == 'EXTRACTION' else (payload['unit_id'],))
        key = PhaseKey.build(phase=phase, task_fingerprint=self.store.task_fingerprint,
            input_ids=ids, input_components={'canonical_phase_payload': canonical(payload)},
            policy_bytes=self.inputs.policy_bytes, route=self.inputs.policy['model_route'],
            contract_components=dict(self.inputs.contract_components) | {'canonical_response_schema': canonical(schema), 'task_version': task_version.encode()},
            validator_version=task_version)
        self.validators[key.identity] = (validator, payload, task_version)
        def validate(artifact):
            """Retain the original physical artifact only after exact fresh validation."""
            result = self.validate_phase(key, artifact)
            self.artifacts[key.identity] = artifact
            return result
        try:
            cached = self.store.lookup_checkpoint(key, validate=validate)
        except (ValidationError, CheckpointFailure) as exc:
            raise CheckpointFailure('NCA checkpoint replay failed') from exc
        if cached is not None:
            checkpoint_id, result = cached
            self.checkpoints[checkpoint_id] = key
            self.reused.add(checkpoint_id)
            return result
        if getattr(self.tasks, 'phase_resume_only', False):
            return self._replay_failure(key)
        try:
            result = physical(phase, payload, validator, task_version=task_version, schema=schema)
        except ValidationError as exc:
            try:
                self.store.record_failure(key, {'code': str(exc.code), 'message': str(exc),
                    'attempts': [self._attempt(x) for x in self.tasks.attempts if x.measurement.unit_ids == ids]})
            except ValidationError as persistence:
                raise CheckpointFailure('NCA failure evidence was not durably recorded') from persistence
            if exc.code in {'NCA_MODEL_ROUTE_CHANGED', 'LLM_RESPONSE_ROUTE_MISMATCH', 'PROVIDER_ROUTE_UNAVAILABLE'}:
                raise CheckpointFailure('NCA sealed provider route failed') from exc
            raise
        attempt = next(x for x in self.tasks.attempts if x.measurement.request_id == result.request_id)
        artifact = {'receipt': result.receipt.to_dict(), 'raw_response': result.raw_response,
            'request_id': result.request_id, 'route_snapshot': _plain(self.inputs.policy['model_route']),
            'attempt': self._attempt(attempt),
            'item_sha256': dict(result.value.item_sha256) if isinstance(result.value, BatchValidation) else {}}
        if isinstance(result.value, BatchValidation) and not result.value.accepted:
            self.store.record_failure(key, {'code': 'NCA_BATCH_NO_ADMITTED_MEMBERS', 'pending': dict(result.value.pending),
                'phase_artifact': artifact})
            return result
        try:
            checkpoint_id = self.store.commit(key, artifact, validate=validate)
        except (ValidationError, CheckpointFailure) as exc:
            raise CheckpointFailure('NCA phase acceptance was not durably committed') from exc
        self.checkpoints[checkpoint_id] = key
        return result

    def _replay_failure(self, key: PhaseKey) -> object:
        """Revalidate the last durable failure solely while recovering an already staged publication."""
        from .replay import _validate_physical
        failures = [row['diagnostic'] for row in self.store.failure_diagnostics() if row['key'] == key.to_dict()]
        if not failures:
            raise CheckpointFailure('Prepared publication lacks original failed-phase history')
        diagnostic = failures[-1]
        if diagnostic.get('code') == 'NCA_BATCH_NO_ADMITTED_MEMBERS':
            artifact = _validate_physical(key, diagnostic.get('phase_artifact'))
            result = self.validate_phase(key, artifact, allow_empty=True)
            if (not isinstance(result.value, BatchValidation) or result.value.accepted
                    or dict(result.value.pending) != diagnostic.get('pending')):
                raise CheckpointFailure('Recorded failed envelope no longer validates as the same pending membership')
            return result
        attempts = diagnostic.get('attempts')
        if not isinstance(attempts, list) or not attempts:
            raise CheckpointFailure('Recorded failure has no physical request evidence')
        attempt = attempts[-1]
        measurement = attempt['measurement']
        validator, payload, version = self.validators[key.identity]
        prompt = json.loads(attempt['request']['prompt'])
        code = diagnostic.get('code')
        if (measurement['phase'] != key.phase or measurement['unit_ids'] != list(key.input_ids)
                or measurement['status'] != code or prompt['input'] != _plain(payload)
                or prompt['task_version'] != version):
            raise CheckpointFailure('Recorded failed request differs from current protected phase')
        raw = attempt['raw_response']
        if raw is not None:
            try:
                decoded = json.loads(raw)
            except (TypeError, ValueError):
                if code != 'NCA_MODEL_RESPONSE_INVALID':
                    raise CheckpointFailure('Recorded parsing failure differs')
            else:
                try:
                    validator(decoded)
                except ValidationError as failure:
                    if failure.code != code:
                        raise CheckpointFailure('Current validator disagrees with the recorded terminal failure') from failure
                else:
                    raise CheckpointFailure('Recorded failure now has valid evidence without an accepted checkpoint')
        elif code != 'NCA_MODEL_PROVIDER_FAILED':
            raise CheckpointFailure('Recorded no-response failure has an invalid disposition')
        raise ValidationError(str(diagnostic.get('message') or 'Recorded failed phase'), code=code)

    def durable_calls(self) -> tuple[object, ...]:
        """Reconcile all durably observed task requests, including rejected envelopes and failures."""
        from .telemetry import CallMeasurement
        attempts = [artifact['attempt'] for artifact in self.artifacts.values()]
        for failure in self.store.failure_diagnostics():
            attempts.extend(failure['diagnostic'].get('attempts', ()))
            if 'phase_artifact' in failure['diagnostic']:
                attempts.append(failure['diagnostic']['phase_artifact']['attempt'])
        calls = {}
        for attempt in attempts:
            raw = attempt['measurement']
            call = CallMeasurement(**dict(raw, unit_ids=tuple(raw['unit_ids'])))
            previous = calls.setdefault(call.request_id, call)
            if previous != call:
                raise CheckpointFailure('Durable physical request identity conflicts')
        return tuple(calls[key] for key in sorted(calls))

    @staticmethod
    def _attempt(attempt: object) -> dict[str, object]:
        """Copy exact physical request/response evidence without changing raw provider text."""
        return {'measurement': _plain(asdict(attempt.measurement)), 'request': _plain(attempt.request),
            'raw_response': attempt.raw_response, 'response_identity': _plain(attempt.response_identity)}


def evaluate(inputs: object, *, model_tasks: object, phase_store: PhaseStore, run_id: str) -> object:
    """Extract bounded complete scope once, then feed accepted evidence to typed comparison."""
    from sage.evidence import EvidencePolicy
    from sage.references import parse_scope
    from sage.coverage import assess_coverage
    from sage.findings import assign_global_finding_ids
    from .execution import build_inventory, reference_restrictions
    from .batching import plan_batches
    from .extraction import _parsing_conventions
    from .model_tasks import extract_batch_with_retries
    from .models import Extraction, ProjectedUnit
    from .models_v2 import ComponentResult, GroupResult, OptimizedRunResult
    from .engine import (_evaluate_prepared_unit, candidate_group_ids, _result_reference_context)
    from .results_v2 import group_findings, group_summary
    from .groups import ReferenceGroup, evaluate_group, assess_group_notes, row_provenance
    from .telemetry import summarize_calls
    from .policy import validate_optimization_policy

    optimization = validate_optimization_policy(inputs.policy['optimization'])
    checks = inputs.policy['checks']
    inventory = build_inventory(inputs)
    streams = tuple(x for x in inventory.stream_inputs if x.purpose == 'BODY' or checks['presentation_consistency'])
    plan = plan_batches(streams, policy=EvidencePolicy.from_mapping(inputs.evidence_policy),
                        max_units=optimization['extraction_batch_max_units'])
    session = PhaseSession(inputs, model_tasks, phase_store)
    model_tasks.configure_phase_execution(session.execute)
    model_tasks.phase_session = session
    accepted, blocked = {}, dict(plan.blocked)
    for batch in plan.batches:
        result = extract_batch_with_retries(model_tasks, batch,
            parsing_conventions=_parsing_conventions(inputs.style_profile), transient_retries=optimization['transient_retries'])
        accepted.update(result.accepted)
        blocked.update(result.pending)
    by_owner, notes = {}, {}
    for stream in streams:
        extraction = accepted.get(stream.input_id, Extraction((), 'UNSUPPORTED', (blocked.get(stream.input_id, 'EXTRACTION_UNAVAILABLE'),)))
        if stream.purpose == 'NOTE_STYLE':
            notes.setdefault(stream.owner_unit_id, {})[stream.stream_id.removeprefix('note:')] = extraction
        else:
            by_owner[stream.owner_unit_id] = extraction
    candidates = candidate_group_ids(inventory, by_owner)
    projected = inputs.projected_units + tuple(ProjectedUnit(x, (), x.target_references, 'STYLE_STREAM', 'READY') for x in inputs.style_units)
    groups = []
    for unit in projected:
        heading = unit.precision == 'STYLE_STREAM'
        selected_checks = dict(checks, number_accuracy=False, footnote_review=False) if heading else checks
        extraction = by_owner.get(unit.target.unit_id, Extraction((), 'UNSUPPORTED',
            ('PRESENTATION_CHECK_DISABLED',) if heading and not checks['presentation_consistency'] else ('MISSING_WIP_OR_EXTRACTION',)))
        # Presentation reuses the parent extraction; semantic policy runs only after row ownership.
        multirow = len(unit.western_references) > 1
        prepared_checks = dict(selected_checks, number_accuracy=False, footnote_review=False) if multirow else selected_checks
        result = _evaluate_prepared_unit(unit, bundle=inputs.bundle, language=inputs.policy['wip']['language'],
            language_profile={}, style_profile=inputs.style_profile, checks=prepared_checks, model_tasks=model_tasks,
            extraction=extraction, note_extractions=notes.get(unit.target.unit_id, {}))
        rows = tuple(dict(row, provenance=row_provenance(inputs.bundle.lookup(ref), inputs.bundle), context=(_result_reference_context(inputs.bundle.lookup(ref), inputs.bundle)
            if inputs.bundle.lookup(ref) is not None else {})) for row, ref in zip(result.reference_index, unit.western_references))
        ids = tuple(x.expression_id for x in extraction.expressions)
        semantic_enabled = not heading and (checks["number_accuracy"] or checks["footnote_review"])
        resolved = len(unit.western_references) == 1 and semantic_enabled
        components = (ComponentResult(unit.western_references[0], rows[0]['ol_reference'], ids,
            result.source_expressions, result.reading, result.footnote, result.final_outcome, result.limitations),) if resolved else ()
        limits = result.limitations
        alignment = 'NOT_ASSESSED' if not semantic_enabled else 'COMPLETE' if resolved else 'UNAVAILABLE'
        ownership = {eid: unit.western_references[0].label() for eid in ids} if resolved else {}
        unmatched, unresolved = (ids if not semantic_enabled else ()), (ids if semantic_enabled and not resolved else ())
        if multirow and semantic_enabled and extraction.status == 'COMPLETE' and unit.status in {'READY', 'REGISTERED_ABSENCE'}:
            reference_group = ReferenceGroup.build(unit, bundle=inputs.bundle)
            try:
                correspondence = model_tasks.correspond_group(unit, extraction, reference_group).value
            except ValidationError as exc:
                limits = tuple(dict.fromkeys((*limits, exc.code)))
            else:
                alignment = correspondence.status
                limits = tuple(dict.fromkeys((*limits, *correspondence.limitations)))
                if alignment != 'UNAVAILABLE':
                    components = evaluate_group(reference_group, extraction, correspondence, bundle=inputs.bundle, checks=checks)
                    components = assess_group_notes(reference_group, components, bundle=inputs.bundle, checks=checks,
                        language=inputs.policy['wip']['language'], model_tasks=model_tasks)
                    roles = {x.expression_id: x for row in correspondence.rows.values() for x in row.target_extraction.expressions}
                    extraction = replace(extraction, expressions=tuple(roles.get(x.expression_id, x) for x in extraction.expressions))
                    ownership = {eid: ref for ref, eids in correspondence.assignments.items() for eid in eids}
                    unmatched, unresolved = correspondence.unmatched_target_ids, correspondence.unresolved_target_ids
        if alignment == 'UNAVAILABLE':
            limits = tuple(dict.fromkeys((*limits, 'GROUP_ALIGNMENT_UNRESOLVED')))
        groups.append(GroupResult(unit, extraction, rows, components, alignment, ownership,
            unmatched, unresolved, result.style_findings, limits))
    local = {g.projected.target.unit_id: group_findings(g, bundle=inputs.bundle,
        checks=dict(checks, number_accuracy=False, footnote_review=False) if g.projected.precision == 'STYLE_STREAM' else checks) for g in groups}
    findings = tuple(assign_global_finding_ids(local, run_id=run_id, prefix='NUMBERS'))
    restrictions = list(reference_restrictions(inputs.policy)) + [limit for g in groups for limit in g.limitations]
    if checks['presentation_consistency']:
        restrictions.extend(str(x['code']) for g in groups for x in g.style_findings if x['status'] == 'NOT_ASSESSED')
    complete = all((g.extraction.status == 'COMPLETE' or 'PRESENTATION_CHECK_DISABLED' in g.limitations)
        and g.alignment_status not in {'PARTIAL', 'UNAVAILABLE'}
        and all(c.reading.semantic.outcome not in {'INSUFFICIENT_EVIDENCE', 'REFERENCE_NOT_INDEXED'}
                and c.footnote.outcome != 'INSUFFICIENT_EVIDENCE' for c in g.components) for g in groups)
    coverage = assess_coverage(findings_present=bool(findings), required_evidence_complete=complete,
        restrictions=restrictions, skipped_checks=tuple(sorted(k for k, v in checks.items() if not v)), assessed=bool(groups)).to_dict()
    scope = parse_scope(inputs.requested_scope)
    coverage.update(expected_unit_ids=list(inputs.expected_unit_ids), assessed_unit_ids=[g.projected.target.unit_id for g in groups],
        requested_scope=inputs.requested_scope, candidate_group_ids=sorted(candidates),
        scope_expansions=[{'unit_id': g.projected.target.unit_id, 'included_target_references': [r.label() for r in g.projected.target.target_references if not scope.contains(r)],
            'western_references': [r.label() for r in g.projected.western_references]} for g in groups if any(not scope.contains(r) for r in g.projected.target.target_references)])
    summary = group_summary(tuple(groups), checks=checks, findings_count=len(findings))
    phases = [{'checkpoint_id': cid, 'key': key.to_dict(), 'receipt': _plain(session.artifacts[key.identity]['receipt']),
        'request_id': session.artifacts[key.identity]['request_id'], 'accepted_input_ids': sorted(session.artifacts[key.identity]['item_sha256'])}
        for cid, key in session.checkpoints.items()]
    measurements = session.durable_calls()
    metrics = dict(summarize_calls(measurements), accepted_phase_receipts=len(phases), checkpoint_reuse=len(session.reused),
        reused_checkpoint_ids=sorted(session.reused), batch_members=sum(len(x['accepted_input_ids']) for x in phases),
        calls=[asdict(x) for x in measurements], checkpoints=phases,
        planning={'input_ids': [x.input_id for x in streams], 'blocked': blocked,
                  'missing_owner_ids': [x.target.unit_id for x in projected if x.target.unit_id not in by_owner]})
    return OptimizedRunResult(tuple(groups), findings, coverage, summary, metrics)
