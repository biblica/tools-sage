"""Bind the existing phase builders and validators to task-local durable evidence."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
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
    """Extract bounded indexed scope once, then compare locally against the index.

    Simplified per the 2026-09-28 rewrite: EXTRACTION is the only model phase.
    Comparison (numbers/compare.py) and the noteworthy-info advisory
    (numbers/footnotes.py) are both local and deterministic -- no
    CORRESPONDENCE/GROUP_CORRESPONDENCE/FOOTNOTE model calls. Presentation-
    style/heading checking (the old NOTE_STYLE/HEADING_STYLE machinery) has
    no successor here; this pipeline is number-accuracy only.
    """
    from sage.coverage import assess_coverage
    from sage.findings import assign_global_finding_ids
    from .execution import build_inventory, plan_extraction, reference_restrictions
    from .extraction import _parsing_conventions
    from .model_tasks import extract_batch_with_retries
    from .models import Extraction
    from .compare import compare_values
    from .footnotes import noteworthy_note
    from .results import GroupResult, NumbersResult, group_findings, group_summary
    from .telemetry import summarize_calls
    from .policy import validate_optimization_policy

    optimization = validate_optimization_policy(inputs.policy['optimization'])
    checks = inputs.policy['checks']
    mode = inputs.policy['numeric_comparison_mode']
    inventory = build_inventory(inputs)
    streams, plan = plan_extraction(inputs, inventory)
    session = PhaseSession(inputs, model_tasks, phase_store)
    model_tasks.configure_phase_execution(session.execute)
    model_tasks.phase_session = session
    accepted, blocked = {}, dict(plan.blocked)
    for batch in plan.batches:
        result = extract_batch_with_retries(model_tasks, batch,
            parsing_conventions=_parsing_conventions(inputs.style_profile), transient_retries=optimization['transient_retries'])
        accepted.update(result.accepted)
        blocked.update(result.pending)
    by_owner = {}
    for stream in streams:
        if stream.purpose != 'BODY':
            continue
        by_owner[stream.owner_unit_id] = accepted.get(
            stream.input_id,
            Extraction((), 'UNSUPPORTED', (blocked.get(stream.input_id, 'EXTRACTION_UNAVAILABLE'),)),
        )
    groups = []
    for unit in inputs.projected_units:
        extraction = by_owner.get(unit.target.unit_id, Extraction((), 'UNSUPPORTED', ('MISSING_WIP_OR_EXTRACTION',)))
        limits = list(extraction.limitations)
        rows = [inputs.bundle.lookup(ref) for ref in unit.western_references]
        notes = [note for ref in unit.western_references
                 if (note := noteworthy_note(ref, bundle=inputs.bundle)) is not None] if checks['footnote_review'] else []
        if not checks['number_accuracy']:
            comparison = compare_values((), None, mode=mode)  # NOT_ASSESSED placeholder; check disabled
        elif extraction.status != 'COMPLETE':
            comparison = compare_values((), None, mode=mode)
            limits.append('NUMBER_ACCURACY_EXTRACTION_INCOMPLETE')
        elif any(row is None for row in rows):
            comparison = compare_values((), None, mode=mode)
            limits.append('REFERENCE_NOT_INDEXED')
        else:
            # Bridged groups (multiple western_references) compare against the
            # concatenation of each row's expected values, in reference order.
            authority_field = 'ol_values' if all(row.ol_values for row in rows) else 'niv_values'
            expected = tuple(value for row in rows for value in getattr(row, authority_field))
            combined_row = rows[0] if len(rows) == 1 else type(rows[0])(
                rows[0].western_reference, rows[0].ol_reference, rows[0].language,
                rows[0].ol_text, expected if authority_field == 'ol_values' else (),
                rows[0].niv_text, expected if authority_field == 'niv_values' else (), rows[0].metadata,
            )
            comparison = compare_values(extraction.values, combined_row, mode=mode)
        groups.append(GroupResult(unit, extraction, comparison, tuple(dict.fromkeys(limits)), tuple(notes)))
    local = {g.projected.target.unit_id: group_findings(g) for g in groups}
    findings = tuple(assign_global_finding_ids(local, run_id=run_id, prefix='NUMBERS'))
    restrictions = list(reference_restrictions(inputs.policy)) + [limit for g in groups for limit in g.limitations]
    complete = all(g.comparison.outcome in {'PASS', 'FAIL'} for g in groups if checks['number_accuracy'])
    coverage = assess_coverage(findings_present=bool(findings), required_evidence_complete=complete,
        restrictions=restrictions, skipped_checks=tuple(sorted(k for k, v in checks.items() if not v)), assessed=bool(groups)).to_dict()
    coverage.update(expected_unit_ids=list(inputs.expected_unit_ids), assessed_unit_ids=[g.projected.target.unit_id for g in groups],
        requested_scope=inputs.requested_scope, candidate_group_ids=sorted(inventory.expected_groups))
    summary = group_summary(tuple(groups), checks=checks, findings_count=len(findings))
    phases = [{'checkpoint_id': cid, 'key': key.to_dict(), 'receipt': _plain(session.artifacts[key.identity]['receipt']),
        'request_id': session.artifacts[key.identity]['request_id'], 'accepted_input_ids': sorted(session.artifacts[key.identity]['item_sha256'])}
        for cid, key in session.checkpoints.items()]
    measurements = session.durable_calls()
    metrics = dict(summarize_calls(measurements), accepted_phase_receipts=len(phases), checkpoint_reuse=len(session.reused),
        reused_checkpoint_ids=sorted(session.reused), batch_members=sum(len(x['accepted_input_ids']) for x in phases),
        calls=[asdict(x) for x in measurements], checkpoints=phases,
        planning={'planned_extraction_calls': len(plan.batches), 'input_ids': [x.input_id for x in streams], 'blocked': blocked,
                  'missing_owner_ids': [x.target.unit_id for x in inputs.projected_units if x.target.unit_id not in by_owner],
                  'numeric_comparison_mode': mode})
    return NumbersResult(tuple(groups), findings, coverage, summary, metrics)
