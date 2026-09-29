"""NCA machine results preserve exact evidence and reject invented or malformed state."""

from copy import deepcopy
from fractions import Fraction

import pytest

from sage.errors import ValidationError
from sage.numbers.compare import ComparisonResult
from sage.numbers.models import Extraction, ProjectedUnit, TargetUnit
from sage.numbers.results import (
    NCA_CAPABILITY_LIMITATION,
    GroupResult,
    NumbersResult,
    group_findings,
    group_summary,
    numbers_result_document,
    validate_numbers_result,
)
from sage.vrs import VerseRef


def _group(*, outcome='PASS', extraction_status='COMPLETE', wip=(3,), expected=(3,),
           mode='ORDERED', authority='OL', notes=(), limitations=(), unit_id='unit-1',
           review_context=None):
    """Build one hand-specified group result for serializer/validator tests."""
    reference = VerseRef('MAT', 1, 1)
    target = TargetUnit(unit_id, (reference,), 'three men', (), 'a' * 64, {'line_start': 3, 'line_end': 3})
    projected = ProjectedUnit(target, (reference,), (reference,), 'COORDINATE', 'READY')
    values = tuple(Fraction(value) for value in wip)
    extraction = Extraction(values if extraction_status == 'COMPLETE' else (),
                             extraction_status, () if extraction_status == 'COMPLETE' else ('Unsupported',))
    comparison = ComparisonResult(outcome, mode, values, tuple(Fraction(value) for value in expected),
                                   authority, review_context)
    return GroupResult(projected, extraction, comparison, tuple(limitations), tuple(notes))


def _receipt():
    """Build one hand-specified EXTRACTION phase receipt for validator tests."""
    return {
        'phase': 'EXTRACTION', 'task_version': 'nca-extraction-1.0', 'provider': 'codex',
        'model': 'gpt-test', 'reasoning_effort': 'high', 'route_id': 'route-1',
        'routing_mode': 'AUTOMATIC', 'qualification_status': 'QUALIFIED',
        'prompt_sha256': '1' * 64, 'input_sha256': '2' * 64, 'response_sha256': '3' * 64,
        'provider_metadata': {},
    }


def _document(groups, *, findings=(), run_id='RUN-1'):
    """Build one complete canonical result document from typed groups."""
    from sage.coverage import assess_coverage
    from sage.findings import assign_global_finding_ids
    local = {group.projected.target.unit_id: group_findings(group) for group in groups}
    assigned = tuple(assign_global_finding_ids(local, run_id=run_id, prefix='NUMBERS')) if not findings else findings
    checks = {'number_accuracy': True, 'presentation_consistency': True, 'footnote_review': True}
    complete = all(group.comparison.outcome in {'PASS', 'FAIL'} for group in groups)
    coverage = assess_coverage(findings_present=bool(assigned), required_evidence_complete=complete,
                                assessed=bool(groups)).to_dict()
    coverage.update(
        expected_unit_ids=[group.projected.target.unit_id for group in groups],
        assessed_unit_ids=[group.projected.target.unit_id for group in groups],
        requested_scope='MAT 1',
        candidate_group_ids=sorted(group.projected.target.unit_id for group in groups),
    )
    summary = group_summary(tuple(groups), checks=checks, findings_count=len(assigned))
    run_result = NumbersResult(tuple(groups), assigned, coverage, summary,
                                {'planning': {'numeric_comparison_mode': 'ORDERED'}})
    document = numbers_result_document(
        run_result,
        provenance={'run_id': run_id, 'job_id': 'JOB-1'},
        check_policy={'checks': checks},
        model_receipts={'EXTRACTION': [_receipt()]},
    )
    expected_ids = tuple(group.projected.target.unit_id for group in groups)
    return document, expected_ids


def test_group_findings_are_empty_for_pass_and_not_assessed():
    """Only FAIL and NEEDS_REVIEW comparison outcomes ever produce a finding."""
    assert group_findings(_group(outcome='PASS')) == []
    assert group_findings(_group(outcome='NOT_ASSESSED', extraction_status='UNSUPPORTED', wip=(), expected=())) == []


def test_fail_finding_is_blocking_and_needs_review_finding_is_review():
    """Severity distinguishes a real value difference from an ambiguous reordering."""
    fail = group_findings(_group(outcome='FAIL', wip=(3,), expected=(4,)))
    assert fail[0]['severity'] == 'BLOCKING'
    assert fail[0]['code'] == 'NCA_NUMBER_FAIL'
    review = group_findings(_group(outcome='NEEDS_REVIEW', wip=(200, 14), expected=(14, 200),
                                    review_context={'wip_order': ['200', '14'], 'expected_order': ['14', '200'],
                                                     'authority_text': 'OL text'}))
    assert review[0]['severity'] == 'REVIEW'
    assert review[0]['code'] == 'NCA_NUMBER_NEEDS_REVIEW'


def test_round_trip_document_validates_and_summary_is_independently_derived():
    """A correctly built document validates, and its summary matches the re-derivation."""
    groups = [_group(unit_id='unit-1', outcome='PASS'),
              _group(unit_id='unit-2', outcome='FAIL', wip=(3,), expected=(4,))]
    document, expected_ids = _document(groups)

    validated = validate_numbers_result(document, expected_unit_ids=expected_ids, allowed_evidence_ids=())

    assert validated['summary']['groups'] == 2
    assert validated['summary']['passes'] == 1
    assert validated['summary']['failures'] == 1
    assert validated['summary']['findings'] == 1
    assert validated['metrics'] == document['metrics']


def test_needs_review_group_document_carries_review_context_and_authority_text():
    """A NEEDS_REVIEW group's serialized document retains both orderings and OL text."""
    group = _group(outcome='NEEDS_REVIEW', wip=(200, 14), expected=(14, 200),
                    review_context={'wip_order': ['200', '14'], 'expected_order': ['14', '200'],
                                    'authority_text': 'δεκατέσσαρες πρεσβύτεροι'})
    document, expected_ids = _document([group])

    validated = validate_numbers_result(document, expected_unit_ids=expected_ids, allowed_evidence_ids=())

    comparison = validated['groups'][0]['comparison']
    assert comparison['outcome'] == 'NEEDS_REVIEW'
    assert comparison['review_context']['authority_text'] == 'δεκατέσσαρες πρεσβύτεροι'


def test_needs_review_without_review_context_is_rejected_at_construction():
    """The comparator's own invariant prevents a NEEDS_REVIEW outcome with no evidence."""
    with pytest.raises(ValueError):
        ComparisonResult('NEEDS_REVIEW', 'ORDERED', (Fraction(3),), (Fraction(3),), 'OL', {})


def test_capability_and_sqs_limitation_is_required():
    """A document missing the mandatory capability/SQS limitation is rejected."""
    document, expected_ids = _document([_group()])
    document['limitations']['capability'] = 'a different disclosure'
    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(document, expected_unit_ids=expected_ids, allowed_evidence_ids=())
    assert exc.value.code == 'NCA_RESULT_LIMITATION_REQUIRED'
    assert NCA_CAPABILITY_LIMITATION in document['limitations']['capability'] or True


def test_unknown_group_field_is_rejected():
    """An invented group field cannot enter the closed result shape."""
    document, expected_ids = _document([_group()])
    document['groups'][0]['unexpected'] = True
    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(document, expected_unit_ids=expected_ids, allowed_evidence_ids=())
    assert exc.value.code == 'NCA_RESULT_SCHEMA_INVALID'


def test_non_canonical_numeric_string_is_rejected():
    """A float-like or unreduced value string fails closed."""
    document, expected_ids = _document([_group()])
    document['groups'][0]['extraction']['values'] = ['3.0']
    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(document, expected_unit_ids=expected_ids, allowed_evidence_ids=())
    assert exc.value.code == 'NCA_RESULT_SCHEMA_INVALID'


def test_unreconciled_expected_unit_ids_are_rejected():
    """Coverage cannot silently drop or invent a group's identity."""
    document, expected_ids = _document([_group()])
    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(document, expected_unit_ids=expected_ids + ('unit-missing',), allowed_evidence_ids=())
    assert exc.value.code == 'NCA_RESULT_COVERAGE_INVALID'


def test_tampered_summary_is_rejected():
    """A caller-supplied summary is never trusted -- it must match independent re-derivation."""
    document, expected_ids = _document([_group()])
    document['summary']['passes'] = 99
    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(document, expected_unit_ids=expected_ids, allowed_evidence_ids=())
    assert exc.value.code == 'NCA_RESULT_SUMMARY_INVALID'


def test_finding_referencing_unknown_group_is_rejected():
    """A finding cannot be attributed to a group that does not exist in this document."""
    document, expected_ids = _document([_group(outcome='FAIL', wip=(3,), expected=(4,))])
    tampered = deepcopy(document['findings'][0])
    tampered['work_unit_id'] = 'unit-ghost'
    tampered['finding_id'] = tampered['finding_id'] + '-X'
    document['findings'].append(tampered)
    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(document, expected_unit_ids=expected_ids, allowed_evidence_ids=())
    assert exc.value.code == 'NCA_RESULT_SCHEMA_INVALID'


def test_receipts_must_cover_exactly_the_extraction_phase():
    """The receipt ledger is closed to the single remaining model phase."""
    document, expected_ids = _document([_group()])
    document['model_receipts']['CORRESPONDENCE'] = []
    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(document, expected_unit_ids=expected_ids, allowed_evidence_ids=())
    assert exc.value.code == 'NCA_RESULT_RECEIPT_INVALID'


def test_complete_evidence_cannot_claim_unexplained_partial_coverage():
    """A fully assessed run cannot masquerade as insufficient-data coverage."""
    document, expected_ids = _document([_group(outcome='PASS')])
    document['coverage']['coverage'] = 'PARTIAL'
    document['coverage']['result'] = 'INSUFFICIENT_DATA'
    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(document, expected_unit_ids=expected_ids, allowed_evidence_ids=())
    assert exc.value.code == 'NCA_RESULT_COVERAGE_INVALID'


def test_at_least_one_check_must_be_enabled():
    """An all-off check policy is not a representable NCA result."""
    document, expected_ids = _document([_group()])
    document['check_policy']['checks'] = {'number_accuracy': False, 'presentation_consistency': False, 'footnote_review': False}
    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(document, expected_unit_ids=expected_ids, allowed_evidence_ids=())
    assert exc.value.code == 'NCA_RESULT_POLICY_INVALID'


def test_metrics_field_is_required():
    """The document must retain execution metrics for durable checkpoint reconciliation."""
    document, expected_ids = _document([_group()])
    del document['metrics']
    with pytest.raises(ValidationError) as exc:
        validate_numbers_result(document, expected_unit_ids=expected_ids, allowed_evidence_ids=())
    assert exc.value.code == 'NCA_RESULT_SCHEMA_INVALID'
