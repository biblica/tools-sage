"""Render canonical NCA machine results as bounded Operator-facing Markdown."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .errors import ValidationError
from .human_output import catalogue_text
from .numbers.results import NCA_CAPABILITY_LIMITATION


_ENGLISH = {
    "report.nca.title": "Number Consistency & Accuracy report",
    "report.nca.authority": "Authority and analyzed snapshot",
    "report.nca.summary": "Summary",
    "report.nca.coverage": "Coverage",
    "report.nca.limitations": "Limitations",
    "report.nca.capability_limitation": NCA_CAPABILITY_LIMITATION,
    "report.nca.checks": "Selected checks",
    "report.nca.units": "Units",
    "report.nca.findings": "Findings",
    "report.nca.no_findings": "No NCA findings were recorded.",
    "report.nca.target_reference": "Target reference",
    "report.nca.target_locator": "Target locator",
    "report.nca.western_reference": "Western reference",
    "report.nca.ol_reference": "Original-language reference",
    "report.nca.selected_reading": "Selected reading",
    "report.nca.source_ids": "Source IDs",
    "report.nca.footnote_action": "Footnote action",
    "report.nca.footnote_status": "Footnote status",
    "report.nca.suggested_note": "Suggested note",
    "report.nca.code": "Code",
    "report.nca.category": "Category",
    "report.nca.outcome": "Outcome",
    "report.nca.restrictions": "Restrictions",
    "report.nca.model_identity": "Model identity",
    "report.nca.style_profile": "Style profile",
    "report.nca.reference_package": "Reference package",
    "report.nca.expressions": "Expressions",
    "report.nca.insufficient_evidence": "Insufficient evidence",
    "report.nca.reference_not_indexed": "Reference not indexed",
    "report.nca.not_assessed": "Not assessed",
    "report.nca.result": "Result",
    "report.nca.confidence_basis": "Confidence basis",
    "report.nca.ol_expressions_checked": "OL expressions checked",
    "report.nca.target_expressions": "Target expressions",
    "report.nca.passes": "Passes",
    "report.nca.unit_conversions": "Unit conversions",
    "report.nca.value_differences": "Value differences",
    "report.nca.missing_numbers": "Missing numbers",
    "report.nca.added_numbers": "Added numbers",
    "report.nca.known_variants": "Known variants",
    "report.nca.style_findings": "Style findings",
    "report.nca.source_expressions": "OL source expressions",
    "report.nca.variant_class": "Variant class",
    "report.nca.scholarship_status": "Scholarship status",
}
_ENGLISH.update({
    'report.nca.chapters': 'WIP chapters',
    'report.nca.unlocated': 'Unlocated WIP coverage',
    'report.nca.alignment': 'Alignment',
    'report.nca.cross_reference': 'See primary evidence',
    'report.nca.parent_group': 'Protected parent group',
    'report.nca.planned_inputs': 'Planned extraction inputs',
    'report.nca.planned_extraction_calls': 'Planned extraction calls (initial batches)',
    'report.nca.executed_calls': 'Executed calls',
    'report.nca.reused_checkpoints': 'Reused checkpoints',
    'report.nca.blocked_inputs': 'Blocked extraction inputs',
    'report.nca.missing_owners': 'Groups without extraction',
    'report.nca.scope_expansion': 'Scope expansion',
    'report.nca.requested_scope': 'Requested scope',
    'report.nca.row_evidence': 'Exact row evidence',
    'report.nca.indexed_coordinates': 'Indexed coordinates',
    'report.nca.unindexed_coordinates': 'Unindexed coordinates',
    'report.nca.extraction_complete': 'Complete extractions',
    'report.nca.extraction_partial': 'Partial extractions',
    'report.nca.extraction_unsupported': 'Unsupported extractions',
    'report.nca.unresolved_targets': 'Unresolved target expressions',
    'report.nca.uncertain_navigation': 'Row ownership is unresolved; use the protected WIP range.',
    'report.nca.unlocated_navigation': 'No proven WIP location; Western coordinates below identify coverage only.',
    'report.nca.planning_notice': 'Planning estimates describe initial extraction batches, not measured time, cost or model qualification. Semantic calls and retries depend on evidence.',
    'report.nca.preflight': 'Scoped preflight',
    'report.nca.reference_expectations': 'Reference expectations (Western)',
    'report.nca.protected_groups': 'Protected groups',
    'report.nca.mandatory_profile': 'Number Style Profile (optional)',
    'report.nca.input_language': 'Input language and script',
    'report.nca.failed_calls': 'Failed calls',
    'report.nca.exact_evidence': 'Exact evidence',
    'report.nca.usage_title': 'Number Usage Report',
    'report.nca.usage_notice': 'Observed usage in this Run scope, derived from accepted numeric extraction. Counts describe observed expressions; partial extraction is not complete coverage.',
    'report.nca.usage_forms': 'Observed forms',
    'report.nca.usage_stream': 'Text location',
    'report.nca.usage_form': 'Form',
    'report.nca.usage_details': 'Numeric details',
    'report.nca.usage_mixed': 'Mixed usage for operator review',
    'report.nca.usage_mixed_notice': 'Mixed forms can be appropriate in different contexts. These observations are not violations of approved rules; they do not create a stylesheet. Separator characters are observed without assuming a decimal or grouping convention.',
    'report.nca.usage_no_mixed': 'No mixed usage identified in the available extracted evidence.',
    'report.nca.no_stylesheet': 'No stylesheet selected. Checks against approved rules are not assessed; numeric accuracy and footnote review remain independent.',
})
_ENGLISH_LANGUAGES = frozenset({"en", "en-US", "en-GB"})
_CATALOG_LANGUAGES = _ENGLISH_LANGUAGES | {"id", "fr", "ru", "pt-BR", "uk"}


def _localization_function(
    *, language: str, localize: Callable[[str], str] | object | None
) -> Callable[[str], str]:
    """Resolve an explicit report-language catalog without silent English fallback."""
    if localize is None:
        if language not in _CATALOG_LANGUAGES:
            raise ValidationError(
                f"NCA report localization is unavailable for {language}.",
                code="NCA_REPORT_TRANSLATION_REQUIRED",
            )
        return lambda key: (
            _ENGLISH[key]
            if catalogue_text(language, key) == key
            else catalogue_text(language, key)
        )
    function = localize if callable(localize) else getattr(localize, "text_key", None)
    if not callable(function):
        raise ValidationError(
            "NCA report localizer must be callable or expose text_key().",
            code="NCA_REPORT_TRANSLATION_REQUIRED",
        )

    def localized(key: str) -> str:
        """Return catalog text, retaining English only for visibly unresolved labels."""
        value = function(key)
        if not isinstance(value, str) or not value.strip() or value == key:
            if key == "report.nca.capability_limitation" and language not in _ENGLISH_LANGUAGES:
                raise ValidationError(
                    f"NCA capability limitation is not localized for {language}.",
                    code="NCA_REPORT_TRANSLATION_REQUIRED",
                )
            return _ENGLISH[key]
        return value

    return localized


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    """Require one report section to be a mapping before rendering it."""
    if not isinstance(value, Mapping):
        raise ValidationError(
            f"NCA report {label} is malformed.", code="NCA_RESULT_SCHEMA_INVALID"
        )
    return value


def _joined(value: object) -> str:
    """Render a bounded sequence without changing the stored identifiers."""
    if not isinstance(value, (list, tuple)):
        return "NOT RECORDED"
    return ", ".join("NULL" if item is None else str(item) for item in value) or "NOT RECORDED"


def _locator(value: object) -> str:
    """Render the immutable target source locator in stable key order."""
    if not isinstance(value, Mapping):
        return "NOT RECORDED"
    return ", ".join(f"{key}={value[key]}" for key in sorted(value)) or "NOT RECORDED"


def _model_identities(value: object, *, grouped: bool = False) -> tuple[str, ...]:
    """Collect exact provider/model identities from actual phase receipts."""
    if not isinstance(value, Mapping):
        return ()
    identities: list[str] = []
    for phase in ("EXTRACTION", "CORRESPONDENCE", "FOOTNOTE") + (("GROUP_CORRESPONDENCE",) if grouped else ()):
        rows = value.get(phase, ())
        if not isinstance(rows, (list, tuple)):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            provider, model = row.get("provider"), row.get("model")
            if isinstance(provider, str) and provider and isinstance(model, str) and model:
                identity = f"{phase}: {provider}/{model}"
                if identity not in identities:
                    identities.append(identity)
    return tuple(identities)


def _expressions(value: object) -> str:
    """Render typed source expressions without changing their canonical values."""
    if not isinstance(value, (list, tuple)):
        return "NOT RECORDED"
    rendered: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        attributes = [str(item.get("kind") or "UNKNOWN")]
        for key in ("role", "unit", "qualifier"):
            if item.get(key) is not None:
                attributes.append(f"{key}={item[key]}")
        rendered.append(
            f"{item.get('surface', 'NOT RECORDED')} = {_joined(item.get('values'))} "
            f"[{' ; '.join(attributes)}]"
        )
    return "; ".join(rendered) or "NOT RECORDED"


def chapter_sections(document: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    """Assign each canonical parent and finding once using only proven WIP coordinates."""
    from sage.references import BOOK_ORDER
    import re

    groups = document.get('groups', document.get('units', ()))
    findings = document.get('findings', ())
    sections: dict[tuple[str | None, int | None], dict[str, Any]] = {}
    owners = {}
    by_owner: dict[str, list[str]] = {}
    seen_findings = set()
    for finding in findings:
        identity = finding['finding_id']
        if identity in seen_findings:
            raise ValidationError('Duplicate canonical finding', code='NCA_RESULT_FINDING_INVALID')
        seen_findings.add(identity)
        by_owner.setdefault(finding['work_unit_id'], []).append(identity)

    def coordinate(label):
        """Read a canonical WIP coordinate without interpreting Western or OL labels."""
        match = re.fullmatch(r'([A-Z0-9]{3}) (\d+):(\d+)', label)
        if match is None:
            raise ValidationError('Invalid WIP coordinate', code='NCA_RESULT_REFERENCE_INVALID')
        book, chapter, verse = match.groups()
        return BOOK_ORDER.get(book, 999), book, int(chapter), int(verse)

    ordered = sorted(groups, key=lambda group: (
        min((coordinate(ref) for ref in group['projection']['target_references']), default=(1000, '', 0, 0)),
        group['unit_id']))
    for group in ordered:
        identity = group['unit_id']
        if identity in owners:
            raise ValidationError('Duplicate canonical parent', code='NCA_RESULT_COVERAGE_INVALID')
        refs = sorted(group['projection']['target_references'], key=coordinate)
        chapters = list(dict.fromkeys((coordinate(ref)[1], coordinate(ref)[2]) for ref in refs)) or [(None, None)]
        primary = chapters[0]
        owners[identity] = primary
        for key in chapters:
            section = sections.setdefault(key, {'book': key[0], 'chapter': key[1],
                'group_ids': [], 'finding_ids': [], 'cross_references': [], 'target_references': []})
            section['target_references'].extend(ref for ref in refs
                if (coordinate(ref)[1], coordinate(ref)[2]) == key and ref not in section['target_references'])
            if key == primary:
                section['group_ids'].append(identity)
                section['finding_ids'].extend(by_owner.get(identity, ()))
            else:
                section['cross_references'].append({'group_id': identity,
                    'book': primary[0], 'chapter': primary[1],
                    'finding_ids': tuple(by_owner.get(identity, ()))})
    if set(by_owner) - set(owners):
        raise ValidationError('Finding has no canonical parent', code='NCA_RESULT_FINDING_INVALID')
    return tuple({key: tuple(value) if isinstance(value, list) else value for key, value in sections[identity].items()}
        for identity in sorted(sections, key=lambda key: (BOOK_ORDER.get(key[0], 1000), key[0] or '', key[1] or 0)))


def _anchor(identity: str, kind: str) -> str:
    """Generate a safe stable Markdown destination without changing canonical identities."""
    from hashlib import sha256
    return 'nca-' + kind + '-' + sha256(identity.encode('utf-8')).hexdigest()[:20]


def _exact(value: object) -> str:
    """Quote exact structured evidence without letting source text become report markup."""
    import json
    return json.dumps(value, ensure_ascii=False, sort_keys=True).replace('`', '\\u0060').replace('<', '\\u003c')


def _optimized_metrics(document, text) -> list[str]:
    """Expose sealed planning and observed work separately without estimating missing history."""
    metrics = document.get('metrics', {})
    planning = metrics.get('planning', {})
    coverage = document['coverage']
    values = {
        'planned_extraction_calls': planning.get('planned_extraction_calls', 'NOT RECORDED'),
        'planned_inputs': len(planning['input_ids']) if 'input_ids' in planning else 'NOT RECORDED',
        'executed_calls': metrics.get('provider_calls', 'NOT RECORDED'),
        'reused_checkpoints': metrics.get('checkpoint_reuse', 'NOT RECORDED'),
        'failed_calls': metrics.get('failed_calls', 'NOT RECORDED'),
    }
    lines = [f"- {text('report.nca.' + key)}: `{value}`" for key, value in values.items()]
    for key in ('indexed_coordinates', 'unindexed_coordinates', 'extraction_complete', 'extraction_partial', 'extraction_unsupported'):
        lines.append(f"- {text('report.nca.' + key)}: `{document['summary'].get(key, 'NOT RECORDED')}`")
    for key, value in (('blocked_inputs', planning.get('blocked')), ('missing_owners', planning.get('missing_owner_ids')),
                       ('requested_scope', coverage.get('requested_scope')), ('scope_expansion', coverage.get('scope_expansions'))):
        lines.append(f"- {text('report.nca.' + key)}: `{_exact(value)}`")
    return lines + ['', text('report.nca.planning_notice'), '']


def _group_lines(group, text) -> list[str]:
    """Keep exact per-row evidence beneath its one protected target extraction parent."""
    projection = group['projection']
    lines = [f'<a id="{_anchor(group["unit_id"], "group")}"></a>', f"### `{group['unit_id']}`", '',
        f"- {text('report.nca.target_reference')}: {_joined(projection['target_references'])}",
        f"- {text('report.nca.target_locator')}: {_locator(projection.get('source_locator'))}",
        f"- {text('report.nca.western_reference')}: {_joined(projection['western_references'])}",
        f"- {text('report.nca.alignment')}: `{group['alignment_status']}`",
        f"- {text('report.nca.target_expressions')}: {_expressions(group['extraction']['expressions'])}",
        f"- {text('report.nca.exact_evidence')}: `{_exact(group['extraction'])}`",
        f"- {text('report.nca.unresolved_targets')}: {_joined(group['unresolved_target_ids'])}"]
    if not projection['target_references']:
        lines.extend(['', text('report.nca.unlocated_navigation')])
    elif group['alignment_status'] in {'PARTIAL', 'UNAVAILABLE'}:
        lines.extend(['', text('report.nca.uncertain_navigation')])
    lines.extend(['', f"- {text('report.nca.exact_evidence')}: `{_exact({'projection': projection, 'expression_ownership': group['expression_ownership'], 'unmatched_target_ids': group['unmatched_target_ids'], 'style_findings': group['style_findings']})}`",
        f"- {text('report.nca.limitations')}: {_joined(group['limitations'])}", ''])
    # The Western row is the source-expression namespace. Target IDs stay on
    # the extraction parent; row-specific components never replace that parent.
    components = {row['western_reference']: row for row in group['components']}
    for row in group['reference_rows']:
        component = components.get(row['western_reference'])
        lines.extend(['', f"#### {text('report.nca.western_reference')}: `{row['western_reference']}`", '',
            f"- {text('report.nca.ol_reference')}: `{'NULL' if row['ol_reference'] is None else row['ol_reference']}`",
            f"- {text('report.nca.coverage')}: `{row['status']}`",
            f"- {text('report.nca.row_evidence')}: `{_exact(row)}`"])
        if component is not None:
            reading, note = component['reading'], component['footnote']
            lines.extend([
                f"- {text('report.nca.outcome')}: `{component['final_outcome']}`",
                f"- {text('report.nca.source_expressions')}: {_expressions(component['source_expressions'])}",
                f"- {text('report.nca.selected_reading')}: `{reading['selected']}`",
                f"- {text('report.nca.source_ids')}: {_joined(reading['source_ids'])}",
                f"- {text('report.nca.footnote_action')}: `{note['action']}`",
                f"- {text('report.nca.footnote_status')}: `{note['status']}`",
                f"- {text('report.nca.exact_evidence')}: `{_exact(component)}`"])
    return lines


def _chapter_lines(document, text) -> list[str]:
    """Render navigation links without copying canonical evidence or findings."""
    groups = {group['unit_id']: group for group in document['groups']}
    findings = {finding['finding_id']: finding for finding in document['findings']}
    lines = []
    for section in chapter_sections(document):
        title = f"{section['book']} {section['chapter']}" if section['book'] else text('report.nca.unlocated')
        lines.extend([f'## {title}', ''])
        for group_id in section['group_ids']:
            lines.extend(_group_lines(groups[group_id], text))
        for finding_id in section['finding_ids']:
            finding = findings[finding_id]
            owner = finding['work_unit_id']
            refs = groups[owner]['projection']['target_references']
            lines.extend([f'<a id="{_anchor(finding_id, "finding")}"></a>', *_finding_lines(finding, text),
                f"- {text('report.nca.parent_group')}: [{owner}](#{_anchor(owner, 'group')})",
                f"- WIP: {_joined(refs)}", ''])
        for cross in section['cross_references']:
            owner = cross['group_id']
            links = [f"[{owner}](#{_anchor(owner, 'group')})"]
            links.extend(f"[{identity}](#{_anchor(identity, 'finding')})" for identity in cross['finding_ids'])
            lines.extend([f"- {text('report.nca.cross_reference')}: " + ', '.join(links), ''])
    if not findings:
        lines.append(text('report.nca.no_findings') if document['coverage']['result'] == 'NO_FINDINGS'
                     else f"`{document['coverage']['result']}`")
    return lines


def _finding_lines(finding, text) -> list[str]:
    """Render canonical finding fields without altering stored coordinates or identities."""
    return [
        f"### `{finding.get('finding_id', 'NOT RECORDED')}`",
        "",
        f"- {text('report.nca.code')}: `{finding.get('code', 'NOT RECORDED')}`",
        f"- {text('report.nca.category')}: `{finding.get('category', 'NOT RECORDED')}`",
        f"- {text('report.nca.target_reference')}: `{finding.get('target_reference') or 'NOT RECORDED'}`",
        f"- {text('report.nca.western_reference')}: {_joined(finding.get('western_references'))}",
        f"- {text('report.nca.ol_reference')}: `{finding.get('ol_reference') or 'NOT RECORDED'}`",
        f"- {text('report.nca.selected_reading')}: `{finding.get('selected_reading') or 'NOT RECORDED'}`",
        f"- {text('report.nca.source_ids')}: {_joined(finding.get('source_ids'))}",
        f"- {text('report.nca.footnote_action')}: `{finding.get('footnote_action') or 'NOT RECORDED'}`",
        f"- {text('report.nca.footnote_status')}: `{finding.get('footnote_status') or 'NOT RECORDED'}`",
        f"- {text('report.nca.suggested_note')}: {finding.get('suggested_note') or 'NOT RECORDED'}",
        "",
    ]


def render_nca_report(
    document: Mapping[str, object],
    *,
    language: str = "en",
    localize: Callable[[str], str] | object | None = None,
) -> str:
    """Render NCA evidence while localizing only human-facing prose and labels."""
    if not isinstance(document, Mapping) or document.get("check_id") != "NUMBERS":
        raise ValidationError(
            "NCA report requires a canonical NUMBERS result.",
            code="NCA_RESULT_SCHEMA_INVALID",
        )
    limitations = _mapping(document.get("limitations"), "limitations")
    if (
        limitations.get("capability") != NCA_CAPABILITY_LIMITATION
        or limitations.get("sqs_confidence_checks_applied") is not False
    ):
        raise ValidationError(
            "The NCA capability and SQS limitation is required.",
            code="NCA_RESULT_LIMITATION_REQUIRED",
        )
    text = _localization_function(language=language, localize=localize)
    provenance = _mapping(document.get("provenance"), "provenance")
    style = _mapping(provenance.get("style_profile"), "style profile")
    reference = _mapping(provenance.get("reference_package"), "reference package")
    wip = _mapping(provenance.get("wip"), "WIP")
    checks = _mapping(_mapping(document.get("check_policy"), "check policy").get("checks"), "checks")
    coverage = _mapping(document.get("coverage"), "coverage")
    summary = _mapping(document.get("summary"), "summary")
    findings = document.get("findings")
    is_v2 = document.get("schema_version") == "2.0"
    units = document.get("groups" if is_v2 else "units")
    if not isinstance(findings, (list, tuple)) or not isinstance(units, (list, tuple)):
        raise ValidationError(
            "NCA report units or findings are malformed.", code="NCA_RESULT_SCHEMA_INVALID"
        )

    # Human labels may change language; every backticked identity remains canonical machine evidence.
    lines = [
        f"# {text('report.nca.title')}",
        "",
        f"## {text('report.nca.authority')}",
        "",
        f"- Job: `{provenance.get('job_id', 'NOT RECORDED')}`",
        f"- Run: `{provenance.get('run_id', 'NOT RECORDED')}`",
        f"- WIP: `{wip.get('identity', 'NOT RECORDED')}` (`{wip.get('sha256', 'NOT RECORDED')}`)",
        (f"- {text('report.nca.style_profile')}: `{style['selector']}` (`{style.get('sha256', 'NOT RECORDED')}`)"
         if style.get('selector') else f"- {text('report.nca.no_stylesheet')}"),
        f"- {text('report.nca.reference_package')}: `{reference.get('package_id', 'NOT RECORDED')}` (`{reference.get('sha256', 'NOT RECORDED')}`)",
        "",
        f"## {text('report.nca.checks')}",
        "",
    ]
    lines.extend(
        f"- `{name}`: `{'ON' if enabled is True else 'OFF'}`"
        for name, enabled in checks.items()
    )
    lines.extend(
        [
            "",
            f"## {text('report.nca.model_identity')}",
            "",
        ]
    )
    identities = _model_identities(document.get("model_receipts"), grouped=is_v2)
    assessed_units = any(
        isinstance(unit, Mapping)
        and isinstance(unit.get("extraction"), Mapping)
        and unit["extraction"].get("status") != "UNSUPPORTED"
        for unit in units
    )
    if assessed_units and not identities:
        raise ValidationError(
            "Assessed NCA units require actual model identity.",
            code="NCA_RESULT_RECEIPT_INVALID",
        )
    lines.extend(f"- `{identity}`" for identity in identities)
    if not identities:
        lines.append("- `NOT RECORDED`")
    lines.extend(
        [
            "",
            f"## {text('report.nca.summary')}",
            "",
            f"- {text('report.nca.units')}: `{summary.get('units', 0)}`",
            f"- {text('report.nca.expressions')}: `{summary.get('expressions', 0)}`",
            f"- {text('report.nca.target_expressions')}: `{summary.get('target_expressions', 0)}`",
            f"- {text('report.nca.ol_expressions_checked')}: `{summary.get('ol_expressions_checked', 0)}`",
            f"- {text('report.nca.passes')}: `{summary.get('passes', 0)}`",
            f"- {text('report.nca.unit_conversions')}: `{summary.get('unit_conversions', 0)}`",
            f"- {text('report.nca.value_differences')}: `{summary.get('value_differences', 0)}`",
            f"- {text('report.nca.missing_numbers')}: `{summary.get('missing_numbers', 0)}`",
            f"- {text('report.nca.added_numbers')}: `{summary.get('added_numbers', 0)}`",
            f"- {text('report.nca.known_variants')}: `{summary.get('known_variants', 0)}`",
            f"- {text('report.nca.style_findings')}: `{summary.get('style_findings', 0)}`",
            f"- {text('report.nca.findings')}: `{summary.get('findings', 0)}`",
            f"- {text('report.nca.insufficient_evidence')}: `{summary.get('insufficient_evidence', 0)}`",
            f"- {text('report.nca.reference_not_indexed')}: `{summary.get('reference_not_indexed', 0)}`",
            f"- {text('report.nca.not_assessed')}: `{summary.get('not_assessed', 0)}`",
            "",
            f"## {text('report.nca.coverage')}",
            "",
            f"- {text('report.nca.result')}: `{coverage.get('result', 'NOT RECORDED')}`",
            f"- {text('report.nca.coverage')}: `{coverage.get('coverage', 'NOT RECORDED')}`",
            f"- {text('report.nca.confidence_basis')}: `{coverage.get('confidence_basis', 'NOT RECORDED')}`",
            f"- {text('report.nca.restrictions')}: {_joined(coverage.get('restrictions'))}",
            "",
            f"## {text('report.nca.chapters' if is_v2 else 'report.nca.units')}",
            "",
        ]
    )
    if is_v2:
        lines.extend(_optimized_metrics(document, text))
        lines.extend(_chapter_lines(document, text))
    for raw_unit in (() if is_v2 else units):
        unit = _mapping(raw_unit, "unit")
        projection = _mapping(unit.get("projection"), "unit projection")
        reading = _mapping(unit.get("reading"), "unit reading")
        footnote = _mapping(unit.get("footnote"), "unit footnote")
        source_evidence = _mapping(unit.get("source_evidence"), "unit source evidence")
        source_context = _mapping(source_evidence.get("context"), "unit source context")
        lines.extend(
            [
                f"### `{unit.get('unit_id', 'NOT RECORDED')}`",
                "",
                f"- {text('report.nca.target_reference')}: {_joined(projection.get('target_references'))}",
                f"- {text('report.nca.target_locator')}: {_locator(projection.get('source_locator'))}",
                f"- {text('report.nca.western_reference')}: {_joined(projection.get('western_references'))}",
                f"- {text('report.nca.ol_reference')}: {_joined(projection.get('ol_references'))}",
                f"- {text('report.nca.selected_reading')}: `{reading.get('selected', 'NOT RECORDED')}`",
                f"- {text('report.nca.source_ids')}: {_joined(reading.get('source_ids'))}",
                f"- {text('report.nca.source_expressions')}: {_expressions(source_evidence.get('expressions'))}",
                f"- {text('report.nca.variant_class')}: `{source_context.get('variant_class') or 'NOT RECORDED'}`",
                f"- {text('report.nca.scholarship_status')}: `{source_context.get('scholarship_status') or 'NOT RECORDED'}`",
                f"- {text('report.nca.footnote_action')}: `{footnote.get('action', 'NOT RECORDED')}`",
                f"- {text('report.nca.footnote_status')}: `{footnote.get('status', 'NOT RECORDED')}`",
                f"- {text('report.nca.outcome')}: `{unit.get('final_outcome', 'NOT RECORDED')}`",
                "",
            ]
        )
    if not is_v2:
        lines.extend([f"## {text('report.nca.findings')}", ""])
    if not is_v2 and not findings:
        if coverage.get("result") == "NO_FINDINGS":
            lines.append(text("report.nca.no_findings"))
        else:
            lines.append(f"`{coverage.get('result', 'NOT ASSESSED')}`")
    for raw_finding in (() if is_v2 else findings):
        finding = _mapping(raw_finding, "finding")
        lines.extend(_finding_lines(finding, text))
    from .numbers.usage import render_number_usage
    lines.extend(render_number_usage(document, text))
    lines.extend(
        [
            f"## {text('report.nca.limitations')}",
            "",
            text("report.nca.capability_limitation"),
            "",
            "SQS: `NOT_APPLIED`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"
