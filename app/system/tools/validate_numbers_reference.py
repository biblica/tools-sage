#!/usr/bin/env python3
"""Qualify supplied NCA reference bytes without changing the inherited artifact gate."""
from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from fractions import Fraction
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import sys
import time
import tracemalloc

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'system/src'))

from sage.atomic import atomic_write_json
from sage.errors import ValidationError
from sage.numbers.models import Extraction, NumericExpression, SemanticDecision
from sage.numbers.reference import REFERENCE_PARSER_VERSION, load_reference, parse_values
from sage.numbers.units import compare_registered_units, parse_registered_quantity
from sage.numbers.variants import select_reading
from sage.vrs import VerseRef

LIMITATION = "Findings are limited by the selected LLM's language understanding and numeric-interpretation capabilities. SQS confidence checks have not been applied."
EXPECTED_COUNTS = {'rows': 6244, 'numeric_rows': 4392, 'ol_values': 6800, 'variants': 21, 'footnote_guidance': 21, 'unit_examples': 12, 'provenance_sources': 38}
EXPECTED_PACKAGE_SHA256 = 'b04a08e7e51e405defeb1c1821a8fb3c63bf1af4f6bda7ce7c4fff268b19b202'
ACCEPTANCE_VALUES = {
    'GEN 14:14': '318', 'JDG 7:3': '22000;10000', 'JDG 20:10': '10;100;100;1000;1000;10000',
    '1SA 25:2': '3000;1000', 'PSA 91:7': '1000;10000', 'EXO 25:10': '5/2;3/2;3/2',
    '1CH 24:11': '9;10', '1KI 18:44': '7', 'ZEC 3:9': '1;7;1',
    'REV 5:11': '10000;10000;1000;1000', 'REV 4:7': '1;2;3;4', 'REV 6:8': '1/4',
    'PSA 60:0': '12000', '1SA 20:42': '2', '1CH 12:4': '30;30',
}


def _require(condition: bool, message: str) -> None:
    """Fail release qualification explicitly for missing or contradictory evidence."""
    if not condition:
        raise ValidationError(message, code='NCA_RELEASE_QUALIFICATION_FAILED')


def _plain(value):
    """Serialize immutable diagnostic containers without changing canonical values."""
    from collections.abc import Mapping
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _golden_readings(bundle) -> list[dict[str, object]]:
    """Check all authorized whole-reading values and retained source policy outcomes."""
    fixture = ROOT / 'system/tests/numbers/fixtures/registered-readings.json'
    _require(fixture.is_file(), 'Required NCA reading acceptance fixture is absent.')
    cases = json.loads(fixture.read_text(encoding='utf-8'))
    _require(len(cases) == 21, 'The complete 21-reading acceptance matrix is required.')
    _require({VerseRef(case['BK'], int(case['CH']), int(case['VS'])) for case in cases} == set(bundle.variants), 'Reading acceptance must cover each registered coordinate exactly once.')
    outcomes = []
    for case in cases:
        ref = VerseRef(case['BK'], int(case['CH']), int(case['VS']))
        row = bundle.lookup(ref)
        _require(row is not None, f'Missing registered reading {ref.label()}.')
        _require(row.ol_values == parse_values(case['OL_VALUES']), f'Changed OL acceptance values at {ref.label()}.')
        _require(row.ol_reference == (case['OL_REF'] or None), f'Changed OL reference at {ref.label()}.')
        for choice, values in [('OL', row.ol_values), ('ALT', parse_values(case['ALT_NIV_VALUES']))]:
            decision = select_reading(row, values, bundle=bundle, semantic=SemanticDecision('PASS_AUTHORITY1'))
            _require(decision.selected == choice, f'Whole-reading selection failed at {ref.label()}.')
            _require(decision.footnote_action == case[f'FOOTNOTE_IF_TARGET_FOLLOWS_{choice}'], f'Changed disclosure policy at {ref.label()}.')
            _require(decision.source_validation_outcome == case[f'VALIDATION_IF_TARGET_FOLLOWS_{choice}'], f'Changed source policy at {ref.label()}.')
            _require(decision.source_ids == tuple(case['SOURCE_IDS'].split(';')), f'Changed provenance at {ref.label()}.')
            outcomes.append({'reference': ref.label(), 'reading': choice, 'semantic': decision.semantic.outcome,
                             'footnote_action': decision.footnote_action, 'source_policy': decision.source_validation_outcome})
    return outcomes


def _golden_units(bundle) -> list[dict[str, object]]:
    """Check exact registered pairs with hand-specified retained unrelated quantities."""
    fixture = ROOT / 'system/tests/numbers/fixtures/registered-units.json'
    _require(fixture.is_file(), 'Required NCA unit acceptance fixture is absent.')
    cases = json.loads(fixture.read_text(encoding='utf-8'))
    _require(len(cases) == 12, 'The complete 12-unit acceptance matrix is required.')
    _require({VerseRef(case['BK'], int(case['CH']), int(case['VS'])) for case in cases} == set(bundle.units), 'Unit acceptance must cover each registered coordinate exactly once.')
    retained = {'LUK 24:13': (2,), 'JHN 2:6': (6,), 'JHN 19:39': (1,), 'REV 6:6': (4,)}
    outcomes = []
    for case in cases:
        ref = VerseRef(case['BK'], int(case['CH']), int(case['VS']))
        row = bundle.lookup(ref)
        _require(row is not None and ref in bundle.units, f'Missing unit example {ref.label()}.')
        for key in ('OL_QUANTITY', 'NIV_QUANTITY', 'SOURCE_IDS'):
            _require(bundle.units[ref][key] == case[key], f'Changed registered {key} at {ref.label()}.')
        extras = tuple(NumericExpression((Fraction(value),), 'CARDINAL', str(value), (0, len(str(value))), role='retained') for value in retained.get(ref.label(), ()))
        expressions = extras + tuple(replace(item, role=f'measure-{index}') for index, item in enumerate(parse_registered_quantity(case['NIV_QUANTITY'])))
        decision = compare_registered_units(row, Extraction(expressions, 'COMPLETE'), bundle=bundle)
        _require(decision.outcome == 'PASS_UNIT_CONVERSION', f'Registered unit acceptance failed at {ref.label()}.')
        outcomes.append({'reference': ref.label(), 'outcome': decision.outcome, 'source_ids': list(decision.evidence_ids)})
    return outcomes


def qualify(package: Path, *, release: bool = False) -> dict[str, object]:
    """Qualify integrity and optionally require the complete authorized acceptance package."""
    if not package.is_dir():
        raise ValidationError('The required NCA package directory is absent.', code='NCA_REFERENCE_NOT_IMPORTED')
    started = time.perf_counter()
    tracemalloc.start()
    try:
        bundle = load_reference(package, qualification='STRICT')
        bundle.require_qualified()
        counts = {'rows': len(bundle.rows), 'numeric_rows': sum(bool(row.ol_values) for row in bundle.rows.values()),
                  'ol_values': sum(len(row.ol_values) for row in bundle.rows.values()), 'variants': len(bundle.variants),
                  'footnote_guidance': len(bundle.footnote_guidance), 'unit_examples': len(bundle.units), 'provenance_sources': len(bundle.provenance)}
        readings, units, numeric_cases = [], [], []
        token_count = None
        if release:
            _require(bundle.sha256 == EXPECTED_PACKAGE_SHA256, 'Release qualification requires the unchanged authorized 2026-09-09 package.')
            _require(counts == EXPECTED_COUNTS, f'The authorized NCA package counts differ: {counts}.')
            lineage = next((item for item in bundle.diagnostics if item.get('code') == 'REFERENCE_LINEAGE_INCOMPLETE'), {})
            _require((lineage.get('differing_rows'), lineage.get('additional_authoritative_values'), lineage.get('new_numeric_rows'), lineage.get('supplementary_expression_count')) == (47, 51, 16, 6749), 'The documented supplementary-lineage warning must remain explicit.')
            readings, units = _golden_readings(bundle), _golden_units(bundle)
            for label, values in ACCEPTANCE_VALUES.items():
                book, coordinate = label.split()
                chapter, verse = coordinate.split(':')
                row = bundle.lookup(VerseRef(book, int(chapter), int(verse)))
                _require(row is not None and row.ol_values == parse_values(values), f'Numeric acceptance differs at {label}.')
                numeric_cases.append({'reference': label, 'ol_reference': row.ol_reference, 'values': values})
            _require(bundle.lookup(VerseRef('DAN', 1, 10)) is None, 'DAN 1:10 must remain unindexed, not a zero-value row.')
            with (package / 'reference/ol_token_coverage_audit.tsv').open(encoding='utf-8-sig', newline='') as source:
                token_count = sum(1 for _ in csv.DictReader(source, delimiter='\t'))
            _require(token_count == 341, 'The complete classified token audit requires 341 rows.')
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    dependencies = {}
    for name in ('PyYAML', 'pytest', 'openpyxl'):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = 'NOT_INSTALLED'
    return {'schema_version': '1.0', 'status': 'PASS', 'mode': 'RELEASE' if release else 'INTEGRITY',
            'package_id': bundle.package_id, 'package_sha256': bundle.sha256, 'parser_version': REFERENCE_PARSER_VERSION,
            'qualification_status': bundle.qualification_status, 'counts': counts,
            'diagnostics': [_plain(item) for item in bundle.diagnostics], 'reading_cases': readings, 'unit_cases': units,
            'numeric_cases': numeric_cases, 'classified_token_rows': token_count,
            'runtime': {'python': platform.python_version(), 'platform': platform.platform(), 'dependencies': dependencies},
            'measurement': {'seconds': round(time.perf_counter() - started, 4), 'peak_traced_bytes': peak},
            'model_execution': 'NOT_RUN', 'sqs_checks_applied': False, 'capability_limitation': LIMITATION,
            'limits': ['Reference/domain acceptance does not measure target-language LLM accuracy.', 'Registered unit pairs preserve unrelated OL quantities; NIV residual changes at LUK 16:7 and JHN 19:39 remain review cases.', 'Original PENDING_FINAL_RUN gate and package contents are unchanged.', 'Supplied Scripture bundles are not distributed by this command.']}


def main(argv=None) -> int:
    """Write a separate machine receipt and return nonzero for failed qualification."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--release', action='store_true')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.receipt and args.receipt.resolve().is_relative_to(args.package.resolve()):
            raise ValidationError('The qualification receipt must be outside the immutable package.', code='NCA_RECEIPT_PATH_INVALID')
        result = qualify(args.package, release=args.release)
        if args.receipt:
            atomic_write_json(args.receipt, result)
    except (ValidationError, OSError) as exc:
        result = {'status': 'FAIL', 'code': getattr(exc, 'code', 'NCA_REFERENCE_IO_ERROR'), 'error': str(exc), 'sqs_checks_applied': False, 'capability_limitation': LIMITATION}
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
